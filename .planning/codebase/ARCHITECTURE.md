# Core Architecture

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

1. `get_config()` supplies one cached `Settings` object (`config.py:194`, `config.py:198`).
2. `fetch_all()` instantiates each enabled source adapter and concatenates its `Article` values (`sources/__init__.py:32`, `sources/__init__.py:52`).
3. `dedupe()` sorts by priority and removes identical normalized-title plus domain keys (`utils/dedupe.py:31`, `utils/dedupe.py:44`).
4. The orchestrator converts dataclass records to dictionaries before enrichment and persistence (`main.py:111`).
5. `enrich_articles_with_tavily()` optionally validates candidates, fills shortfalls from trusted domains, and returns both final articles and a detailed report (`utils/news_enrichment.py:1349`).
6. The dated JSON checkpoint stores `date`, `articles`, and `enrichment` diagnostics (`main.py:115`, `utils/storage.py:34`).
7. `summarize()` compresses input, tries configured OpenAI-compatible providers in order, and rejects responses that fail content-quality rules (`summarizer.py:143`, `summarizer.py:164`, `summarizer.py:192`).
8. `save_markdown()` writes a dated document with frontmatter (`utils/storage.py:52`), after which `build_site()` rebuilds the whole output directory (`build.py:234`, `build.py:241`).

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

