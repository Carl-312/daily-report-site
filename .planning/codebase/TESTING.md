# Core Testability Map

## Scope and Evidence

- Tests were deliberately not read; this document records only test seams and risks visible in the permitted core code.
- The README states that CI runs Ruff and pytest (`README.md:51-55`) and that a `tests/` directory exists (`README.md:66-83`), but no test file or test configuration was inspected.
- Consequently, every item below is a recommended or visible seam, not a claim about existing coverage.

## Strong Pure-Function Seams

- `utils/dedupe.py:17-69` is directly unit-testable with table-driven title, domain, priority, and ordering cases.
- `summarizer.py:50-95` exposes deterministic numbered-item parsing and Chinese-quality validation, including useful negative paths via `SummaryQualityError`.
- `summarizer.py:227-243` supports deterministic offline rendering tests without credentials or network calls.
- `build.py:155-183` exposes pure frontmatter and ordered-list transformations suitable for malformed-input and Markdown-shape tests.
- `utils/news_enrichment.py:123-219` provides pure normalization, URL, timestamp, recency, and relevance helpers.
- `utils/news_enrichment.py:270-456` provides deterministic story-relation, union-find clustering, and representative-collapse seams.
- `utils/news_enrichment.py:519-592` exposes ranking and cross-result cluster matching without transport dependencies.
- `utils/news_enrichment.py:595-655` makes prefilter inclusion/exclusion counters testable from plain dictionaries.
- `utils/news_enrichment.py:940-958` makes call-budget reservation testable across policy combinations.

## HTTP Adapter Seams

- `BaseSource.session` is an instance attribute, so tests can replace it with a fake session after construction (`sources/base.py:50-61`).
- `BaseSource._get()` centralizes HTML GET behavior for AIBase, TechCrunch, and The Verge (`sources/base.py:59-67`).
- Parser methods accept a soup object, allowing fixture HTML to bypass the network (`sources/aibase.py:60-89`, `sources/techcrunch.py:36-103`, `sources/theverge.py:34-91`).
- AIBase further separates detail extraction, selector selection, time parsing, summary extraction, body extraction, and date validation (`sources/aibase.py:91-236`).
- Syft bypasses `_get()` and calls `self.session.get()` directly, but the same replaceable session attribute remains usable (`sources/syft.py:30-44`).
- Tavily transport is centralized in `search_tavily(session, api_key, payload, timeout)` and accepts the session explicitly (`utils/news_enrichment.py:485-502`).
- Both Tavily stages accept a session and fixed reference time, allowing deterministic fake-response tests (`utils/news_enrichment.py:961-968`, `utils/news_enrichment.py:1122-1135`).

## Configuration Seams and Friction

- `load_config(config_path)` accepts a path and can be exercised with a temporary YAML file (`config.py:139-191`).
- Environment access remains direct through `os.getenv`, so tests must patch process environment (`config.py:142-162`).
- `.env` loading occurs at import time with `override=True`, which can mutate or unexpectedly replace test environment state (`config.py:14-15`).
- `get_config()` caches a global singleton, so tests that change environment or paths must reset private `_config` or reload the module (`config.py:194-203`).
- `summarizer.py` and `build.py` call `get_config()` internally, increasing patching needs compared with explicit settings injection (`summarizer.py:24-35`, `summarizer.py:97-100`, `build.py:141-152`).
- `EnrichmentSettings` is a typed, default-rich fixture source for policy tests (`config.py:108-133`), but enrichment stage signatures currently accept `Any` (`utils/news_enrichment.py:964`, `utils/news_enrichment.py:1129`).

## Time Seams and Risks

- Enrichment has the strongest time seam because its public entry point accepts `reference_dt` (`utils/news_enrichment.py:1349-1365`).
- `within_strict_hours()` is deterministic when given an explicit reference instant (`utils/news_enrichment.py:169-179`).
- Storage date helpers call the clock directly and cannot accept a test clock (`utils/storage.py:16-24`).
- Source recency methods also call `datetime.now(...)` directly (`sources/aibase.py:32-35`, `sources/techcrunch.py:113-122`, `sources/theverge.py:101-108`, `sources/syft.py:30-37`).
- Boundary tests should cover midnight in Asia/Shanghai, future publication times, naive timestamps, ISO `Z`, RFC dates, and DST-bearing source timestamps even though the report timezone itself has no DST (`utils/news_enrichment.py:151-179`).

## Pipeline and Failure-Policy Tests

- `resolve_enrichment_enabled()` is a small direct seam for CLI override precedence (`main.py:29-34`).
- `summarize_or_offline()` can be tested by patching `summarize`, `offline_summary`, and validation; important cases are explicit offline, no keys, invalid LLM output, and provider exception (`main.py:67-86`).
- `cmd_run()` has many global collaborators and filesystem side effects, so it requires broad monkeypatching rather than simple dependency injection (`main.py:89-150`).
- The source registry should be tested for partial failure: one adapter raises while later adapters still contribute articles (`sources/__init__.py:52-70`).
- A zero-source result currently proceeds through storage, summary, and build in `cmd_run()`; this deserves an explicit policy test because the online summarizer returns `暂无新闻`, which fails the later quality contract if revalidated (`main.py:97-143`, `summarizer.py:143-155`).
- Verify-stage tests should distinguish transport errors, successful no-match, stale match, and missing publication date because only transport errors preserve upstream articles (`utils/news_enrichment.py:1035-1050`, `utils/news_enrichment.py:1091-1107`).
- Refill tests should assert total-call ceilings, reserved-call behavior, stage order, no-domain short circuit, and early exit on empty/error rounds (`utils/news_enrichment.py:940-977`, `utils/news_enrichment.py:1141-1164`, `utils/news_enrichment.py:1331-1345`).
- Enrichment entry-point tests should lock down disabled, missing-key, full success, and unexpected-exception fail-open contracts (`utils/news_enrichment.py:1368-1397`, `utils/news_enrichment.py:1652-1667`).
- Report-schema tests should verify required counters and stop reasons because downstream diagnostics consume string-keyed dictionaries with no schema validation (`utils/news_enrichment.py:658-762`, `utils/news_enrichment.py:1611-1646`).

## Storage and Build Tests

- `save_json`, `load_json`, and `save_markdown` accept directory arguments and are suitable for temporary-directory round trips (`utils/storage.py:27-67`).
- Tests should simulate invalid JSON and write failures; `load_json()` currently catches neither decode errors nor I/O errors (`utils/storage.py:43-49`).
- Crash-safety tests are warranted because JSON and Markdown are written directly to their final filenames (`utils/storage.py:34-40`, `utils/storage.py:52-65`).
- `build_site()` accepts source, output, and asset directory overrides and returns generated article metadata (`build.py:241-249`, `build.py:316-318`).
- Build tests should cover an empty content directory, invalid dates, malformed frontmatter, missing assets, and output reset behavior (`build.py:200-204`, `build.py:234-264`).
- Security-focused rendering tests should include HTML-sensitive titles and frontmatter because values are inserted with string formatting and no explicit escaping (`build.py:206-231`, `build.py:291-313`).
- Destructive-boundary tests should ensure `prepare_output_dir()` never receives a source/root path, since it recursively deletes the supplied directory without an ownership guard (`build.py:234-238`).

## Highest-Value Coverage Priorities

- Priority 1: end-to-end daily-run state-machine tests for no articles, partial source failure, enrichment outage, invalid LLM output, storage failure, and build failure (`main.py:89-150`).
- Priority 2: contract tests for each source using captured minimal HTML/JSON fixtures, focused on selector drift and publication-time parsing (`sources/aibase.py:32-58`, `sources/techcrunch.py:23-34`, `sources/theverge.py:23-32`, `sources/syft.py:25-64`).
- Priority 3: enrichment property/table tests for budget invariants, deduplication invariants, and fail-open behavior (`utils/news_enrichment.py:940-958`, `utils/news_enrichment.py:961-1346`, `utils/news_enrichment.py:1349-1667`).
- Priority 4: atomic artifact publication and rebuild idempotence tests around storage/build boundaries (`utils/storage.py:34-67`, `build.py:234-318`).
- Priority 5: provider fallback tests proving that validation failure advances to the next provider and that aggregated error text does not expose secrets (`summarizer.py:168-201`).
