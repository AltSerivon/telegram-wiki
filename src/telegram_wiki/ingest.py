from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from telegram_wiki.config import get_settings
from telegram_wiki.crud import get_or_create_cursor
from telegram_wiki.db.models import CompanyGroup, Membership, TelegramPeer
from telegram_wiki.telethon_service import build_input_peer, classify_entity, telegram_client
from telegram_wiki.vault import company_abs_path, ensure_company_vault


def _safe_label(peer: TelegramPeer) -> str:
    if peer.username:
        return peer.username.replace("/", "_")
    return f"{peer.peer_type}-{peer.peer_id}"


def _message_block(msg) -> str:
    mid = msg.id
    dt = msg.date
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    iso = dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    sender = ""
    if msg.sender:
        s = msg.sender
        sender = getattr(s, "username", None) or getattr(s, "first_name", "") or str(getattr(s, "id", ""))
    text = msg.message or ""
    lines = [
        f"## msg-{mid} | {iso} | {sender}",
        "",
        text,
        "",
        "---",
        "",
    ]
    return "\n".join(lines)


async def ingest_company(session: Session, company: CompanyGroup) -> dict:
    settings = get_settings()
    root = company_abs_path(settings, company.vault_rel_path)
    ensure_company_vault(settings, company.name, company.slug, company.vault_rel_path)

    stmt = (
        select(TelegramPeer, Membership.sort_order)
        .join(Membership, Membership.telegram_peer_id == TelegramPeer.id)
        .where(Membership.company_group_id == company.id, TelegramPeer.is_junk.is_(False))
        .order_by(Membership.sort_order, TelegramPeer.id)
    )
    rows = session.execute(stmt).all()
    if not rows:
        return {"peers": 0, "messages": 0, "files": []}

    total_msgs = 0
    written_files: list[str] = []

    async with telegram_client() as client:
        for peer, _sort in rows:
            cursor = get_or_create_cursor(session, peer.id)
            last_id = int(cursor.last_message_id)
            limit = settings.ingest_max_messages_per_peer

            input_peer = await build_input_peer(
                client,
                peer.peer_type,
                peer.peer_id,
                peer.access_hash,
                peer.username,
            )

            messages: list = []
            if last_id == 0:
                async for m in client.iter_messages(input_peer, limit=limit):
                    messages.append(m)
                messages.sort(key=lambda x: x.id)
            else:
                async for m in client.iter_messages(input_peer, min_id=last_id, reverse=True, limit=limit):
                    messages.append(m)

            if not messages:
                continue

            by_day: dict[str, list] = {}
            max_id = last_id
            for m in messages:
                if m.id <= last_id:
                    continue
                d = m.date
                if d.tzinfo is None:
                    d = d.replace(tzinfo=timezone.utc)
                day = d.astimezone(timezone.utc).strftime("%Y-%m-%d")
                by_day.setdefault(day, []).append(m)
                max_id = max(max_id, m.id)

            label = _safe_label(peer)
            for day, msgs in sorted(by_day.items()):
                day_dir = root / "raw" / day
                day_dir.mkdir(parents=True, exist_ok=True)
                path = day_dir / f"{label}.md"
                chunk = "\n".join(_message_block(m) for m in sorted(msgs, key=lambda x: x.id))
                if chunk.strip():
                    is_new = not path.exists() or path.stat().st_size == 0
                    with path.open("a", encoding="utf-8") as f:
                        if is_new:
                            f.write(f"# Raw messages — {label} — {day}\n\n")
                        f.write(chunk)
                    rel = str(path.relative_to(root)).replace("\\", "/")
                    if rel not in written_files:
                        written_files.append(rel)
                total_msgs += len(msgs)

            cursor.last_message_id = max_id
            cursor.updated_at = datetime.utcnow()

    session.flush()
    return {"peers": len(rows), "messages": total_msgs, "files": written_files}


async def discover_dialogs(session: Session) -> int:
    from telegram_wiki.crud import upsert_peer

    count = 0
    async with telegram_client() as client:
        async for dialog in client.iter_dialogs():
            ent = dialog.entity
            peer_type, peer_id, access_hash, username, title = classify_entity(ent)
            if peer_type == "unknown" or peer_id == 0:
                continue
            upsert_peer(
                session,
                peer_type=peer_type,
                peer_id=peer_id,
                access_hash=access_hash,
                username=username,
                title=title or dialog.name,
            )
            count += 1
    return count
