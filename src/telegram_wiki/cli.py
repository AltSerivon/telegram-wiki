from __future__ import annotations

import asyncio
import os

import typer
from sqlalchemy import select

from telegram_wiki.db import init_db
from telegram_wiki.db.models import CompanyGroup
from telegram_wiki.db.session import session_scope

app = typer.Typer(help="Telegram → Company Group → Obsidian LLM Wiki")


@app.callback()
def _main():
    """Load .env from current working directory."""
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass


@app.command("init-db")
def init_db_cmd():
    """Create SQLite tables."""
    init_db()
    typer.echo("Database initialized.")


@app.command()
def login():
    """Interactive Telegram login (creates session file)."""
    from telegram_wiki.telethon_service import build_client

    async def go():
        client = build_client()
        await client.start()
        typer.echo("Login OK. Session saved.")
        await client.disconnect()

    asyncio.run(go())


@app.command("clear-db")
def clear_db_cmd(
    all_data: bool = typer.Option(
        False,
        "--all",
        help="Also remove company groups, wiki runs, and processed-file bookkeeping.",
    ),
):
    """Remove stored Telegram peers (and related rows) so the next discover starts clean."""
    from telegram_wiki.crud import clear_database_for_discover, clear_entire_database

    init_db()
    with session_scope() as session:
        stats = clear_entire_database(session) if all_data else clear_database_for_discover(session)
    parts = [f"{k}={v}" for k, v in stats.items()]
    typer.echo("Cleared: " + ", ".join(parts))


@app.command()
def discover(
    fresh: bool = typer.Option(
        False,
        "--fresh",
        help="Clear Telegram peer tables (memberships, cursors, peers) before importing.",
    ),
):
    """Import dialogs from Telegram into the local peer list."""
    from telegram_wiki.crud import clear_database_for_discover
    from telegram_wiki.ingest import discover_dialogs

    init_db()
    with session_scope() as session:
        if fresh:
            clear_database_for_discover(session)
        n = asyncio.run(discover_dialogs(session))
    typer.echo(f"Imported {n} dialogs into database.")


@app.command()
def ingest(
    company: str | None = typer.Option(None, "--company", "-c", help="Company slug"),
    all_groups: bool = typer.Option(False, "--all", help="Ingest all company groups"),
):
    """Fetch new Telegram messages into Obsidian raw/ folders."""
    from telegram_wiki.ingest import ingest_company

    init_db()
    if not all_groups and not company:
        typer.echo("Specify --company SLUG or --all", err=True)
        raise typer.Exit(1)

    async def run_one(c: CompanyGroup):
        with session_scope() as session:
            c2 = session.get(CompanyGroup, c.id)
            if c2 is None:
                return
            r = await ingest_company(session, c2)
            typer.echo(f"{c2.slug}: peers={r['peers']} messages={r['messages']} files={r['files']}")

    with session_scope() as session:
        if all_groups:
            companies = list(session.scalars(select(CompanyGroup)).all())
        else:
            c = session.scalars(select(CompanyGroup).where(CompanyGroup.slug == company)).first()
            if not c:
                typer.echo(f"Unknown company slug: {company}", err=True)
                raise typer.Exit(1)
            companies = [c]

    for c in companies:
        asyncio.run(run_one(c))


@app.command("wiki-update")
def wiki_update(
    company: str | None = typer.Option(None, "--company", "-c"),
    all_groups: bool = typer.Option(False, "--all"),
):
    """Run LLM wiki maintenance for new raw files."""
    from telegram_wiki.wiki_llm import run_wiki_update

    init_db()
    if not all_groups and not company:
        typer.echo("Specify --company SLUG or --all", err=True)
        raise typer.Exit(1)

    with session_scope() as session:
        if all_groups:
            companies = list(session.scalars(select(CompanyGroup)).all())
        else:
            c = session.scalars(select(CompanyGroup).where(CompanyGroup.slug == company)).first()
            if not c:
                typer.echo(f"Unknown company slug: {company}", err=True)
                raise typer.Exit(1)
            companies = [c]

        for c in companies:
            wr = run_wiki_update(session, c)
            typer.echo(
                f"{c.slug}: wiki_run id={wr.id} success={wr.success} err={wr.error_message!r}",
            )


@app.command("run-daily")
def run_daily(
    company: str | None = typer.Option(None, "--company", "-c", help="Limit to one company slug; default: all groups"),
):
    """Ingest then wiki-update (intended for launchd/cron)."""
    from telegram_wiki.ingest import ingest_company
    from telegram_wiki.wiki_llm import run_wiki_update

    init_db()

    async def ingest_async(sess, cg: CompanyGroup):
        cg2 = sess.get(CompanyGroup, cg.id)
        if cg2 is None:
            return {}
        return await ingest_company(sess, cg2)

    with session_scope() as session:
        if company:
            companies = list(
                session.scalars(select(CompanyGroup).where(CompanyGroup.slug == company)).all(),
            )
            if not companies:
                typer.echo(f"Unknown company slug: {company}", err=True)
                raise typer.Exit(1)
        else:
            companies = list(session.scalars(select(CompanyGroup)).all())

        for c in companies:
            r = asyncio.run(ingest_async(session, c))
            typer.echo(f"{c.slug} ingest: {r}")
            wr = run_wiki_update(session, c)
            typer.echo(f"{c.slug} wiki: success={wr.success} err={wr.error_message!r}")


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8765, "--port"),
):
    """Run the curation web UI."""
    import uvicorn

    os.environ.setdefault("UVICORN_WORKERS", "1")
    uvicorn.run("telegram_wiki.app:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    app()
