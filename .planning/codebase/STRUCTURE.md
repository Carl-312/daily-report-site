# Core Structure

## Repository Root

- `README.md` describes the automated daily-news product, commands, deployment cadence, retention model, and high-level directory layout (`README.md:1`, `README.md:26`, `README.md:51`, `README.md:66`).
- `main.py` is the composition root and CLI. It should remain responsible for argument handling and top-level stage sequencing, not source or enrichment policy (`main.py:89`, `main.py:219`).
- `config.py` defines validated settings, merges environment/YAML inputs, and caches the runtime configuration (`config.py:22`, `config.py:139`, `config.py:194`).
- `summarizer.py` owns prompt loading, article compression, provider order, API invocation, summary validation, offline rendering, and connectivity checks (`summarizer.py:24`, `summarizer.py:33`, `summarizer.py:65`, `summarizer.py:246`).
- `build.py` owns static HTML templates, frontmatter parsing, Markdown conversion, page metadata, asset copying, and output generation (`build.py:17`, `build.py:155`, `build.py:186`, `build.py:241`).

## Source Adapter Package

- `sources/base.py` contains the shared `Article` dataclass and abstract `BaseSource` HTTP/HTML helper contract (`sources/base.py:13`, `sources/base.py:37`).
- `sources/__init__.py` is the adapter registry and multi-source fetch coordinator (`sources/__init__.py:15`, `sources/__init__.py:32`).
- `sources/aibase.py` handles a digest-style source: discover the newest daily page, fetch its detail, extract content, and reject it unless it is today in Beijing (`sources/aibase.py:32`, `sources/aibase.py:60`, `sources/aibase.py:91`, `sources/aibase.py:214`).
- `sources/techcrunch.py` scrapes homepage links, extracts dates from URL paths, and retains recent date-based candidates (`sources/techcrunch.py:23`, `sources/techcrunch.py:36`, `sources/techcrunch.py:105`).
- `sources/theverge.py` applies the same link/date strategy to The Verge's AI section (`sources/theverge.py:23`, `sources/theverge.py:34`, `sources/theverge.py:93`).
- `sources/syft.py` adapts a credentialed Google Apps Script JSON endpoint into `Article` records (`sources/syft.py:20`, `sources/syft.py:25`).

## Utility Package

- `utils/dedupe.py` normalizes titles, extracts domains, hashes exact keys, and retains the highest-priority item per key (`utils/dedupe.py:17`, `utils/dedupe.py:31`, `utils/dedupe.py:44`).
- `utils/news_enrichment.py` is the optional post-fetch Tavily subsystem. It owns title matching, recency parsing, prefiltering, story clustering, network calls, verification, refill, and diagnostics (`utils/news_enrichment.py:117`, `utils/news_enrichment.py:151`, `utils/news_enrichment.py:306`, `utils/news_enrichment.py:485`).
- `utils/storage.py` owns Beijing-date naming plus JSON/Markdown file reads and writes (`utils/storage.py:12`, `utils/storage.py:16`, `utils/storage.py:34`, `utils/storage.py:43`, `utils/storage.py:52`).

## Runtime Directories Referenced By Core Code

- `prompts/` contains the summary prompt selected by `Settings.prompt_path`; the inspected core falls back to a built-in Chinese editor prompt if the file is absent (`config.py:64`, `summarizer.py:24`).
- `data/` is the default dated JSON checkpoint directory (`config.py:65`, `main.py:115`).
- `content/` is the default dated Markdown publication-source directory (`config.py:66`, `utils/storage.py:52`).
- `assets/` is the static asset input directory copied into the build output (`build.py:141`, `build.py:255`).
- `dist/` is the default generated site directory and is fully recreated for each build (`config.py:67`, `build.py:234`).
- The README states that `data/` and `content/` keep a seven-day working window while older history is released separately (`README.md:11`, `README.md:61`, `README.md:76`).

## Dependency Direction

- `main.py` depends on `config.py`, `sources/`, `utils/`, `summarizer.py`, and lazily on `build.py` (`main.py:10`, `main.py:11`, `main.py:12`, `main.py:21`, `main.py:141`).
- `sources/__init__.py` depends on the abstract model/contract and every concrete adapter (`sources/__init__.py:9`).
- Concrete source adapters depend only on `sources/base.py` plus standard-library helpers (`sources/techcrunch.py:11`, `sources/theverge.py:11`, `sources/syft.py:10`).
- `utils/dedupe.py` and `utils/news_enrichment.py` depend on `sources.base.Article`, making the ingestion model the shared cross-layer schema (`utils/dedupe.py:12`, `utils/news_enrichment.py:21`).
- `summarizer.py` and `build.py` independently depend on `config.py`, but neither depends on source implementation details (`summarizer.py:12`, `build.py:15`).
- `utils/storage.py` is leaf-like and has no project-internal imports in the inspected core.

## Where To Add Or Change Behavior

- Add a conventional HTML/JSON source by subclassing `BaseSource`, returning `Article` values, and registering it in `sources/__init__.py`; current registration is static (`sources/base.py:54`, `sources/__init__.py:16`).
- Change global pipeline sequencing or CLI options in `main.py`; stage logic should preferably be extracted before adding more commands because `cmd_run()` and `cmd_fetch()` already duplicate work.
- Change provider order, prompting, token compression, or output-quality rules in `summarizer.py` (`summarizer.py:97`, `summarizer.py:143`).
- Change article verification/refill policy in `utils/news_enrichment.py`, especially the prefilter at line 595, verify stage at line 961, refill stage at line 1122, and coordinator at line 1349.
- Change dated artifact shape and write guarantees in `utils/storage.py`; this is the narrowest place to introduce atomic temporary-file writes.
- Change generated-site structure in `build.py`; safer publication semantics would build to a staging directory and swap only after all pages succeed.

## Structural Risks Relevant To Daily Operation

- Adapter configuration is not polymorphic: `fetch_all()` special-cases Syft constructor arguments (`sources/__init__.py:57`), so adding credentialed sources will grow conditionals in the registry coordinator.
- `Article.publish_time` is an untyped string (`sources/base.py:20`); every adapter/enrichment path interprets it independently.
- Source names, recency, and failure details are not represented in a shared fetch-result object, so an empty list can mean valid emptiness, missing credentials, parse drift, or network failure (`sources/syft.py:27`, `sources/syft.py:63`).
- Configuration models validate types but provide few semantic bounds; values such as negative budgets or impossible relationships can reach runtime policy code (`config.py:108`).
- `build.py` combines very large inline presentation templates with build mechanics, making template safety and escaping difficult to isolate (`build.py:17`, `build.py:224`).
- The dated filenames are simple and operationally useful, but direct writes and destructive rebuilds do not provide transactional publication across JSON, Markdown, and HTML (`utils/storage.py:37`, `build.py:236`).
