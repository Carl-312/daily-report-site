# External Integrations

## Integration map

| Integration | Direction | Authentication | Core code | Daily-path role |
| --- | --- | --- | --- | --- |
| AIBase | inbound HTML | none | `sources/aibase.py:25-58` | supplies a Beijing-date daily AI digest |
| TechCrunch | inbound HTML | none | `sources/techcrunch.py:17-34` | supplies recent general technology articles |
| The Verge | inbound HTML | none | `sources/theverge.py:16-32` | supplies recent AI-section articles |
| Syft / Google Apps Script | inbound JSON | query-string secret | `sources/syft.py:20-61` | supplies curated newsletter articles for the current Beijing date |
| Tavily Search API | outbound JSON POST | API key in JSON body | `utils/news_enrichment.py:485-502` | verifies candidates and refills shortages from trusted domains |
| ModelScope | outbound OpenAI-compatible chat API | API key | `config.py:25-37`, `summarizer.py:118-130` | primary and secondary LLM summary models |
| SiliconFlow | outbound OpenAI-compatible chat API | API key | `config.py:39-46`, `summarizer.py:132-138` | final LLM provider fallback |
| GitHub Actions / Pages / Releases | automation and delivery | repository-managed | `README.md:51-62` | schedules generation, deploys static pages, archives old reports |

## News-source boundary

- `fetch_all` executes enabled sources one at a time and combines their `Article` records in `sources/__init__.py:32-70`.
- Per-source exceptions are caught at the registry boundary, printed, and omitted, so one failed public source does not stop the remaining fetches (`sources/__init__.py:52-69`).
- The source abstraction standardizes title, link, description, publish time, content, priority, and source name (`sources/base.py:13-34`).
- All standard source sessions disable environment proxy inheritance with `trust_env=False` (`sources/base.py:50-52`).
- Standard source GET calls use a 15-second default timeout, browser-like headers, and an empty proxy mapping (`sources/base.py:42-61`).
- AIBase performs two dependent HTML requests: the daily listing and then the selected detail page (`sources/aibase.py:36-47`, `sources/aibase.py:91-125`).
- AIBase accepts only an article whose content or publish timestamp resolves to the current Beijing date (`sources/aibase.py:51-58`, `sources/aibase.py:214-236`).
- AIBase detail extraction swallows every exception and returns `None`, losing transport/parser failure identity (`sources/aibase.py:91-125`).
- TechCrunch parses homepage links and derives publication dates from dated URL paths rather than structured page metadata (`sources/techcrunch.py:23-34`, `sources/techcrunch.py:89-122`).
- The Verge similarly parses the AI section and requires URL-derived dates for its recentness filter (`sources/theverge.py:23-32`, `sources/theverge.py:93-108`).
- Both TechCrunch and The Verge use a day-difference test labeled 48 hours; this is calendar-date based and can admit future dates because it only checks `diff.days <= 1` (`sources/techcrunch.py:113-122`, `sources/theverge.py:101-108`).
- Syft calls a configured web-app URL with `secret` and `date` query parameters and a 30-second timeout (`sources/syft.py:25-41`).
- Syft treats missing credentials, an unsuccessful JSON payload, and any exception as an empty source result (`sources/syft.py:25-28`, `sources/syft.py:44-46`, `sources/syft.py:63-64`).
- Syft inputs are mapped permissively with default empty strings and are not schema-validated at the boundary (`sources/syft.py:48-59`).

## Tavily verification and refill

- Tavily is optional and disabled by default in configuration (`config.py:108-123`); CLI flags can explicitly force it on or off (`main.py:29-49`, `main.py:231-249`).
- The API endpoint is fixed to `https://api.tavily.com/search` and requests have a 45-second timeout (`utils/news_enrichment.py:23-28`, `utils/news_enrichment.py:485-502`).
- Authentication is sent as `api_key` in the JSON request body (`utils/news_enrichment.py:492-495`).
- The Tavily session follows the configurable `trust_env` proxy policy, unlike source sessions which always disable it (`utils/news_enrichment.py:1394-1395`, `config.py:111-112`).
- Candidate verification performs quoted-title news searches with a date range, configurable search depth, and at most three results (`utils/news_enrichment.py:984-998`).
- Verification matches exact canonical URL first, then same-domain title similarity at a threshold of 0.82 (`utils/news_enrichment.py:519-559`, `utils/news_enrichment.py:1021-1034`).
- Successful verification also requires a parseable publication date within the strict hour window (`utils/news_enrichment.py:1030-1050`).
- Transport failures are classified into timeout, HTTP, connection, request, and unexpected categories (`utils/news_enrichment.py:505-516`).
- A verification request error preserves the original candidate, implementing fail-open behavior for transient Tavily faults (`utils/news_enrichment.py:1098-1107`, `utils/news_enrichment.py:1647-1650`).
- Verification budget reserves capacity for refill and is bounded by both per-stage and total-call settings (`utils/news_enrichment.py:940-977`).
- Refill uses Tavily advanced search, domain allowlists, date bounds, a configurable result cap, and a bounded number of rounds (`utils/news_enrichment.py:1141-1177`).
- Refill proceeds through priority media, secondary media, and optional official-domain stages (`config.py:85-105`, `utils/news_enrichment.py:1480-1603`).
- Strict refill accepts only in-window, AI-relevant, nonduplicate, nonclustered articles (`utils/news_enrichment.py:1200-1255`).
- The enrichment result includes detailed counts, per-request latency, request outcome, validation outcome, candidates, and stop reason (`utils/news_enrichment.py:658-762`, `utils/news_enrichment.py:1051-1089`, `utils/news_enrichment.py:1304-1329`).
- Missing API credentials or a top-level enrichment exception returns the original deduplicated articles rather than aborting the pipeline (`utils/news_enrichment.py:1380-1392`, `utils/news_enrichment.py:1653-1667`).
- The HTTP helper has a timeout but no retry, exponential backoff, jitter, rate-limit handling, or response-schema validation (`utils/news_enrichment.py:485-502`).

## LLM provider boundary

- ModelScope endpoint, primary model, and secondary model default to values declared in `config.py:17-37`.
- SiliconFlow endpoint and model defaults are declared in `config.py:39-46`.
- Secrets and endpoints are read from environment variables in `config.py:142-161`; secrets are not loaded from YAML by `load_config`.
- Provider candidates are ordered ModelScope primary, ModelScope secondary, then SiliconFlow, with duplicates removed by base URL plus model (`summarizer.py:97-140`).
- Every provider uses the same OpenAI-compatible chat-completions interface through `OpenAI(base_url=..., api_key=...)` (`summarizer.py:19-21`, `summarizer.py:168-191`).
- The request sends a system prompt plus JSON article input, sets temperature to 0.7, and caps output tokens from configuration (`summarizer.py:164-180`).
- Provider fallback catches any exception, records a provider/model error string, and tries the next candidate (`summarizer.py:182-201`).
- Each provider response is locally quality-validated before acceptance (`summarizer.py:188-196`).
- The LLM calls shown here do not set explicit request timeouts, retries, idempotency keys, or per-provider circuit breakers (`summarizer.py:168-224`).
- When API keys are entirely absent, `run` uses the deterministic offline summary (`main.py:67-75`); explicit `--offline` also bypasses providers.
- When configured providers fail or output fails quality checks, the normal online path aborts instead of publishing the lower-quality offline form (`main.py:76-86`).

## Persistence and publishing boundary

- The pipeline writes enriched source data before attempting LLM summarization (`main.py:111-129`), so fetched data survives a summary failure.
- JSON and Markdown writes open the final date-named path directly; there is no temporary-file write plus atomic replace (`utils/storage.py:34-40`, `utils/storage.py:52-65`).
- JSON load returns `None` only when the file is absent; malformed JSON and I/O errors propagate (`utils/storage.py:43-49`).
- The site build removes the entire configured output directory before rendering (`build.py:234-253`).
- Markdown is converted locally to standalone HTML, while index and archive pages are rebuilt from every retained Markdown file (`build.py:186-221`, `build.py:261-318`).
- The README states that GitHub Actions runs the daily fetch-summary-build-archive-deploy workflow at 00:36 UTC, chosen to reduce scheduler peak delay (`README.md:57-61`).
- Scheduled runs leave Tavily off; only manual workflow activation enables the canary enrichment path (`README.md:62`).
- GitHub Pages receives the generated static output, and GitHub Releases hold reports older than the seven-day branch retention window (`README.md:60-62`).

## Cross-integration operational characteristics

- The main command has no explicit run identifier, checkpoint manifest, or idempotency guard beyond overwriting date-named files (`main.py:89-150`, `utils/storage.py:34-65`).
- Source and provider diagnostics use `print`; the inspected path has no structured logger, metrics exporter, tracing context, or alerting hook.
- External calls are sequential, so latency and a slow timeout accumulate across sources, Tavily verification/refill calls, and provider fallbacks (`sources/__init__.py:52-69`, `utils/news_enrichment.py:984-1015`, `summarizer.py:168-201`).
- Failure policy is intentionally mixed: sources fail open, Tavily generally fails open, but online summary quality/provider exhaustion fails closed (`sources/__init__.py:67-70`, `utils/news_enrichment.py:1653-1667`, `main.py:76-86`).
- Beijing time is the operational date contract, but it is implemented in multiple modules with three mechanisms rather than one shared clock (`utils/storage.py:12-24`, `sources/aibase.py:14-22`, `utils/news_enrichment.py:23`).
