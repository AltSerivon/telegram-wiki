# telegram-wiki

Ingest Telegram channels you follow into **per–company-group** folders inside an **Obsidian vault**, then run an **OpenAI-compatible** LLM to maintain a **Karpathy-style** wiki (`raw/`, `wiki/`, `WIKI_SCHEMA.md`, `index.md`, `log.md`).

## Quick start

1. Copy `.env.example` to `.env` and set at least:

   - `TELEGRAM_API_ID`, `TELEGRAM_API_HASH` (from [my.telegram.org](https://my.telegram.org))
   - `OBSIDIAN_VAULT_PATH` — folder you open as a vault in Obsidian
   - `OPENAI_API_KEY` — for automated wiki updates (optional for ingest-only tests)

2. Create a virtualenv and install:

```bash
cd /path/to/telegram-info
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

3. Initialize the database and log in to Telegram (interactive):

```bash
telegram-wiki init-db
telegram-wiki login
telegram-wiki discover
```

4. Run the **web UI** (curation + control room):

```bash
telegram-wiki serve
# Curation: http://127.0.0.1:8765/
# Control room (status, cursors, wiki runs): http://127.0.0.1:8765/control
```

5. Ingest and update the wiki:

```bash
telegram-wiki ingest --all
telegram-wiki wiki-update --all
# or combined:
telegram-wiki run-daily
```

Company data is written under:

`$OBSIDIAN_VAULT_PATH/_telegram_wiki/<slug>/`

## Daily schedule (macOS)

Use `launchd` so `run-daily` runs once per day (example loads `.env` from your project directory):

- See [scripts/com.telegramwiki.daily.plist](scripts/com.telegramwiki.daily.plist)

Install (adjust paths):

```bash
cp scripts/com.telegramwiki.daily.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.telegramwiki.daily.plist
```

**Tip:** If the vault is on iCloud Drive, run the job when Obsidian is usually closed to reduce sync conflicts.

## Troubleshooting

**`ModuleNotFoundError: No module named 'telegram_wiki'` after `pip install -e .` (macOS, project on iCloud Drive):**  
iCloud can mark the editable-install pointer file `__editable__.*.pth` in `.venv/.../site-packages/` with the **hidden** file flag. Python 3.13 skips hidden `.pth` files, so `src/` is never added to `sys.path`. Clear the flag (adjust the path if your venv differs):

```bash
chflags nohidden .venv/lib/python3.*/site-packages/__editable__.telegram_wiki-*.pth
```

Then run `python -c "import telegram_wiki"` again. Putting the virtualenv **outside** iCloud (e.g. under your home directory) avoids this class of issue.

## Backup

- Keep `data/` (SQLite + Telegram session) backed up privately — it is effectively a credential.
- The Obsidian vault can be git-backed like any other wiki.

## Legal

Use only for chats your Telegram account is allowed to access. Respect Telegram’s Terms of Service and channel rules.
