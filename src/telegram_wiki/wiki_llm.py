from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from openai import OpenAI
from sqlalchemy import select
from sqlalchemy.orm import Session

from telegram_wiki.config import get_settings
from telegram_wiki.db.models import CompanyGroup, WikiProcessedFile, WikiRun
from telegram_wiki.vault import (
    company_abs_path,
    file_sha256,
    is_wiki_read_allowed,
    is_wiki_write_allowed,
    list_raw_files,
    rel_under_company,
)


def _resolve_safe(company_root: Path, rel: str) -> Path | None:
    rel = rel.replace("\\", "/").lstrip("/")
    if ".." in rel:
        return None
    full = (company_root / rel).resolve()
    try:
        full.relative_to(company_root.resolve())
    except ValueError:
        return None
    return full


def _tool_defs() -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": "list_dir",
                "description": "List files in a directory relative to the company folder (e.g. wiki, raw).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "relative_path": {
                            "type": "string",
                            "description": "Relative path like 'wiki' or 'raw/2026-01-01'",
                        }
                    },
                    "required": ["relative_path"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Read a text file under the company folder.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "relative_path": {"type": "string"},
                        "max_chars": {"type": "integer", "default": 120000},
                    },
                    "required": ["relative_path"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "write_file",
                "description": "Write or overwrite a file. Only wiki/*.md, index.md, or log.md.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "relative_path": {"type": "string"},
                        "content": {"type": "string"},
                    },
                    "required": ["relative_path", "content"],
                },
            },
        },
    ]


def _execute_tool(company_root: Path, name: str, args: dict) -> str:
    if name == "list_dir":
        rel = args.get("relative_path", ".")
        full = _resolve_safe(company_root, rel)
        if full is None or not full.exists():
            return json.dumps({"error": "path not found"})
        if not full.is_dir():
            return json.dumps({"error": "not a directory"})
        names = sorted(p.name for p in full.iterdir())
        return json.dumps({"entries": names})

    if name == "read_file":
        rel = args.get("relative_path", "")
        max_chars = int(args.get("max_chars") or 120000)
        if not is_wiki_read_allowed(rel):
            return json.dumps({"error": "read not allowed for this path"})
        full = _resolve_safe(company_root, rel)
        if full is None or not full.is_file():
            return json.dumps({"error": "file not found"})
        text = full.read_text(encoding="utf-8", errors="replace")
        if len(text) > max_chars:
            text = text[:max_chars] + "\n\n...[truncated]..."
        return json.dumps({"content": text})

    if name == "write_file":
        rel = args.get("relative_path", "")
        content = args.get("content", "")
        if not is_wiki_write_allowed(rel):
            return json.dumps({"error": "write not allowed for this path"})
        full = _resolve_safe(company_root, rel)
        if full is None:
            return json.dumps({"error": "invalid path"})
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content, encoding="utf-8")
        return json.dumps({"ok": True, "bytes": len(content.encode("utf-8"))})

    return json.dumps({"error": f"unknown tool {name}"})


def _unprocessed_raw_files(session: Session, company: CompanyGroup, company_root: Path) -> list[Path]:
    all_raw = [p for p in list_raw_files(company_root) if str(p.relative_to(company_root)).startswith("raw" + "/")]
    out: list[Path] = []
    for path in all_raw:
        rel = rel_under_company(company_root, path)
        h = file_sha256(path)
        stmt = select(WikiProcessedFile).where(
            WikiProcessedFile.company_group_id == company.id,
            WikiProcessedFile.rel_path == rel,
            WikiProcessedFile.content_hash == h,
        )
        if session.scalars(stmt).first() is None:
            out.append(path)
    return sorted(out)


def _mark_processed(session: Session, company_id: int, paths: list[Path], company_root: Path) -> None:
    for path in paths:
        rel = rel_under_company(company_root, path)
        h = file_sha256(path)
        stmt = select(WikiProcessedFile).where(
            WikiProcessedFile.company_group_id == company_id,
            WikiProcessedFile.rel_path == rel,
        )
        row = session.scalars(stmt).first()
        if row:
            row.content_hash = h
            row.processed_at = datetime.utcnow()
        else:
            session.add(
                WikiProcessedFile(
                    company_group_id=company_id,
                    rel_path=rel,
                    content_hash=h,
                )
            )


def run_wiki_update(session: Session, company: CompanyGroup) -> WikiRun:
    settings = get_settings()
    if not settings.openai_api_key:
        wr = WikiRun(
            company_group_id=company.id,
            success=False,
            error_message="OPENAI_API_KEY not set",
            model=settings.wiki_model,
            finished_at=datetime.utcnow(),
        )
        session.add(wr)
        session.flush()
        return wr

    company_root = company_abs_path(settings, company.vault_rel_path)
    company_root.mkdir(parents=True, exist_ok=True)

    run = WikiRun(company_group_id=company.id, success=False, model=settings.wiki_model)
    session.add(run)
    session.flush()

    client = OpenAI(api_key=settings.openai_api_key, base_url=settings.openai_base_url or None)

    max_batches = 8
    char_budget = 100_000
    max_tool_rounds = 40
    max_body_chars = 80_000

    try:
        for _batch in range(max_batches):
            unprocessed = _unprocessed_raw_files(session, company, company_root)
            if not unprocessed:
                run.success = True
                run.finished_at = datetime.utcnow()
                session.flush()
                return run

            batch: list[Path] = []
            chars = 0
            for p in unprocessed:
                t = p.read_text(encoding="utf-8", errors="replace")
                if chars + len(t) > char_budget and batch:
                    break
                batch.append(p)
                chars += len(t)
            if not batch:
                batch = [unprocessed[0]]

            raw_bundle_parts: list[str] = []
            for p in batch:
                rel = rel_under_company(company_root, p)
                body = p.read_text(encoding="utf-8", errors="replace")
                if len(body) > max_body_chars:
                    body = body[:max_body_chars] + "\n\n...[truncated for LLM context]...\n"
                raw_bundle_parts.append(f"### FILE: {rel}\n\n{body}\n")

            schema_text = (company_root / "WIKI_SCHEMA.md").read_text(encoding="utf-8", errors="replace")
            index_text = (company_root / "index.md").read_text(encoding="utf-8", errors="replace")[-40000:]
            log_tail = (company_root / "log.md").read_text(encoding="utf-8", errors="replace")[-20000:]

            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            user_intro = (
                f"Company group: **{company.name}** (slug `{company.slug}`).\n"
                f"Today (UTC): {today}.\n"
                "New raw sources (immutable) are appended below. Integrate them into the Obsidian wiki per WIKI_SCHEMA.md.\n"
                "Use tools to read existing wiki pages and write updates. Append a new `## [{today}] ingest | ...` section to log.md summarizing what you integrated.\n"
                "Update index.md to reflect current wiki pages.\n\n"
                "--- RAW SOURCES ---\n\n"
                + "\n".join(raw_bundle_parts)
            )

            messages: list[dict] = [
                {
                    "role": "system",
                    "content": (
                        "You are a disciplined wiki maintainer. Follow the user's WIKI_SCHEMA exactly.\n\n"
                        f"### WIKI_SCHEMA.md\n\n{schema_text[:20000]}\n\n"
                        "### Current index.md (tail)\n\n"
                        f"{index_text}\n\n"
                        "### log.md (tail)\n\n"
                        f"{log_tail}\n"
                    ),
                },
                {"role": "user", "content": user_intro},
            ]

            tools = _tool_defs()

            for _round in range(max_tool_rounds):
                resp = client.chat.completions.create(
                    model=settings.wiki_model,
                    messages=messages,
                    tools=tools,
                    tool_choice="auto",
                )
                choice = resp.choices[0].message
                tool_calls = choice.tool_calls
                msg_dict = {
                    "role": "assistant",
                    "content": choice.content or "",
                }
                if tool_calls:
                    msg_dict["tool_calls"] = [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                        }
                        for tc in tool_calls
                    ]
                messages.append(msg_dict)

                if not tool_calls:
                    break

                for tc in tool_calls:
                    name = tc.function.name
                    try:
                        args = json.loads(tc.function.arguments or "{}")
                    except json.JSONDecodeError:
                        args = {}
                    result = _execute_tool(company_root, name, args)
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": result,
                        }
                    )
            else:
                run.error_message = "Max tool rounds exceeded"
                run.finished_at = datetime.utcnow()
                session.flush()
                return run

            _mark_processed(session, company.id, batch, company_root)

        run.success = True
        run.finished_at = datetime.utcnow()
    except Exception as exc:  # noqa: BLE001
        run.success = False
        run.error_message = str(exc)[:4000]
        run.finished_at = datetime.utcnow()

    session.flush()
    return run
