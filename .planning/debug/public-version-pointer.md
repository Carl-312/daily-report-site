---
status: diagnosed
trigger: "Investigate the remaining P0 in /home/carl/daily-report-site: data/, content/, and dist/ do not expose one single public version pointer, so readers can observe a mixed edition across paths. Find the root cause and propose a concrete fix, with special attention to existing staged publication and promotion code. Do not make code edits yet; create or update .planning/debug/public-version-pointer.md with evidence, hypotheses, reproduction, and recommended implementation."
created: 2026-07-10T00:00:00+08:00
updated: 2026-07-10T00:40:00+08:00
---

## Current Focus

hypothesis: The staged promotion protocol switches independently named public paths, so there is no atomic reader-visible edition selector.
test: Compare the controlled interleaving result with the competing explanations (journal recovery, site-directory rename, and DailyRunManifest) and run the full regression suite for unintended evidence.
expecting: The competing mechanisms will be shown to be writer recovery/observability only, while the mixed tuple remains reachable; full tests should remain green because the missing invariant has no regression test.
next_action: Diagnosis complete; implement the versioned-edition pointer design in a separate change plan.

## Symptoms

expected: A successful daily run exposes one atomically selected public edition for JSON, Markdown, and site reads; a failed/interrupted run leaves the previous public edition intact with readers never needing to combine independently switched paths.
actual: Existing promotion replaces JSON, Markdown, and site through separate filesystem operations, with no single public version pointer or reader contract.
errors: Code-review P0 from the current delivery state; no runtime exception required.
reproduction: Inspect utils/publication.py, main.py, build.py, and tests around promotion; reason about a reader observing paths between individual promotions.
started: Existing staged publication work is present, but the cross-path atomic read view is explicitly listed as incomplete in the task handoff.

## Evidence

- timestamp: 2026-07-10T00:10:00+08:00
  checked: "utils/publication.py, main.py, build.py, tests/test_publication.py, tests/test_staged_run.py, tests/test_atomic_storage.py"
  found: "The repository has journaled staged-file promotion and directory replacement, but no public version manifest/pointer or reader helper. stage_and_publish_run calls promote_staged_files for JSON and Markdown, then promote_staged_directory for dist."
  implication: "The existing mechanism can make each target replacement recoverable, but it does not define one reader-visible commit point across all three public surfaces."

- timestamp: 2026-07-10T00:10:00+08:00
  checked: "promote_staged_files implementation and its failure test"
  found: "For each mapping, the code performs os.replace(target, backup) followed by os.replace(staged, target) in sequence. The test injects failure on a later replace and verifies rollback only after the writer raises."
  implication: "A reader interleaving during the loop can observe new JSON while Markdown and site remain old; rollback restores after the observation but cannot make the observation impossible."

- timestamp: 2026-07-10T00:10:00+08:00
  checked: "promote_staged_directory and stage_and_publish_run call order"
  found: "The site directory is renamed only after the JSON/Markdown file promotion returns successfully. The site has a directory rename boundary, but that boundary is separate from the file promotion boundary."
  implication: "A successful run has at least two public switch points, and an interrupted run can leave files changed while dist remains old (or vice versa depending on failure location)."

- timestamp: 2026-07-10T00:10:00+08:00
  checked: "build.py and existing tests"
  found: "build_site reads Markdown from content_dir and writes a complete dist candidate; tests assert old artifacts survive build failure and that per-file promotion replaces staged files. No test reads all public surfaces through a version-selection contract or injects a reader between promotions."
  implication: "The test suite proves writer-side staging/rollback properties, not the missing cross-path public read invariant."

- timestamp: 2026-07-10T00:20:00+08:00
  checked: "pytest -q tests/test_publication.py tests/test_staged_run.py tests/test_atomic_storage.py"
  found: "9 focused tests passed. They cover atomic single-file writes, rollback after an injected promotion failure, staged build failure preservation, complete site directory replacement, and equivalent-edition no-op behavior."
  implication: "The current implementation satisfies its existing writer-side tests; the P0 is an untested invariant gap, not evidence that those tests are failing."

- timestamp: 2026-07-10T00:20:00+08:00
  checked: "All Python references to publication, public paths, manifests, and readers"
  found: "No public-version pointer, edition resolver, or reader API exists. load_json reads data/<date>.json directly; build_site reads content directly and writes dist directly. DailyRunManifest records published_run_id for observability but is stored inside the run workspace and is not the public selector."
  implication: "A manifest's published_run_id cannot coordinate public reads because it is neither atomically published with the artifacts nor consulted by data/content/site consumers."

- timestamp: 2026-07-10T00:20:00+08:00
  checked: "Controlled replace interleaving model of promote_staged_files followed by promote_staged_directory"
  found: "Starting from O=(old JSON, old Markdown, old dist), after the first file replacement the visible state is (new JSON, old Markdown, old dist); after the second it is (new JSON, new Markdown, old dist); only after the directory replacement is it N=(new JSON, new Markdown, new dist). The writer can be interrupted or a reader can run at either intermediate state."
  implication: "The mixed-edition state is directly reachable without any runtime exception and remains observable until the later operations complete. Rollback is compensating work after partial exposure, not an atomic read boundary."

- timestamp: 2026-07-10T00:30:00+08:00
  checked: "The same controlled interleaving with readers after each os.replace"
  found: "Observed states included (N-json, O-md, O-site) after JSON installation, (N-json, N-md, O-site) after Markdown installation, and (N-json, N-md, N-site) only after site-directory installation; temporary missing-target states also occurred during target-to-backup moves."
  implication: "The reproduction demonstrates both mixed editions and transient missing files for direct-path readers, independent of whether the final promotion succeeds."

## Eliminated

- hypothesis: "The promotion journal makes the multi-path operation atomic to readers."
  evidence: "The journal is written before/after the replacements and recovery runs on a later startup; neither operation coordinates readers or changes the fact that each target is replaced separately."
  timestamp: 2026-07-10T00:30:00+08:00

- hypothesis: "Replacing dist as one directory is sufficient to provide a single public edition."
  evidence: "dist is switched only after data and content have already been switched, so the JSON/Markdown-to-site relation still has a two-boundary window."
  timestamp: 2026-07-10T00:30:00+08:00

- hypothesis: "DailyRunManifest.published_run_id is already the public version pointer."
  evidence: "The manifest lives under the run workspace, is updated after promotion, and no load_json/build/site reader consults it. It records publication after the fact rather than selecting the artifact set before reads."
  timestamp: 2026-07-10T00:30:00+08:00

## Resolution

root_cause: "Publication has multiple independently replaced public roots. stage_and_publish_run first promotes data/<date>.json and content/<date>.md through sequential per-file os.replace calls, then promotes dist/ through a separate directory rename. There is no atomically switched public selector and no reader contract that resolves all artifacts from one selected edition. Consequently, a reader can observe mixed old/new editions or transient missing files between filesystem operations; journal rollback only compensates after failure and cannot retract a read already made."
fix: "Recommended implementation (not applied in this diagnose-only session): stage an immutable, self-contained edition under a run/version directory, e.g. .public/editions/<run_id>/{data,content,dist}, including an edition manifest with run_id/report_date and artifact hashes. Validate/build every artifact there. Publish exactly one small root pointer, e.g. .public/public-version.json, with atomic temp-file-plus-os.replace; the pointer is the sole commit boundary and must be written only after the edition is complete. Add a resolver that reads the pointer once per logical request and resolves JSON, Markdown, and site paths relative to that edition. Update load_json, build/deployment readers, retention, and documentation to use the resolver. Existing promote_staged_files/promote_staged_directory should become staging/validation helpers or be replaced by one edition promotion; they must not independently switch authoritative public paths. Do not retain data/, content/, and dist/ as independently switched authoritative aliases, because that preserves the P0. If legacy paths must remain, treat them as compatibility-only and require callers to resolve the pointer first; GitHub Pages should upload the selected edition's dist as one deployment artifact."
verification: "Diagnosis evidence: focused promotion tests passed 9/9; full suite passed 69/69 with one unrelated Pydantic deprecation warning; controlled replace interleaving observed (new JSON, old Markdown, old site) and (new JSON, new Markdown, old site). The implementation change should add tests for pointer-before/after crash behavior, a reader that reads the pointer once, pointer-target retention safety, and failure injection proving the old pointer and old edition remain authoritative until the final pointer replace."
files_changed: []
