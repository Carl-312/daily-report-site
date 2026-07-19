from pathlib import Path

from config import load_config


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_deploy_workflow_exposes_a_single_render_trending_gray_run() -> None:
    workflow = (REPO_ROOT / ".github" / "workflows" / "deploy.yml").read_text(
        encoding="utf-8"
    )

    assert "enable_agihunt_trending:" in workflow
    assert "runs-on: ubuntu-24.04" in workflow
    assert "SOURCE_ARGS+=(--agihunt-trending on)" in workflow
    assert "SOURCE_ARGS+=(--agihunt-trending off)" in workflow
    assert 'GITHUB_EVENT_NAME" = "workflow_dispatch' in workflow
    assert "AGIHUNT_TRENDING_CHROME_BIN" in workflow
    assert "scripts/agihunt_trending_health.py" in workflow
    assert "agihunt-trending-health.json" in workflow
    assert "continue-on-error: true" in workflow
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
