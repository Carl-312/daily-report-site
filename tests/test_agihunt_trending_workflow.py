from pathlib import Path

import yaml

from config import load_config


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_deploy_workflow_exposes_a_single_render_trending_gray_run() -> None:
    workflow = (REPO_ROOT / ".github" / "workflows" / "deploy.yml").read_text(
        encoding="utf-8"
    )

    assert "run_mode:" in workflow
    assert "type: choice" in workflow
    assert "- formal_gray" in workflow
    assert "runs-on: ubuntu-24.04" in workflow
    assert "SOURCE_ARGS+=(--agihunt-trending on)" in workflow
    assert "SOURCE_ARGS+=(--agihunt-trending off)" in workflow
    assert 'GITHUB_EVENT_NAME" = "workflow_dispatch' in workflow
    assert "AGIHUNT_TRENDING_CHROME_BIN" in workflow
    assert "scripts/agihunt_trending_health.py" in workflow
    assert "agihunt-trending-health.json" in workflow
    assert (
        "continue-on-error: ${{ github.event.schedule != '5 14 * * *' && "
        "inputs.run_mode != 'formal_gray' }}" in workflow
    )
    assert "AGI Hunt Trending will degrade without blocking other sources" in workflow
    assert "setup-chrome" not in workflow


def test_production_config_enables_only_the_rendered_trending_source() -> None:
    config = load_config(str(REPO_ROOT / "config.yaml"))

    assert config.sources["agihunt_trending"] is True
    assert config.sources["agihunt"] is False
    assert config.enrichment.enabled is True


def test_scheduled_workflow_injects_tavily_secret_without_manual_gate() -> None:
    workflow = (REPO_ROOT / ".github" / "workflows" / "deploy.yml").read_text(
        encoding="utf-8"
    )

    assert "TAVILY_API_KEY: ${{ secrets.TAVILY_API_KEY }}" in workflow
    assert "inputs.enable_tavily && secrets.TAVILY_API_KEY" not in workflow
    assert (
        "github.event.schedule == '5 14 * * *' || "
        "inputs.run_mode == 'formal_gray'" in workflow
    )
    assert "ENRICHMENT_ARGS=(--enrichment off)" in workflow


def test_daily_schedule_deploys_gray_pages_at_1405_asia_shanghai() -> None:
    workflow = (REPO_ROOT / ".github" / "workflows" / "deploy.yml").read_text(
        encoding="utf-8"
    )

    assert 'cron: "5 14 * * *"' in workflow
    assert 'timezone: "Asia/Shanghai"' in workflow
    assert (
        "github.event.schedule == '5 14 * * *' || "
        "inputs.run_mode == 'formal_gray'" in workflow
    )
    assert (
        "github.event.schedule == '36 0 * * *' || "
        "inputs.run_mode == 'production'" in workflow
    )


def test_formal_gray_pages_is_isolated_and_requires_full_live_inputs() -> None:
    workflow = (REPO_ROOT / ".github" / "workflows" / "deploy.yml").read_text(
        encoding="utf-8"
    )

    assert "deploy_gray_pages:" not in workflow
    assert "deploy-gray-pages:" in workflow
    assert "Formal gray mode invariant failed" in workflow
    assert "inputs.run_mode == 'formal_gray'" in workflow
    assert "needs.generate-and-deploy.outputs.publish != 'true'" in workflow
    assert "name: daily-report-preview-${{ github.run_id }}" in workflow
    assert "preview/agihunt-trending-health.json" in workflow
    assert 'health.get("healthy") is not True' in workflow
    assert "Carl-312/daily-report-site-gray" in workflow
    assert "git -C gray-site push origin HEAD:gh-pages" in workflow
    assert "environment:\n      name: gray-pages" in workflow


def test_manual_workflow_uses_one_safe_mode_selector() -> None:
    workflow = yaml.load(
        (REPO_ROOT / ".github" / "workflows" / "deploy.yml").read_text(
            encoding="utf-8"
        ),
        Loader=yaml.BaseLoader,
    )
    inputs = workflow["on"]["workflow_dispatch"]["inputs"]

    assert list(inputs) == ["run_mode"]
    assert inputs["run_mode"]["options"] == [
        "preview",
        "formal_gray",
        "agihunt_shadow",
        "rebuild_preview",
        "production",
    ]

    workflow_text = (REPO_ROOT / ".github" / "workflows" / "deploy.yml").read_text(
        encoding="utf-8"
    )
    assert (
        "AGIHUNT_API_KEY: ${{ inputs.run_mode == 'agihunt_shadow' && "
        "secrets.AGIHUNT_API_KEY || '' }}" in workflow_text
    )
