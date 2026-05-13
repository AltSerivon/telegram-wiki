from __future__ import annotations

from datetime import datetime, timedelta, timezone
from functools import partial
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select

from telegram_wiki import pipeline_runner
from telegram_wiki.config import get_settings
from telegram_wiki.crud import assign_peer_to_company, create_company_group
from telegram_wiki.db import init_db
from telegram_wiki.db.models import CompanyGroup, IngestCursor, Membership, TelegramPeer, WikiRun
from telegram_wiki.db.session import session_scope
from telegram_wiki.url_redact import redact_database_url
from telegram_wiki.vault import slugify

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

WIKI_PAGE_SIZE = 25
CURSOR_PAGE_SIZE = 20
WIKI_STALE_AFTER = timedelta(hours=2)


def _wiki_run_status(run: WikiRun) -> tuple[str, str]:
    """Return (css_key, short_label) for a wiki run row."""
    if run.finished_at is not None:
        return ("failed", "failed") if not run.success else ("ok", "ok")
    started = run.started_at
    if started is None:
        return "running", "in progress"
    if started.tzinfo is not None:
        started = started.astimezone(timezone.utc).replace(tzinfo=None)
    age = datetime.utcnow() - started
    if age > WIKI_STALE_AFTER:
        return "stale", "incomplete"
    return "running", "in progress"


def _flash_from_query(request: Request) -> tuple[str | None, str | None]:
    qp = request.query_params
    err = qp.get("error")
    flash_error = None
    if err == "busy":
        flash_error = "Another pipeline job is still running."
    elif err == "unknown_company":
        flash_error = "Unknown company slug for that action."

    notice = qp.get("notice")
    flash_notice = None
    if notice == "started":
        job = qp.get("job", "job")
        flash_notice = f"Started “{job}” in the background. Refresh this page to watch DB counters and tables update."
    return flash_error, flash_notice


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
        flash_error, flash_notice = _flash_from_query(request)
        pipe = pipeline_runner.snapshot()

        wiki_filter = request.query_params.get("wiki_filter", "all")
        if wiki_filter not in ("all", "failed", "unfinished"):
            wiki_filter = "all"
        try:
            wiki_page = int(request.query_params.get("wiki_page", "0") or "0")
        except ValueError:
            wiki_page = 0
        wiki_page = max(0, wiki_page)
        try:
            cursor_page = int(request.query_params.get("cursor_page", "0") or "0")
        except ValueError:
            cursor_page = 0
        cursor_page = max(0, cursor_page)

        with session_scope() as session:
            n_peers = session.scalar(select(func.count()).select_from(TelegramPeer)) or 0
            n_companies = session.scalar(select(func.count()).select_from(CompanyGroup)) or 0
            n_memberships = session.scalar(select(func.count()).select_from(Membership)) or 0
            n_cursors = session.scalar(select(func.count()).select_from(IngestCursor)) or 0
            n_wiki_runs = session.scalar(select(func.count()).select_from(WikiRun)) or 0

            companies = [
                {"slug": c.slug, "name": c.name}
                for c in session.scalars(select(CompanyGroup).order_by(CompanyGroup.name)).all()
            ]

            wiki_count_q = select(func.count(WikiRun.id)).join(
                CompanyGroup,
                WikiRun.company_group_id == CompanyGroup.id,
            )
            if wiki_filter == "failed":
                wiki_count_q = wiki_count_q.where(WikiRun.finished_at.is_not(None), WikiRun.success.is_(False))
            elif wiki_filter == "unfinished":
                wiki_count_q = wiki_count_q.where(WikiRun.finished_at.is_(None))
            wiki_total_filtered = session.scalar(wiki_count_q) or 0

            wiki_stmt = (
                select(WikiRun, CompanyGroup.name, CompanyGroup.slug)
                .join(CompanyGroup, WikiRun.company_group_id == CompanyGroup.id)
                .order_by(WikiRun.started_at.desc())
            )
            if wiki_filter == "failed":
                wiki_stmt = wiki_stmt.where(WikiRun.finished_at.is_not(None), WikiRun.success.is_(False))
            elif wiki_filter == "unfinished":
                wiki_stmt = wiki_stmt.where(WikiRun.finished_at.is_(None))
            wiki_stmt = wiki_stmt.offset(wiki_page * WIKI_PAGE_SIZE).limit(WIKI_PAGE_SIZE)
            wiki_rows = list(session.execute(wiki_stmt).all())

            cursor_count_q = select(func.count(IngestCursor.id)).join(
                TelegramPeer,
                IngestCursor.telegram_peer_id == TelegramPeer.id,
            )
            cursor_total = session.scalar(cursor_count_q) or 0

            cursor_stmt = (
                select(IngestCursor, TelegramPeer)
                .join(TelegramPeer, IngestCursor.telegram_peer_id == TelegramPeer.id)
                .order_by(IngestCursor.updated_at.desc())
                .offset(cursor_page * CURSOR_PAGE_SIZE)
                .limit(CURSOR_PAGE_SIZE)
            )
            cursor_rows = list(session.execute(cursor_stmt).all())

            wiki_display = []
            for run, cname, cslug in wiki_rows:
                sk, sl = _wiki_run_status(run)
                wiki_display.append(
                    {
                        "started_at": run.started_at,
                        "finished_at": run.finished_at,
                        "model": run.model,
                        "error_message": run.error_message,
                        "cname": cname,
                        "cslug": cslug,
                        "status_key": sk,
                        "status_label": sl,
                    }
                )

            cursor_display = [
                {
                    "last_message_id": cur.last_message_id,
                    "updated_at": cur.updated_at,
                    "peer_title": peer.title or "—",
                    "peer_telegram_id": f"{peer.peer_type}:{peer.peer_id}",
                }
                for cur, peer in cursor_rows
            ]

        wiki_total_pages = max(1, (wiki_total_filtered + WIKI_PAGE_SIZE - 1) // WIKI_PAGE_SIZE) if wiki_total_filtered else 1
        cursor_total_pages = max(1, (cursor_total + CURSOR_PAGE_SIZE - 1) // CURSOR_PAGE_SIZE) if cursor_total else 1

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
                "database_url": redact_database_url(settings.database_url),
                "n_peers": n_peers,
                "n_companies": n_companies,
                "n_memberships": n_memberships,
                "n_cursors": n_cursors,
                "n_wiki_runs": n_wiki_runs,
                "wiki_display": wiki_display,
                "cursor_display": cursor_display,
                "companies": companies,
                "wiki_filter": wiki_filter,
                "wiki_page": wiki_page,
                "wiki_total_filtered": wiki_total_filtered,
                "wiki_total_pages": wiki_total_pages,
                "wiki_page_size": WIKI_PAGE_SIZE,
                "cursor_page": cursor_page,
                "cursor_total": cursor_total,
                "cursor_total_pages": cursor_total_pages,
                "cursor_page_size": CURSOR_PAGE_SIZE,
                "flash_error": flash_error,
                "flash_notice": flash_notice,
                "pipeline": pipe,
            },
        )

    def _schedule(kind: str, fn, background_tasks: BackgroundTasks) -> RedirectResponse:
        if not pipeline_runner.try_begin(kind):
            return RedirectResponse("/control?error=busy", status_code=303)
        background_tasks.add_task(pipeline_runner.run_guarded, kind, fn)
        return RedirectResponse(f"/control?notice=started&job={kind}", status_code=303)

    @app.post("/control/actions/discover")
    def post_discover(background_tasks: BackgroundTasks):
        return _schedule("discover", pipeline_runner.run_discover, background_tasks)

    @app.post("/control/actions/ingest")
    def post_ingest(background_tasks: BackgroundTasks, company_slug: str = Form("")):
        slug = (company_slug or "").strip() or None
        return _schedule("ingest", partial(pipeline_runner.run_ingest, slug), background_tasks)

    @app.post("/control/actions/wiki-update")
    def post_wiki(background_tasks: BackgroundTasks, company_slug: str = Form("")):
        slug = (company_slug or "").strip() or None
        return _schedule("wiki-update", partial(pipeline_runner.run_wiki, slug), background_tasks)

    @app.post("/control/actions/run-daily")
    def post_run_daily(background_tasks: BackgroundTasks, company_slug: str = Form("")):
        slug = (company_slug or "").strip() or None
        return _schedule("run-daily", partial(pipeline_runner.run_daily, slug), background_tasks)

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
