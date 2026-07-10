# Core Code Conventions

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
