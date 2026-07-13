# Phase 1 Research: Run Contracts, Clock, and Manifest

**Phase:** 01-run-contracts-clock-and-manifest  
**Researched:** 2026-07-10  
**Status:** Ready for planning  
**Scope:** RUN-01, SRC-01, SRC-03, DEL-01 only. This phase establishes additive contracts and persistence; it must not stage/promote public artifacts or alter source/CLI behaviour.

## Executive Recommendation

Add a small, standalone `run_contracts` module (the exact filename is discretionary) containing immutable Pydantic v2 persisted models, a standard-library `RunClock`, canonical redaction/fingerprint helpers, and a manifest repository. Keep it outside `main.py`, `sources/`, and `utils/storage.py` so the later transactional and orchestration phases can depend on it without changing the current pipeline in Phase 1.

The implementation commit should create and persist a `DailyRunManifest` from a testable factory. It should expose, but not yet wire into, the compatible legacy `fetch_all`, dated storage helpers, source adapters, and CLI commands. A narrow non-disruptive CLI integration may be planned only if it can create a manifest per invocation while preserving all existing output paths and command semantics; do not refactor the existing flow to consume it until the dependent phases.

## Research Inputs and Current State

- `config.py` already uses Pydantic **2.13.4** (`Settings`), but uses the old inner `Config` convention with `extra = "ignore"`. Persisted run contracts need the opposite policy: `extra="forbid"` so an unknown manifest field is rejected on reload.
- `main.py` calls `today_ymd()` and `today_cn()` separately and does not carry a run object. It passes a date string to Tavily and writes directly to dated public paths.
- `utils/storage.py` calls `datetime.now(UTC+8)` separately for each title/date helper. It is deliberately unchanged in this phase; `RunClock` is the replacement seam for later integration.
- `sources.fetch_all()` preserves only a combined `list[Article]`, catches failures after printing, and cannot yet populate per-source outcomes. Phase 1 defines the schema only; Phase 3 supplies the executing adapter/retry classification.
- The current test style is pytest with `monkeypatch`, fixed strings, and `tmp_path`. Existing gray regression assertions observe the old call ordering and must remain valid.
- Context7 was attempted for current Pydantic v2 reference (`npx ctx7@latest library pydantic ...`) but the request returned `fetch failed`; no Context7 content was available. The installed package version was verified locally as 2.13.4. Plan implementation against its supported `BaseModel`, `ConfigDict`, `model_validate`, and `model_dump` interfaces, and re-check Context7 during implementation if service access recovers.

## Standard Stack

Use only the existing dependency plus Python 3.12 standard library:

| Concern | Use | Why |
| --- | --- | --- |
| Persisted contract schemas | Pydantic v2 `BaseModel`, `ConfigDict`, `Field`, `model_validator` | Existing project dependency; strict validation and deterministic JSON-ready dumps. |
| Status domains | `typing.Literal` | Makes invalid stage/source states fail at the persistence boundary. |
| Immutability | `ConfigDict(frozen=True, extra="forbid")` plus tuples instead of lists | Pydantic prevents attribute reassignment; tuples prevent mutating a nested collection after construction. |
| IANA timezone | `zoneinfo.ZoneInfo` | Standard library and valid named-timezone semantics, with no `pytz` coupling. |
| Time values | aware `datetime`, `timedelta`, normalized to UTC for serialized instants | Removes naive-time ambiguity while retaining configured-timezone report-date/display semantics. |
| IDs | injected callable defaulting to `uuid.uuid4().hex` | Allows exact fixed IDs in tests without relying on UUID ordering or a third-party UUIDv7 package. |
| Canonical fingerprint | `json.dumps(..., sort_keys=True, separators=(",", ":"), ensure_ascii=False)` then `hashlib.sha256` | Stable byte representation and no hand-rolled crypto. |
| Manifest bytes | `model_dump(mode="json")`, canonical JSON helper, UTF-8 | Pydantic turns dates into JSON values; canonical encoding makes test fixtures and hashes stable. |
| File location | a new run-manifest path API, initially backed by a caller-supplied temporary/run directory | Avoids prematurely deciding Phase 2 staging/publication layout. |

## Proposed Contract Shape

Persist a schema version as a required, literal-compatible value (initially `1`) at the root. New future fields require a schema migration/version bump; silently accepting unknown fields is prohibited.

```python
StageStatus = Literal["ok", "degraded", "failed", "skipped"]
SourceStatus = Literal["ok", "empty", "degraded", "failed"]

class StrictFrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

class Diagnostic(StrictFrozenModel):
    code: str
    message: str
    details: tuple[tuple[str, str], ...] = ()

class StageResult(StrictFrozenModel):
    name: str
    status: StageStatus
    started_at: datetime
    finished_at: datetime | None = None
    duration_ms: int | None = Field(default=None, ge=0)
    diagnostics: tuple[Diagnostic, ...] = ()

class SourceRunResult(StrictFrozenModel):
    source: str
    status: SourceStatus
    attempts: int = Field(ge=0)
    duration_ms: int = Field(ge=0)
    fetched_count: int = Field(ge=0)
    accepted_count: int = Field(ge=0)
    error_kind: str | None = None
    error_message: str | None = None
    articles: tuple[ArticleSnapshot, ...] = ()

class ArtifactHash(StrictFrozenModel):
    name: str
    algorithm: Literal["sha256"] = "sha256"
    digest: str | None = None       # slot is `None` until produced in a later phase

class PublicationState(StrictFrozenModel):
    status: Literal["pending", "published", "blocked", "not_attempted"] = "pending"
    published_run_id: str | None = None
    reason: str | None = None

class DailyRunManifest(StrictFrozenModel):
    schema_version: Literal[1] = 1
    run_id: str
    report_date: date
    timezone: str
    started_at: datetime
    cutoff_at: datetime
    deadline_at: datetime
    config_fingerprint: str
    config_snapshot: Mapping[str, JsonValue]
    stages: tuple[StageResult, ...] = ()
    sources: tuple[SourceRunResult, ...] = ()
    artifacts: tuple[ArtifactHash, ...] = ()
    publication: PublicationState
    diagnostics: tuple[Diagnostic, ...] = ()
```

`ArticleSnapshot` should be a minimal additive persisted shape based on current `Article.to_dict()` fields, not a replacement for `sources.base.Article`. Source result `articles` are included because the phase context explicitly requires them; Phase 3 decides how source execution constructs them. Prefer a model with explicit scalar fields over `dict[str, Any]` so a malformed article cannot become durable run evidence.

Use validators to enforce invariants that types cannot express: all timestamp fields must be timezone-aware; `deadline_at >= cutoff_at >= started_at`; `accepted_count <= fetched_count`; `status="empty"` requires zero fetched/accepted articles and no error; `status="ok"` cannot carry an error; and failed/degraded sources must have an error classification or diagnostic. Keep validation compatible with partial/in-progress manifests: `StageResult.finished_at` and artifact digest slots can remain absent/`None` while a run is active.

For a genuinely immutable graph, do not expose lists or ordinary dictionaries in frozen models. Represent diagnostics as tuples, and either use a recursively JSON-serializable frozen mapping representation or canonicalize the snapshot to an immutable JSON string plus its fingerprint. If a mapping is retained for readable JSON, copying it on construction is still insufficient against nested mutation; make the public model value a tuple-of-key/value pairs or only return defensive copies. This detail matters because RUN-01 calls for immutable run facts, not merely assignment protection.

## Architecture Patterns

### 1. Construct one clock at the composition boundary

`RunClock.create(timezone_name, now=None, deadline_duration=...)` validates `ZoneInfo(timezone_name)`, rejects a naive injected `now`, converts it once into the configured timezone, and derives all facts from that instant:

```python
@dataclass(frozen=True, slots=True)
class RunClock:
    timezone_name: str
    started_at: datetime       # aware, configured zone
    report_date: date
    cutoff_at: datetime        # initially equal to started_at
    deadline_at: datetime

    @classmethod
    def create(
        cls,
        timezone_name: str,
        *,
        now: datetime | None = None,
        deadline_duration: timedelta = timedelta(minutes=20),
    ) -> "RunClock": ...

    @property
    def report_date_ymd(self) -> str: ...

    @property
    def report_date_cn(self) -> str: ...
```

Do not use `datetime.now()` anywhere inside properties or downstream helpers. If `now` is omitted, acquire it exactly once with `datetime.now(ZoneInfo(timezone_name))`. Convert external instants to UTC before canonical serialization (for example RFC 3339 `Z`) but keep a configured-zone derived report date and Chinese display title. This yields the same date around midnight for filenames, titles, cutoff comparisons, and future Tavily/source inputs.

The phase must define the dependency-injection seam only. Later phases pass this exact `RunClock` to source freshness checks, Tavily, title rendering, file naming, and deadline budgets; they do not recreate it from a date string.

### 2. Create manifests through a factory, evolve them functionally

Have `new_manifest(settings, clock, run_id_factory=...)` take the `Settings` object, build its redacted canonical snapshot/fingerprint, and return a manifest with explicit pending/empty slots. Have functional methods/helpers such as `with_stage(manifest, result)` return a new validated manifest, replacing a stage/source by stable name rather than mutating a list in place. This supports persistence after every later stage without a mutable shared state object.

Do not invoke global `get_config()` in this module. The CLI composition root can pass `cfg` to the factory, keeping unit tests independent of `.env`, the process singleton, and secrets.

### 3. Separate redaction from canonicalization and hashing

Algorithm:

1. `settings.model_dump(mode="json")` produces JSON-compatible primitives.
2. Recursively remove any mapping entry whose normalized key contains `key`, `secret`, `token`, or `password` (case-insensitive). Remove it; do not preserve a secret-derived hash or a value-shaped redaction placeholder.
3. For diagnostics, never add raw exception representations without passing a secret-aware text scrubber that replaces known configured secret values. Prefer stable `code`/`error_kind` and a bounded safe message.
4. Canonicalize recursively: mappings sorted by key, array order retained where order is semantic, then encode with fixed JSON separators and UTF-8.
5. Compute SHA-256 over those exact bytes. Store the lowercase hexadecimal digest and the redacted snapshot in the manifest.

Fingerprinting must be a pure function. Identical non-secret settings always yield identical snapshot bytes/digest; changing a non-secret nested setting changes it; changing only removed secret values does not leak or alter the redacted configuration fingerprint. Document that intentional property so operators do not infer a secret rotation from this fingerprint.

### 4. Repository owns I/O, model owns validation

`write_manifest(path, manifest)` accepts only a fully validated model and serializes deterministic UTF-8. `read_manifest(path)` reads JSON then calls `DailyRunManifest.model_validate(...)`; unknown fields, invalid statuses, timestamp mistakes, and malformed versioned records fail closed. Phase 1 persistence can use a direct write to its run/temporary path because atomic write/promotion is explicitly Phase 2. Do not claim last-known-good safety from Phase 1 manifest I/O.

Make the output path a parameter (for example `run_dir / "manifest.json"`). Do not add `.runs` path layout or call existing public storage functions until Phase 2 has its staging design.

## Backward-Compatible Integration Boundary

- Preserve `Article`, `fetch_all`, `save_json`, `save_markdown`, `today_ymd`, `today_cn`, all Tavily report keys, and all current parser argument/return shapes.
- Do not change `Settings.Config.extra = "ignore"`; strictness is scoped to persisted run contracts. Changing app configuration parsing would be a separate compatibility decision.
- Do not change `cmd_run`, `cmd_fetch`, `cmd_summarize`, or `cmd_build` call order during the contracts-only commit. Existing gray regression test instrumentation expects the current fetch/dedupe/enrich/save/summarize/save/build sequence.
- If manifest creation is wired to an invocation in this phase, do it as an additive observer and inject all dependencies. It must never select dates, overwrite article/Markdown/site paths, or turn existing print/return behavior into a new exit-code policy.
- Do not make `RunClock` silently replace `today_ymd`/`today_cn` yet. Add explicit adapter methods in a later small commit with characterization tests, so each source/storage integration is independently rollbackable.

## Don't Hand-Roll

- A timezone database or manual UTC+8 offsets: use `zoneinfo.ZoneInfo`, including DST-aware configured zones.
- UUIDv7 generation: Python 3.12 does not provide a standard UUIDv7 API; a random UUID4 plus injected test factory meets this phase's identity need without a new package.
- Cryptography: `hashlib.sha256` is sufficient for a deterministic integrity fingerprint. It is not a password hash or secrecy mechanism.
- JSON schema parsing/deserialization: Pydantic `model_validate` must be the persisted-manifest boundary.
- A generic mutable event store/state machine: Phase 1 needs a small versioned immutable record; the publication state machine belongs to Phases 2–3.
- A new settings framework or a Pydantic Settings migration: retain current `Settings` and project loading semantics.
- Atomic directory swap, recovery, or last-known-good pointers: those are Phase 2 and must not be partially implemented here.

## Common Pitfalls and Required Defenses

| Pitfall | Defense / test |
| --- | --- |
| `frozen=True` permits changing a nested list/dict | Use tuples/immutable representation and test mutation is impossible or cannot affect serialised data. |
| Naive test datetime passes silently | Reject it; fixed clocks must supply an aware value. |
| `ZoneInfo` invalid name becomes a delayed runtime error | Validate in `RunClock.create`; test an invalid IANA name. |
| Calling `now()` separately gives different dates around midnight | Construct one clock once; assert all date/title properties derive from it. |
| `datetime.isoformat()` preserves differing offsets for the same instant | Normalize persisted instants consistently to UTC/RFC 3339 in the canonical dump. |
| Pydantic defaults ignore unexpected fields | Set `extra="forbid"` on every persisted model and reload a JSON record containing an unexpected key. |
| Redaction only handles top-level `api_key` | Traverse nested mappings and lists; match case-insensitively on every key name. |
| Redacted string still reveals length/secret hash | Omit sensitive entries entirely, not `***` or a secret-derived digest. |
| Error messages leak query-string credentials or API tokens | Use classified diagnostics and scrub configured secret values before persistence. |
| Dict iteration or whitespace changes alter fingerprints | One canonical JSON function with sorted keys and fixed separators. |
| Reordering semantic source/stage events changes an otherwise equivalent fingerprint | Define and enforce a stable ordering (source name and canonical stage order) before dumping. |
| Phase 1 changes current CLI outputs/exit codes | Keep integration additive; characterize legacy call order before any optional invocation manifest hook. |
| Direct manifest writes are mistaken for safe publication | Clearly document Phase 2 as the first atomic/write-promotion step and keep tests scoped to manifests. |

## Code Examples

The following is a planning pattern, not code to paste verbatim; field names may be refined by the plan.

```python
def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def fingerprint_settings(settings: Settings) -> tuple[dict[str, object], str]:
    raw = settings.model_dump(mode="json")
    redacted = redact_sensitive_mapping(raw)
    digest = hashlib.sha256(canonical_json_bytes(redacted)).hexdigest()
    return redacted, digest


def read_manifest(path: Path) -> DailyRunManifest:
    data = json.loads(path.read_text(encoding="utf-8"))
    return DailyRunManifest.model_validate(data)
```

```python
fixed_now = datetime(2026, 7, 10, 23, 59, tzinfo=ZoneInfo("Asia/Shanghai"))
clock = RunClock.create(
    "Asia/Shanghai",
    now=fixed_now,
    deadline_duration=timedelta(minutes=15),
)
assert clock.report_date_ymd == "2026-07-10"
assert clock.report_date_cn == "2026年07月10日"
assert clock.deadline_at - clock.started_at == timedelta(minutes=15)
```

## Validation Architecture

Validation is offline-only, deterministic, and split into contract, persistence, and compatibility layers. It provides the GSD verification loop for this phase without claiming future publication guarantees.

### Test files and fixtures

Create focused pytest files such as `tests/test_run_clock.py`, `tests/test_run_contracts.py`, and `tests/test_run_manifest.py`. Reuse `tmp_path`; use a fixed aware `datetime`, a fixed `run_id_factory`, and `Settings(...)` constructed with safe fake secret strings. No network, real clock, `.env`, global config cache, or existing data directory is allowed.

### Contract tests

- A fixed IANA-zone clock yields a stable `report_date`, `report_date_ymd`, Chinese display date, cutoff, and deadline. Include a UTC instant that crosses the configured-zone date boundary.
- Invalid timezone names and naive injected instants fail immediately; negative deadline durations fail.
- Model construction rejects unknown fields, unknown status literals, negative counts/durations, impossible count relationships, timezone-naive timestamps, and invalid lifecycle timestamp ordering.
- `SourceRunResult` accepts all four documented statuses and persists attempts, duration, fetched/accepted counts, classified error fields, and typed article snapshots.
- `DailyRunManifest` has a literal schema version, the required run/clock/config/publication/artifact fields, and immutable nested collections.

### Redaction and determinism tests

- Nested `api_key`, `fallback_api_key`, `syft_secret_key`, `tavily_api_key`, mixed-case `AccessToken`, and any field name containing `key`, `secret`, `token`, or `password` are absent from the snapshot and serialized manifest. Assert neither fake secret value nor its key name is present in JSON.
- The same settings supplied with different insertion ordering produce byte-identical canonical JSON and fingerprints.
- A non-secret setting change changes the fingerprint; a secret-only change does not. Document the latter expected redacted-fingerprint behavior in the test name.
- A diagnostic containing a configured fake secret is scrubbed before manifest serialization.

### Persistence tests

- Write a manifest to `tmp_path`, reload with `read_manifest`, and compare canonical bytes/model equality with fixed inputs.
- Hand-edit the persisted JSON to add an unknown field, corrupt `schema_version`, corrupt a status, or use a naive timestamp; each reload must fail validation.
- Verify artifact hash slots and publication slots serialize as explicit pending/empty values, not omitted ambiguously.

### Compatibility characterization

- Run the existing `tests/test_main_summary.py` and Tavily gray regression tests unchanged to prove contracts-only work did not alter legacy collection/summarize/build sequencing.
- Add at most one narrow invocation-factory test if a manifest hook is introduced; it must assert existing `today_*`, save path, and stage call behavior are untouched.
- Execute `pytest -q` and the repository's configured lint command after the single implementation commit. The final Phase 1 evidence should record command output and commit ID on the gray branch/Draft PR #8, but Phase 1 does **not** satisfy the later P0/gray/final GitHub Actions gates.

## Planning Sequence and Commit Boundary

One independently verifiable implementation commit can contain these tightly coupled pieces:

1. Add strict immutable schema models, canonical redaction/fingerprint helpers, `RunClock`, and manifest read/write/factory APIs in new modules.
2. Add the offline deterministic test suite above and compatibility characterization; do not modify legacy runtime modules unless an additive manifest creation hook is proven non-invasive.
3. Update Phase 1 operational/design documentation with schema version, redaction policy, clock injection contract, and explicit Phase 2 handoff.

Keep this one commit limited to Phase 1 facts. Transactional staging/promotion, public artifact hashing, source execution/retry behavior, and current-time replacement belong to later independently verifiable commits.

## Confidence and Open Decisions

- **High confidence:** Pydantic v2 is already installed; strict/frozen models, standard `zoneinfo`, SHA-256 canonical JSON, and injected clock/ID factories fit the existing Python 3.12 file-backed architecture.
- **High confidence:** Existing direct-write/publication risks must remain deferred to Phase 2; no Phase 1 test can prove last-known-good preservation yet.
- **Medium confidence:** Whether Phase 1 should create a manifest for every real CLI invocation now. The success criterion says every invocation, while the compatibility decision says do not change CLI mechanics. Plan an additive hook only after inspecting the plan's test impact; otherwise document the exact minimal wrapper needed and make it the same commit with no changed public artifacts.
- **Open implementation choice:** Select a `runs_dir` setting/default only if required by the invocation hook. Keeping the manifest repository caller-path based is safer until Phase 2 establishes the run-scoped directory topology.

## Sources

- Local project contracts: `.planning/phases/01-run-contracts-clock-and-manifest/01-CONTEXT.md`, `.planning/REQUIREMENTS.md`, `.planning/ROADMAP.md`, `.planning/STATE.md`.
- Local implementation evidence: `config.py`, `main.py`, `utils/storage.py`, `sources/base.py`, `sources/__init__.py`, and existing pytest suites.
- Pydantic documentation lookup: Context7 attempted on 2026-07-10 but failed with `fetch failed`; no external reference was used as a substitute. Installed Pydantic was verified locally as 2.13.4.
