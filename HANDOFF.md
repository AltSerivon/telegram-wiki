# Handoff — 2026-05-12

Where we left off and how to continue.

## Shipped in this snapshot

- **`telegram-wiki clear-db`** — Clears ingest cursors, memberships, and Telegram peers so the next `discover` is a clean import. Use **`--all`** only if you also want company groups, wiki runs, and processed-file bookkeeping removed (does not delete Obsidian files on disk).
- **`telegram-wiki discover --fresh`** — Same as clearing peer-related tables then running discover in one go.
- **Dashboard (`/`)** — Peers and companies are passed to Jinja as plain dicts after the DB session closes, fixing `DetachedInstanceError` when rendering the peer table.
- **Tests** — `test_dashboard_ok_with_peers` covers the dashboard regression.

## Useful commands

```bash
source .venv/bin/activate
pip install -e ".[dev]"   # if CLI/tests deps are missing
telegram-wiki clear-db && telegram-wiki discover
# or
telegram-wiki discover --fresh
```

## Context from today

- Telegram login success line about ToS is Telethon’s normal post-login notice, not an error.
- **`chat:`** vs **`channel:`** in Type/id are different API entity kinds; the same title can appear on two rows if two dialogs share a name (e.g. legacy basic group vs supergroup).

## Next session

- Pull `main` and run tests: `pytest tests/ -q`
- Continue product work from this branch state; no known blockers from the above work.
