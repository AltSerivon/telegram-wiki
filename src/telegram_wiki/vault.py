from __future__ import annotations

import hashlib
import re
from pathlib import Path

from telegram_wiki.config import Settings, get_settings


def slugify(name: str) -> str:
    s = name.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-") or "company"


def is_wiki_write_allowed(rel: str) -> bool:
    rel = rel.replace("\\", "/").lstrip("/")
    if rel in ("index.md", "log.md"):
        return True
    if rel.startswith("wiki/") and ".." not in rel:
        return True
    return False


def is_wiki_read_allowed(rel: str) -> bool:
    rel = rel.replace("\\", "/").lstrip("/")
    if rel in ("WIKI_SCHEMA.md", "index.md", "log.md"):
        return True
    if rel.startswith("wiki/") and ".." not in rel:
        return True
    if rel.startswith("raw/") and ".." not in rel:
        return True
    return False


def company_abs_path(settings: Settings, vault_rel_path: str) -> Path:
    return (settings.obsidian_vault_path / vault_rel_path).resolve()


def default_vault_rel_path(settings: Settings, slug: str) -> str:
    return f"{settings.vault_bucket.rstrip('/')}/{slug}"


DEFAULT_WIKI_SCHEMA = """# Wiki schema (LLM constitution)

You maintain a Karpathy-style **LLM Wiki** for this company group inside Obsidian.

## Layers

- **`raw/`** — immutable Telegram exports. **Never edit** files under `raw/`.
- **`wiki/`** — your workspace: interlinked markdown using **Obsidian wikilinks** `[[Page Title]]` where pages match filenames (e.g. `[[Contoso Overview]]` → `wiki/Contoso Overview.md`).
- **`index.md`** — catalog of wiki pages with one-line summaries; keep updated on each ingest.
- **`log.md`** — append-only timeline. Each ingest entry: `## [YYYY-MM-DD] ingest | <short summary>`.

## Rules

1. Cite raw provenance inline where useful: `(raw/…#msg-<id>)` or message id in footnotes.
2. Prefer stable `wiki/` filenames; use YAML frontmatter optionally: `source`, `date`, `tags`.
3. Integrate new facts; flag contradictions with prior wiki text in `log.md` or a `wiki/Contradictions.md` page.
4. Do not delete historical raw references from `log.md`; only append.

## Page types (suggested)

- `wiki/<Company> Overview.md` — rolling synthesis.
- `wiki/Entities/*.md` — organizations, people, products mentioned often.
- `wiki/Timeline.md` — dated bullets for major events from sources.

When ingesting, update `index.md` first-pass listing all `wiki/*.md` with one-line summaries.
"""


def ensure_company_vault(settings: Settings, name: str, slug: str, vault_rel_path: str) -> Path:
    root = company_abs_path(settings, vault_rel_path)
    (root / "raw").mkdir(parents=True, exist_ok=True)
    (root / "wiki").mkdir(parents=True, exist_ok=True)
    schema = root / "WIKI_SCHEMA.md"
    if not schema.exists():
        schema.write_text(DEFAULT_WIKI_SCHEMA, encoding="utf-8")
    idx = root / "index.md"
    if not idx.exists():
        idx.write_text(
            f"# {name}\n\nCatalog of wiki pages for **{name}**. Updated by the ingest pipeline.\n\n## Pages\n\n",
            encoding="utf-8",
        )
    log = root / "log.md"
    if not log.exists():
        log.write_text("# Wiki log\n\nAppend-only ingest and maintenance entries.\n\n", encoding="utf-8")
    return root


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def list_raw_files(company_root: Path) -> list[Path]:
    raw = company_root / "raw"
    if not raw.exists():
        return []
    out: list[Path] = []
    for p in sorted(raw.rglob("*.md")):
        if p.is_file():
            out.append(p)
    for p in sorted(raw.rglob("*.jsonl")):
        if p.is_file():
            out.append(p)
    return out


def rel_under_company(company_root: Path, path: Path) -> str:
    return str(path.relative_to(company_root)).replace("\\", "/")
