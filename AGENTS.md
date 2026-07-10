<!-- GSD:project-start source:PROJECT.md -->
## Project

**Daily News Reliability**

This is a Python 3.12, file-backed daily AI and technology news pipeline. It collects news from configured sources, deduplicates and optionally enriches candidates, creates a Chinese daily summary, and builds a GitHub Pages static site. This milestone makes that pipeline safe to rerun and safe to publish without losing the last known-good edition.

**Core Value:** Every scheduled or manual daily run must either atomically publish one complete, quality-gated edition or leave the previously published edition untouched with an actionable record of why it did not publish.

### Constraints

- **Publication safety**: Any failed or blocked run must retain the last known-good JSON, Markdown, and site output.
- **Compatibility**: Preserve existing CLI behavior where safe; add explicit exit codes and compatible staged recovery paths.
- **Delivery**: Make one independently verifiable commit at a time, push only a gray branch, open a Draft PR, and never directly modify `main`.
- **CI**: GitHub Actions must pass after P0, after gray validation, and after final regression; failures must be repaired and re-run before progressing.
- **Verification**: Gray validation covers normal, degraded, all-source failure, summary failure, build failure, and duplicate execution.
- **Documentation**: Update operation, rollback, architecture, and acceptance evidence as the implementation changes.
<!-- GSD:project-end -->

<!-- GSD:stack-start source:codebase/STACK.md -->
## Technology Stack

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
<!-- GSD:stack-end -->

<!-- GSD:conventions-start source:CONVENTIONS.md -->
## Conventions

## Scope
- This map is intentionally limited to `README.md` and the requested core functional files.
- No tests, workflow files, YAML configuration files, prompt files, assets, or other documentation were read.
- The README describes a Python 3.12 CLI pipeline with Ruff and pytest in CI (`README.md:14-20`, `README.md:51-62`).
## Module Organization
- `main.py` is the application service and CLI boundary: fetch, deduplicate, enrich, persist, summarize, and build (`main.py:89-150`).
- `config.py` owns typed runtime settings, environment/YAML merging, and a process-wide singleton (`config.py:22-82`, `config.py:139-203`).
- `sources/base.py` defines the canonical `Article` dataclass and the source adapter contract (`sources/base.py:13-34`, `sources/base.py:37-61`).
- `sources/__init__.py` acts as the source registry and fan-in coordinator (`sources/__init__.py:15-29`, `sources/__init__.py:32-70`).
- `summarizer.py` owns prompt loading, input compression, provider fallback, response validation, and offline rendering (`summarizer.py:24-47`, `summarizer.py:65-95`, `summarizer.py:143-243`).
- `utils/news_enrichment.py` isolates Tavily-specific verification/refill logic from the CLI (`utils/news_enrichment.py:1-6`, `utils/news_enrichment.py:1349-1667`).
- `build.py` is a static-site adapter over Markdown and filesystem output (`build.py:141-169`, `build.py:186-221`, `build.py:241-318`).
## Types and Data Shapes
- Public function signatures commonly use built-in generics and union syntax enabled by `from __future__ import annotations` (`sources/base.py:6-10`, `utils/news_enrichment.py:8-21`).
- Boundary data is permissive: most stages accept either `Article` or plain dictionaries (`utils/dedupe.py:31-44`, `utils/news_enrichment.py:117-120`).
- `Article.to_dict()` is the canonical conversion at the source boundary (`sources/base.py:25-34`), and `main.py` repeats that conversion before enrichment/storage (`main.py:111-123`).
- Enrichment returns a dictionary containing `articles` and a large diagnostic `report` rather than a typed result object (`utils/news_enrichment.py:1349-1378`, `utils/news_enrichment.py:1652-1667`).
- Diagnostics favor stable string enums such as `skip_reason`, `stop_reason`, `request_outcome`, and `validation_outcome` (`utils/news_enrichment.py:658-762`, `utils/news_enrichment.py:1039-1069`).
## Configuration
- Pydantic models provide defaults for providers, limits, output paths, and enrichment policy (`config.py:22-79`, `config.py:85-133`).
- Environment variables carry secrets and provider endpoints; YAML carries source, limit, path, and enrichment policy (`config.py:139-188`).
- Environment values override YAML via a shallow dictionary merge (`config.py:190-191`).
- Configuration is globally cached by `get_config()`, so modules call it directly rather than receiving settings explicitly (`config.py:194-203`, `summarizer.py:24-35`, `build.py:141-152`).
- Some values are validated only by conversion at load time, notably `MODELSCOPE_MAX_OUTPUT` through `int(...)` (`config.py:157`).
## Source Adapter Pattern
- Every source subclasses `BaseSource`, owns a lowercase `name`, and implements `fetch(max_articles)` (`sources/base.py:37-57`, `sources/techcrunch.py:17-34`).
- Shared HTTP behavior is a `requests.Session` with a browser-like user agent, explicit timeout, and proxy bypass (`sources/base.py:42-61`).
- HTML adapters separate transport, selector parsing, URL normalization, and recency filtering (`sources/techcrunch.py:23-34`, `sources/techcrunch.py:36-124`; `sources/theverge.py:23-110`).
- Source output is capped after filtering, not before parsing (`sources/techcrunch.py:29-34`, `sources/theverge.py:29-32`).
- Syft is configuration-sensitive and returns no articles when credentials are absent (`sources/syft.py:20-28`).
- The registry handles Syft construction specially rather than exposing a uniform source factory interface (`sources/__init__.py:52-64`).
## Error Handling and Degradation
- The source fan-in is best-effort: one adapter exception is printed and does not stop other sources (`sources/__init__.py:52-70`).
- AIBase and Syft suppress broad exceptions and convert them to `None` or an empty list (`sources/aibase.py:91-125`, `sources/syft.py:30-64`).
- TechCrunch and The Verge also suppress selector/date parsing exceptions locally (`sources/techcrunch.py:50-56`, `sources/techcrunch.py:113-124`; `sources/theverge.py:44-50`, `sources/theverge.py:101-110`).
- LLM generation tries providers in priority order, records provider/model error text, and raises only after all candidates fail (`summarizer.py:97-140`, `summarizer.py:168-201`).
- The production `run` path is fail-closed for invalid online summaries, despite the helper name `summarize_or_offline`: online failure raises and refuses an offline publication (`main.py:67-86`).
- Enrichment is explicitly fail-open: disabled, missing-key, request-error, and module-error paths preserve upstream deduplicated articles with diagnostics (`utils/news_enrichment.py:1368-1392`, `utils/news_enrichment.py:1647-1667`).
- Verification transport errors preserve the original article, while successful verification failures reject it (`utils/news_enrichment.py:1035-1050`, `utils/news_enrichment.py:1091-1107`).
## Determinism and Time
- Beijing time is the publication convention in storage and source filtering (`utils/storage.py:12-24`, `sources/techcrunch.py:13-14`).
- Time acquisition is usually direct `datetime.now(...)`, but enrichment accepts `reference_dt` as an override (`sources/aibase.py:32-35`, `sources/syft.py:30-37`, `utils/news_enrichment.py:1349-1365`).
- Title deduplication sorts by priority before retaining the first item (`utils/dedupe.py:44-69`).
- Enrichment local matching is decomposed into deterministic functions for normalization, time parsing, relevance, similarity, and clustering (`utils/news_enrichment.py:123-219`, `utils/news_enrichment.py:270-456`).
## I/O and Build Behavior
- Storage functions create directories eagerly and write date-keyed UTF-8 JSON/Markdown files (`utils/storage.py:27-40`, `utils/storage.py:52-67`).
- File writes are direct, not atomic; an interrupted write can leave a partial daily artifact (`utils/storage.py:34-40`, `utils/storage.py:52-65`).
- The build output directory is deleted recursively before every build (`build.py:234-253`).
- Builder entry points accept path overrides, which keeps most filesystem behavior separable from global configuration (`build.py:141-152`, `build.py:241-249`).
- Frontmatter parsing is a minimal line-based parser rather than the YAML parser already used by configuration (`build.py:155-169`).
- HTML is assembled with string formatting, including metadata and article-derived values without explicit HTML escaping (`build.py:186-231`, `build.py:291-313`).
## Style and Maintainability Signals
- Module docstrings and short function docstrings are common; comments orient pipeline stages and parsing heuristics (`main.py:89-143`, `sources/aibase.py:32-58`).
- Constants are uppercase at module scope for models, URLs, thresholds, and regex policy (`config.py:17-19`, `utils/news_enrichment.py:23-60`).
- Naming generally uses `snake_case`, source adapters use `PascalCase`, and private helpers use a leading underscore (`summarizer.py:50-63`, `sources/techcrunch.py:17-23`).
- The largest maintainability exception is `utils/news_enrichment.py`: it combines policy constants, matching algorithms, HTTP transport, staged orchestration, and a very large report schema in one 1,667-line module (`utils/news_enrichment.py:23-114`, `utils/news_enrichment.py:485-516`, `utils/news_enrichment.py:658-762`, `utils/news_enrichment.py:1349-1667`).
- Observability is structured inside enrichment reports but console-only elsewhere, so pipeline events do not share a common logging contract (`sources/__init__.py:63-68`, `summarizer.py:182-200`, `utils/news_enrichment.py:658-762`).
<!-- GSD:conventions-end -->

<!-- GSD:architecture-start source:ARCHITECTURE.md -->
## Architecture

## Scope
- This map is based only on `README.md` and the selected runtime files in the repository root, `sources/`, and `utils/`.
- The product is a Python 3.12 batch application that turns daily AI/technology-news candidates into JSON, Markdown, and a static HTML site (`README.md:3`, `README.md:16`, `README.md:60`).
- The runtime is intentionally synchronous and file-backed; there is no application server, queue, or database in the inspected core.
## Entry Points
- `main.py:219` is the unified CLI entry point and registers `run`, `fetch`, `summarize`, `build`, and `test` commands.
- `main.py:89` owns the full `fetch -> dedupe -> enrich -> persist JSON -> summarize -> persist Markdown -> build` orchestration.
- `main.py:153`, `main.py:184`, and `main.py:206` expose pipeline stages as separately repeatable commands, using the dated JSON and Markdown files as checkpoints.
- `summarizer.py:277` and `build.py:321` also provide narrow module-level entry points for provider testing and static-site building.
## Primary Data Flow
## Domain Model And Boundaries
- `sources/base.py:13` defines the canonical ingestion record, `Article`, with title, URL, text, publication time, priority, and source identity.
- `sources/base.py:37` defines the adapter contract; every concrete source implements `fetch(max_articles)` and reuses a standard `requests.Session` (`sources/base.py:50`).
- `sources/__init__.py:15` is the source composition boundary: the registry maps configuration keys to adapter classes.
- `utils/dedupe.py` is a pure transformation boundary, although its exact key only collapses same-domain duplicates and leaves cross-source coverage of the same story untouched.
- `utils/news_enrichment.py` is both a policy engine and an external Tavily gateway. It converts `Article` values to dictionaries at its boundary (`utils/news_enrichment.py:117`).
- `summarizer.py` is the LLM boundary; it builds clients from provider descriptors and sends a compressed JSON payload plus a file-loaded system prompt (`summarizer.py:97`, `summarizer.py:164`).
- `utils/storage.py` is the persistence boundary, using dated filenames as the contract between fetch, summarize, and build stages.
- `build.py` is the presentation boundary. It parses frontmatter, converts Markdown, embeds it in static templates, and writes index/archive/article pages (`build.py:155`, `build.py:186`, `build.py:241`).
## Enrichment State Machine
- Local prefiltering removes missing-title, missing-link, and aggregate-like candidates, then assigns AI relevance buckets (`utils/news_enrichment.py:595`).
- Candidate story clusters are built before network verification so one representative can stand in for near-duplicate stories (`utils/news_enrichment.py:306`, `utils/news_enrichment.py:426`).
- Tavily verification has an explicit call budget that reserves capacity for later refill stages (`utils/news_enrichment.py:947`, `utils/news_enrichment.py:961`).
- A verified item must match by exact URL or same-domain title similarity and have a provable publication time inside the strict window (`utils/news_enrichment.py:1021`, `utils/news_enrichment.py:1039`).
- Refill runs in priority-media, secondary-media, and optional official-source stages, sharing one total budget (`utils/news_enrichment.py:1480`, `utils/news_enrichment.py:1520`, `utils/news_enrichment.py:1567`).
- Refill acceptance requires strict recency, AI-title relevance, and no exact, near-duplicate, or story-cluster collision (`utils/news_enrichment.py:1200`, `utils/news_enrichment.py:1247`).
- Disabled/missing-key paths return the deduped input; unexpected enrichment errors also fail open to that input (`utils/news_enrichment.py:1368`, `utils/news_enrichment.py:1380`, `utils/news_enrichment.py:1653`).
- Per-request outcomes, counts, stop reasons, previews, and optional lenient diagnostics are accumulated in the persisted enrichment report (`utils/news_enrichment.py:658`, `utils/news_enrichment.py:1611`).
## Reliability Characteristics
- Source isolation is coarse but effective: `fetch_all()` catches one adapter failure and continues with other sources (`sources/__init__.py:56`).
- Source error visibility is weak: AIBase and Syft swallow exceptions and return empty lists (`sources/aibase.py:91`, `sources/syft.py:30`), so “no news” and “fetch failure” can be indistinguishable.
- The pipeline creates a JSON checkpoint before calling the LLM (`main.py:115`), allowing summarization to be retried with `main.py summarize`.
- LLM fallback is provider/model ordered and quality validation happens for every candidate response (`summarizer.py:97`, `summarizer.py:168`).
- An explicit offline run produces deterministic linked headlines (`summarizer.py:227`), but an online summarization failure is fail-closed and aborts publication (`main.py:80`).
- JSON and Markdown writes are direct, non-atomic file replacements (`utils/storage.py:34`, `utils/storage.py:52`), leaving partial-file risk if the process is interrupted.
- The build output reset is destructive before all input conversion succeeds (`build.py:234`, `build.py:253`); a late build failure can leave a partially generated `dist/`.
- Source adapters use fixed timeouts but no retries, backoff, response validation schema, or shared observability contract (`sources/base.py:59`, `sources/syft.py:33`).
- Time handling is Beijing-centric in storage and sources, while configured `Settings.timezone` is not used by the inspected date helpers (`config.py:50`, `utils/storage.py:12`).
## Architectural Pressure Points
- `main.py` duplicates fetch/dedupe/enrich/save logic between `cmd_run()` and `cmd_fetch()` (`main.py:97`, `main.py:158`), increasing drift risk in the daily critical path.
- Runtime records alternate between `Article` and unconstrained dictionaries (`main.py:111`, `utils/news_enrichment.py:1350`), weakening schema guarantees after ingestion.
- `utils/news_enrichment.py` is a 1,600-plus-line policy, network, matching, diagnostics, and orchestration module; splitting these responsibilities would make failure behavior and tests easier to reason about.
- Recency rules are distributed and inconsistent: source adapters use date-only “two calendar days” checks, AIBase demands Beijing “today,” and enrichment uses strict rolling hours (`sources/techcrunch.py:113`, `sources/aibase.py:214`, `utils/news_enrichment.py:169`).
- The pipeline lacks a single run/result model that records stage status, source errors, counts, durations, and artifact paths; console output and the enrichment subreport are the only visible execution state (`main.py:94`, `utils/news_enrichment.py:658`).
<!-- GSD:architecture-end -->

<!-- GSD:skills-start source:skills/ -->
## Project Skills

No project skills found. Add skills to any of: `.claude/skills/`, `.agents/skills/`, `.cursor/skills/`, or `.github/skills/` with a `SKILL.md` index file.
<!-- GSD:skills-end -->

<!-- GSD:workflow-start source:GSD defaults -->
## GSD Workflow Enforcement

Before using Edit, Write, or other file-changing tools, start work through a GSD command so planning artifacts and execution context stay in sync.

Use these entry points:
- `/gsd-quick` for small fixes, doc updates, and ad-hoc tasks
- `/gsd-debug` for investigation and bug fixing
- `/gsd-execute-phase` for planned phase work

Do not make direct repo edits outside a GSD workflow unless the user explicitly asks to bypass it.
<!-- GSD:workflow-end -->



<!-- GSD:profile-start -->
## Developer Profile

> Profile not yet configured. Run `/gsd-profile-user` to generate your developer profile.
> This section is managed by `generate-claude-profile` -- do not edit manually.
<!-- GSD:profile-end -->
