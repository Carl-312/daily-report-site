---
quick_id: 260710-kxs
date: 2026-07-10
type: quick
wave: 1
depends_on: []
autonomous: true
files_modified:
  - content/2026-07-10.md
  - data/2026-07-10.json
  - .planning/quick/260710-kxs-2026-07-10-github-actions/260710-kxs-PLAN.md
must_haves:
  truths:
    - "灰度分支包含最新 origin/main 的提交，但只删除今天的生成 Markdown/JSON，不修改源代码或工作流。"
    - "PR #8 仍然是 OPEN 且 Draft，且 workflow_dispatch 在灰度分支以 skip_generate=true、publish=false、enable_tavily=false 成功完成。"
    - "预览 workflow 产出可下载的构建 artifact；由于未在 main 上且 publish=false，线上 GitHub Pages URL 不发生变化。"
  artifacts:
    - path: "content/2026-07-10.md"
      provides: "被删除的当天生成 Markdown，不应存在于灰度分支提交后的工作树"
    - path: "data/2026-07-10.json"
      provides: "被删除的当天生成 JSON，不应存在于灰度分支提交后的工作树"
    - path: ".github/workflows/deploy.yml"
      provides: "workflow_dispatch 的三个预览输入及非 main 不发布约束"
  key_links:
    - from: "gh workflow run deploy.yml --ref gsd/daily-news-reliability"
      to: "GitHub Actions run"
      via: "workflow_dispatch inputs"
    - from: "publish=false + github.ref != refs/heads/main"
      to: "Pages deployment"
      via: "publish-mode 输出为 false，deploy job 被跳过"
---

<objective>
在灰度分支 `gsd/daily-news-reliability` 上同步当天 `origin/main` 的生成文件历史，移除 `2026-07-10` 的生成 Markdown/JSON，并运行一次不发布的 GitHub Actions 预览重建。

Purpose: 为今天的生成文件和预览构建提供可核验的灰度状态，同时保持 Draft PR #8 和线上 GitHub Pages 版本不变。
Output: 灰度分支上的一次仅涉及生成文件删除的可追踪提交、成功的预览 workflow run、以及可下载的构建 artifact 验证记录。
</objective>

<execution_context>
@/home/carl/.codex/get-shit-done/workflows/quick.md
</execution_context>

<context>
@AGENTS.md
@.planning/PROJECT.md
@.planning/STATE.md
@.github/workflows/deploy.yml

当前已核实：
- 当前分支是 `gsd/daily-news-reliability`，PR #8 的 base 是 `main`、状态为 OPEN、`isDraft=true`。
- `origin/main` 的最新提交包含 `content/2026-07-10.md` 与 `data/2026-07-10.json`；灰度分支需先 `fetch` 再 merge。
- workflow 在 `github.ref != refs/heads/main` 或 `publish=false` 时只上传 preview artifact，不执行 Pages deploy，也不提交生成内容。
- 本计划只允许删除上述两个生成文件及必要的计划文件；禁止修改 Python、配置、workflow、测试、文档源文件，禁止合并 PR #8 到 main。
</context>

<tasks>

<task type="auto">
  <name>Task 1: 同步 origin/main 并删除当天生成文件</name>
  <files>content/2026-07-10.md, data/2026-07-10.json</files>
  <action>确认工作树干净且当前分支严格为 `gsd/daily-news-reliability`；执行 `git fetch origin main`，再执行 `git merge --no-edit origin/main` 以获得最新 main（不得使用 reset、checkout 覆盖用户改动或直接操作 main）。确认 merge 后仅定位到 `content/2026-07-10.md` 与 `data/2026-07-10.json` 两个当天生成文件，使用 `rm` 删除它们；若出现任何 Python、配置、workflow、测试或其他非目标文件变更，立即停止并报告，不要自动修复。提交时只暂存这两个删除，使用明确的 generated-artifact 提交信息，并推送到 `origin gsd/daily-news-reliability`，使后续 workflow_dispatch 使用远端最新灰度提交。</action>
  <verify>
    <automated>test "$(git branch --show-current)" = "gsd/daily-news-reliability" &amp;&amp; test -z "$(git diff --name-only origin/main...HEAD | rg -v '^(content/2026-07-10\\.md|data/2026-07-10\\.json)$' || true)" &amp;&amp; test ! -e content/2026-07-10.md &amp;&amp; test ! -e data/2026-07-10.json &amp;&amp; git status --short &amp;&amp; git ls-remote --heads origin gsd/daily-news-reliability</automated>
  </verify>
  <done>灰度远端已包含最新 `origin/main`，两个目标生成文件已删除并作为唯一应用内容变更推送；源文件、工作流、PR 合并状态均未改变。</done>
</task>

<task type="auto">
  <name>Task 2: 触发并等待仅预览 workflow_dispatch</name>
  <files>.github/workflows/deploy.yml</files>
  <action>在已推送的灰度分支上执行 `gh workflow run deploy.yml --ref gsd/daily-news-reliability -f skip_generate=true -f publish=false -f enable_tavily=false`。记录本次新建的 run ID（按 workflow、branch、event 和触发时间轮询，不能误认旧 run），随后用 `gh run watch &lt;run-id&gt; --interval 15 --exit-status` 等待完成；失败时使用 `gh run view &lt;run-id&gt; --log-failed` 收集失败步骤并停止，不重试成发布模式。确认 `Build site from retained content` 执行，`Generate daily report` 被跳过，`Resolve publish mode` 输出 preview，且 deploy job 未运行。</action>
  <verify>
    <automated>RUN_ID=$(gh run list --workflow deploy.yml --branch gsd/daily-news-reliability --event workflow_dispatch --limit 1 --json databaseId,status,conclusion --jq '.[0].databaseId') &amp;&amp; test -n "$RUN_ID" &amp;&amp; gh run view "$RUN_ID" --json status,conclusion,headBranch,event,jobs --jq 'select(.status == "completed" and .conclusion == "success" and .headBranch == "gsd/daily-news-reliability" and .event == "workflow_dispatch") | .jobs[] | [.name,.conclusion] | @tsv' | tee /tmp/260710-kxs-jobs.tsv &amp;&amp; rg -q '^generate-and-deploy[[:space:]]+success$' /tmp/260710-kxs-jobs.tsv &amp;&amp; ! rg -q '^deploy[[:space:]]+success$' /tmp/260710-kxs-jobs.tsv</automated>
  </verify>
  <done>本次 workflow_dispatch 在灰度分支以三个指定输入成功完成，仅预览构建运行；生成步骤未执行、Pages deploy 未执行，且 run ID 已记录。</done>
</task>

<task type="auto">
  <name>Task 3: 下载并核验预览产物、Draft 状态与线上不变性</name>
  <files>content/2026-07-10.md, data/2026-07-10.json</files>
  <action>使用 Task 2 的 run ID 执行 `gh run download &lt;run-id&gt; --name daily-report-preview-&lt;run-id&gt; --dir &lt;temporary-directory&gt;`，只写入临时目录，不覆盖仓库文件。核验 artifact 含可用的 `dist/` 构建产物，并检查 artifact 中不含 `content/2026-07-10.md` 和 `data/2026-07-10.json`；同时执行 `gh pr view 8 --json state,isDraft,headRefName,baseRefName`，必须保持 OPEN、Draft、head 为灰度分支、base 为 main。最后执行 `gh run view &lt;run-id&gt; --json jobs`，以 `publish-mode` 的 preview 输出、无成功 deploy job 为证据，明确该 run 不会改变线上 URL；不要访问或修改 main，也不要将 PR 转为 Ready/Merged。</action>
  <verify>
    <automated>RUN_ID=$(gh run list --workflow deploy.yml --branch gsd/daily-news-reliability --event workflow_dispatch --limit 1 --json databaseId --jq '.[0].databaseId') &amp;&amp; PREVIEW_DIR=$(mktemp -d) &amp;&amp; gh run download "$RUN_ID" --name "daily-report-preview-$RUN_ID" --dir "$PREVIEW_DIR" &amp;&amp; test -d "$PREVIEW_DIR/dist" &amp;&amp; ! test -e "$PREVIEW_DIR/content/2026-07-10.md" &amp;&amp; ! test -e "$PREVIEW_DIR/data/2026-07-10.json" &amp;&amp; gh pr view 8 --json state,isDraft,headRefName,baseRefName --jq 'select(.state == "OPEN" and .isDraft == true and .headRefName == "gsd/daily-news-reliability" and .baseRefName == "main")' &amp;&amp; gh run view "$RUN_ID" --log 2&gt;/dev/null | rg -q 'Preview mode: generated files will only be uploaded as workflow artifacts'</automated>
  </verify>
  <done>预览 artifact 可下载且包含构建产物、不含当天被删除文件；PR #8 仍为 Draft；有明确的 workflow 证据表明未执行发布，因此线上 URL 在合并 main 前保持不变。</done>
</task>

</tasks>

<verification>
1. `git status --short` 只反映计划文件或干净工作树，且 `git diff --name-only origin/main...HEAD` 不含源文件改动。
2. `gh run view <run-id>` 显示灰度分支的 workflow_dispatch 成功、preview artifact 上传成功、deploy job 未执行。
3. `gh pr view 8` 显示 `OPEN`、`isDraft=true`、head=`gsd/daily-news-reliability`、base=`main`。
4. 线上 URL 不变的结论基于 workflow 的发布条件：非 main 分支且 `publish=false`，`publish-mode=false`，Pages deployment job 不会启动；不得把预览 artifact URL 当作线上 URL。
</verification>

<success_criteria>
- 灰度分支已 merge 最新 `origin/main`，并只删除 `content/2026-07-10.md` 与 `data/2026-07-10.json`。
- 预览 workflow 使用 `skip_generate=true`、`publish=false`、`enable_tavily=false` 并成功完成。
- 预览 artifact 已验证，PR #8 保持 Draft，未发生 main 合并或线上 Pages URL 变化。
</success_criteria>

<output>
完成后在 `.planning/quick/260710-kxs-2026-07-10-github-actions/` 创建 quick task summary，记录 merge commit、删除提交、workflow run ID、artifact 名称、PR Draft 状态和“未发布、线上 URL 未变”的证据。
</output>
