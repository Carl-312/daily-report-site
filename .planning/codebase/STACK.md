# Technology Stack

## Runtime and application shape

- The project is a Python 3.12 application, as stated in `README.md:16`.
- It is a framework-free command-line pipeline rather than a persistent web service; `argparse` dispatches `run`, `fetch`, `summarize`, `build`, and `test` in `main.py:219-273`.
- The full daily path is synchronous and sequential: fetch, deduplicate, enrich, persist JSON, summarize, persist Markdown, then build HTML (`main.py:89-150`).
- Python type hints use modern union and generic syntax, with postponed evaluation enabled through `from __future__ import annotations` across the core modules.
- Domain records are represented by the standard-library `dataclasses.dataclass` as `Article` in `sources/base.py:13-34`.
- Source adapters share an `ABC`/`abstractmethod` contract through `BaseSource` in `sources/base.py:37-57`.
- Source discovery uses an explicit in-process registry mapping names to adapter classes in `sources/__init__.py:15-29`.

## Configuration

- Pydantic `BaseModel` and `Field` define validated application and enrichment settings in `config.py:10` and `config.py:22-133`.
- Pydantic forward-reference rebuilding is invoked with `Settings.model_rebuild()` in `config.py:136`.
- `python-dotenv` loads UTF-8 `.env` values with `override=True` at import time in `config.py:11-15`.
- PyYAML reads non-secret project configuration with `yaml.safe_load` in `config.py:164-188`.
- Environment variables override YAML by being merged last in `config.py:190-191`.
- Configuration is cached as a process-global singleton in `config.py:194-203`.
- Filesystem locations are configurable strings converted to `pathlib.Path` at use sites (`config.py:63-67`, `build.py:141-152`).

## HTTP, parsing, and news processing

- `requests.Session` is the shared HTTP client for source adapters (`sources/base.py:50-61`) and a separate session drives Tavily enrichment (`utils/news_enrichment.py:1394-1395`).
- Source HTTP calls use a browser-like user agent, explicit timeouts, and `raise_for_status` in `sources/base.py:42-61` and individual adapters.
- BeautifulSoup is imported lazily and uses the built-in `html.parser` backend in `sources/base.py:63-67`.
- News extraction is hand-authored CSS-selector and URL-pattern parsing, visible in `sources/aibase.py:60-212`, `sources/techcrunch.py:36-103`, and `sources/theverge.py:34-91`.
- Date handling mixes `datetime.timezone`, optional `pytz`, and standard-library `zoneinfo.ZoneInfo` (`sources/aibase.py:14-22`, `utils/news_enrichment.py:17-24`).
- Exact first-pass deduplication uses normalized title plus URL domain hashed with MD5 in `utils/dedupe.py:17-41`.
- Tavily enrichment adds fuzzy title similarity with `difflib.SequenceMatcher` and token-based story clustering (`utils/news_enrichment.py:128-131`, `utils/news_enrichment.py:248-306`).
- The enrichment module relies on regular expressions for AI relevance classification and title/token normalization (`utils/news_enrichment.py:35-60`).

## LLM summarization

- The official OpenAI Python client is used as a generic OpenAI-compatible API client in `summarizer.py:11` and `summarizer.py:19-21`.
- ModelScope is the primary compatible endpoint and SiliconFlow is the fallback endpoint (`config.py:25-46`).
- Provider/model fallback is implemented as ordered application logic rather than an SDK feature (`summarizer.py:97-140`, `summarizer.py:168-201`).
- Both streaming and non-streaming chat completions are supported through `client.chat.completions.create` (`summarizer.py:204-224`).
- LLM input is JSON-serialized compressed article metadata, capped by configurable title and description lengths (`summarizer.py:33-47`, `summarizer.py:164-179`).
- Output quality is checked locally with numbered-item, footer, Chinese-ratio, CJK-count, and raw-link rules (`summarizer.py:50-95`).
- A deterministic Markdown link-list generator provides explicit offline operation (`summarizer.py:227-243`).

## Storage and presentation

- JSON and Markdown are stored as UTF-8 date-named files using the standard library (`utils/storage.py:34-65`).
- JSON is pretty-printed with non-ASCII preservation for inspectable daily artifacts (`utils/storage.py:34-40`).
- Daily Markdown receives minimal YAML-like frontmatter before content is written (`utils/storage.py:52-65`).
- Python-Markdown converts reports to HTML with tables, fenced code, code highlighting, and TOC extensions (`build.py:186-195`).
- Static pages are rendered with Python string templates rather than a template engine (`build.py:17-138`, `build.py:206-213`).
- `shutil` resets the isolated output directory and copies flat assets during each build (`build.py:234-259`).
- The produced artifact is a static site intended for GitHub Pages (`README.md:57-61`, `build.py:241-318`).

## Quality and deployment tooling visible from the allowed files

- The README identifies Ruff and pytest as the CI lint/test toolchain (`README.md:12`, `README.md:53-55`).
- GitHub Actions is the scheduler and delivery orchestrator for the daily job (`README.md:7`, `README.md:57-62`).
- The main branch retains seven days while older data is archived to GitHub Releases (`README.md:11`, `README.md:60-61`).
- No asynchronous runtime, task queue, database, ORM, browser automation, feed parser, or structured logging library appears in the inspected daily-path code.
