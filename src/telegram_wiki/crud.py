from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from telegram_wiki.config import get_settings
from telegram_wiki.db.models import CompanyGroup, IngestCursor, Membership, TelegramPeer
from telegram_wiki.utc import utc_now
from telegram_wiki.vault import ensure_company_vault, slugify


def upsert_peer(
    session: Session,
    *,
    peer_type: str,
    peer_id: int,
    access_hash: int | None,
    username: str | None,
    title: str | None,
) -> TelegramPeer:
    stmt = select(TelegramPeer).where(
        TelegramPeer.peer_type == peer_type,
        TelegramPeer.peer_id == peer_id,
    )
    peer = session.scalars(stmt).first()
    if peer is None:
        peer = TelegramPeer(
            peer_type=peer_type,
            peer_id=peer_id,
            access_hash=access_hash,
            username=username,
            title=title,
        )
        session.add(peer)
        session.flush()
    else:
        peer.access_hash = access_hash if access_hash is not None else peer.access_hash
        peer.username = username if username is not None else peer.username
        peer.title = title if title is not None else peer.title
        peer.updated_at = utc_now()
    return peer


def get_or_create_cursor(session: Session, telegram_peer_id: int) -> IngestCursor:
    stmt = select(IngestCursor).where(IngestCursor.telegram_peer_id == telegram_peer_id)
    cur = session.scalars(stmt).first()
    if cur is None:
        cur = IngestCursor(telegram_peer_id=telegram_peer_id, last_message_id=0)
        session.add(cur)
        session.flush()
    return cur


def create_company_group(session: Session, name: str, slug: str | None = None) -> CompanyGroup:
    settings = get_settings()
    slug = slug or slugify(name)
    vault_rel_path = f"{settings.vault_bucket.rstrip('/')}/{slug}"
    ensure_company_vault(settings, name, slug, vault_rel_path)
    cg = CompanyGroup(name=name, slug=slug, vault_rel_path=vault_rel_path)
    session.add(cg)
    session.flush()
    return cg


def assign_peer_to_company(session: Session, peer_id: int, company_group_id: int, sort_order: int = 0) -> Membership:
    stmt = select(Membership).where(Membership.telegram_peer_id == peer_id)
    m = session.scalars(stmt).first()
    if m:
        m.company_group_id = company_group_id
        m.sort_order = sort_order
        session.flush()
        return m
    m = Membership(telegram_peer_id=peer_id, company_group_id=company_group_id, sort_order=sort_order)
    session.add(m)
    session.flush()
    return m
