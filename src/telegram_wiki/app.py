from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select

from telegram_wiki.config import get_settings
from telegram_wiki.crud import assign_peer_to_company, create_company_group
from telegram_wiki.db import init_db
from telegram_wiki.db.models import CompanyGroup, IngestCursor, Membership, TelegramPeer, WikiRun
from telegram_wiki.db.session import session_scope
from telegram_wiki.vault import slugify

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def create_app() -> FastAPI:
    app = FastAPI(title="Telegram Wiki Curation")

    @app.on_event("startup")
    def _startup():
        try:
            from dotenv import load_dotenv

            load_dotenv()
        except ImportError:
            pass
        init_db()

    @app.get("/", response_class=HTMLResponse)
    def dashboard(request: Request):
        with session_scope() as session:
            peers = list(session.scalars(select(TelegramPeer).order_by(TelegramPeer.title, TelegramPeer.id)).all())
            companies = list(session.scalars(select(CompanyGroup).order_by(CompanyGroup.name)).all())
            memberships = {m.telegram_peer_id: m.company_group_id for m in session.scalars(select(Membership)).all()}
        return templates.TemplateResponse(
            request,
            "dashboard.html",
            {
                "peers": peers,
                "companies": companies,
                "memberships": memberships,
                "vault": str(get_settings().obsidian_vault_path),
            },
        )

    @app.get("/control", response_class=HTMLResponse)
    def control_room(request: Request):
        settings = get_settings()
        session_file_ok = settings.telegram_session_path.is_file()
        llm_configured = bool(settings.openai_api_key and settings.openai_api_key.strip())

        with session_scope() as session:
            n_peers = session.scalar(select(func.count()).select_from(TelegramPeer)) or 0
            n_companies = session.scalar(select(func.count()).select_from(CompanyGroup)) or 0
            n_memberships = session.scalar(select(func.count()).select_from(Membership)) or 0
            n_cursors = session.scalar(select(func.count()).select_from(IngestCursor)) or 0
            n_wiki_runs = session.scalar(select(func.count()).select_from(WikiRun)) or 0

            wiki_rows = list(
                session.execute(
                    select(WikiRun, CompanyGroup.name, CompanyGroup.slug)
                    .join(CompanyGroup, WikiRun.company_group_id == CompanyGroup.id)
                    .order_by(WikiRun.started_at.desc())
                    .limit(25)
                ).all()
            )

            cursor_rows = list(
                session.execute(
                    select(IngestCursor, TelegramPeer)
                    .join(TelegramPeer, IngestCursor.telegram_peer_id == TelegramPeer.id)
                    .order_by(IngestCursor.updated_at.desc())
                    .limit(40)
                ).all()
            )

        wiki_bucket = settings.obsidian_vault_path / settings.vault_bucket

        return templates.TemplateResponse(
            request,
            "control_room.html",
            {
                "session_file_ok": session_file_ok,
                "session_path": str(settings.telegram_session_path),
                "llm_configured": llm_configured,
                "wiki_model": settings.wiki_model,
                "openai_base_url": settings.openai_base_url or "",
                "vault_path": str(settings.obsidian_vault_path),
                "wiki_bucket_rel": settings.vault_bucket,
                "wiki_bucket_abs": str(wiki_bucket),
                "ingest_cap": settings.ingest_max_messages_per_peer,
                "database_url": settings.database_url,
                "n_peers": n_peers,
                "n_companies": n_companies,
                "n_memberships": n_memberships,
                "n_cursors": n_cursors,
                "n_wiki_runs": n_wiki_runs,
                "wiki_rows": wiki_rows,
                "cursor_rows": cursor_rows,
            },
        )

    @app.post("/peers/{peer_id}/junk")
    def toggle_junk(peer_id: int):
        with session_scope() as session:
            p = session.get(TelegramPeer, peer_id)
            if p:
                p.is_junk = not p.is_junk
        return RedirectResponse("/", status_code=303)

    @app.post("/companies")
    def post_company(
        name: str = Form(...),
        slug: str = Form(""),
    ):
        slug = (slug or "").strip() or None
        with session_scope() as session:
            s = slug or slugify(name)
            existing = session.scalars(select(CompanyGroup).where(CompanyGroup.slug == s)).first()
            if existing:
                return RedirectResponse("/?err=slug_exists", status_code=303)
            create_company_group(session, name=name, slug=s)
        return RedirectResponse("/", status_code=303)

    @app.post("/memberships")
    def post_membership(
        peer_id: int = Form(...),
        company_group_id: int = Form(...),
    ):
        with session_scope() as session:
            assign_peer_to_company(session, peer_id, company_group_id, sort_order=0)
        return RedirectResponse("/", status_code=303)

    @app.post("/memberships/clear")
    def clear_membership(peer_id: int = Form(...)):
        with session_scope() as session:
            m = session.scalars(select(Membership).where(Membership.telegram_peer_id == peer_id)).first()
            if m:
                session.delete(m)
        return RedirectResponse("/", status_code=303)

    return app


app = create_app()
