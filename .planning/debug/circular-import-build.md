---
status: awaiting_human_verify
trigger: "调查并修复灰度 Actions 构建失败，目标是让 python main.py build 和 GitHub Actions 的 skip_generate=true 预览构建成功。"
created: 2026-07-10T00:00:00+08:00
updated: 2026-07-10T00:25:00+08:00
---

## Current Focus

hypothesis: `sources.base` imports `utils.run_contracts` before defining `Article`, allowing `utils.__init__` → `utils.dedupe` to re-enter `sources.base`
test: move only the `RunDeadlineExceeded` import below the `Article` definition, add a fresh-interpreter import regression test, then run the original CLI reproduction
expecting: the import chain completes, `Article` remains available from `sources.base` and `sources`, and `python main.py build` reaches the build stage
next_action: rerun the gray Actions workflow with `skip_generate=true`; if it succeeds, archive this session as resolved

## Symptoms

expected: After deleting the generated 2026-07-10 page, `python main.py build` and the GitHub Actions `skip_generate=true` retained-content preview build succeed.
actual: `main.py` import fails through `sources.base -> utils.run_contracts -> utils.__init__ -> utils.dedupe -> sources.base` with `ImportError: cannot import name 'Article' from partially initialized module 'sources.base'`.
errors: ImportError: cannot import name 'Article' from partially initialized module 'sources.base'
reproduction: Run `python main.py build` locally; GitHub Actions run 29075820331 fails at `Build site from retained content`.
started: Immediately after merging origin/main and deleting two same-day generated files; deleting those files is reported not to be the root cause.

## Eliminated

## Evidence

- timestamp: 2026-07-10T00:05:00+08:00
  checked: debugging references and repository state
  found: circular dependency is a matching common bug pattern; branch is `gsd/daily-news-reliability`; only `.planning/quick/` is untracked and no daily artifacts were restored
  implication: investigate module initialization order and preserve unrelated planning files

- timestamp: 2026-07-10T00:10:00+08:00
  checked: `sources/base.py`, `utils/__init__.py`, `utils/dedupe.py`, `utils/run_contracts.py`, and fresh `python main.py build`
  found: `sources.base` imports `utils.run_contracts` at line 15 before `Article` at line 19; importing a `utils` submodule executes `utils/__init__.py`, whose first import is `utils.dedupe`; `utils.dedupe` imports `Article` from the partially initialized `sources.base`
  implication: root cause is deterministic import ordering, not missing retained content; moving the contract import below `Article` breaks the cycle without changing public APIs

- timestamp: 2026-07-10T00:20:00+08:00
  checked: fresh-interpreter regression, relevant pytest tests, Ruff, full pytest suite, and the workflow's `skip_generate=true` branch
  found: 76 tests passed, Ruff passed, and `python main.py build` completed successfully; the workflow invokes the same CLI command for retained-content preview
  implication: the fix is stable across the direct import path and the full test suite; generated same-day files are validation artifacts and must not be included

## Resolution

root_cause: `sources.base` imports `utils.run_contracts` before defining `Article`. Python initializes the `utils` package before its submodule, so `utils.__init__` imports `utils.dedupe`, which re-enters `sources.base` and cannot find `Article` yet.
fix: Defer the `RunDeadlineExceeded` imports inside the two methods that raise it, so importing `sources.base` defines `Article` without initializing the `utils` package. Added a fresh-interpreter regression test for the public import paths.
verification: Fresh interpreter import regression passed; 12 focused tests passed; Ruff passed; full pytest passed with 76 tests; `python main.py build` successfully built 2026-07-10.html, index.html, and archive.html from retained content.
files_changed: [sources/base.py, tests/test_import_order.py]
