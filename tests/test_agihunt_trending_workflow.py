from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_deploy_workflow_exposes_a_single_render_trending_gray_run() -> None:
    workflow = (REPO_ROOT / ".github" / "workflows" / "deploy.yml").read_text(
        encoding="utf-8"
    )

    assert "enable_agihunt_trending:" in workflow
    assert "runs-on: ubuntu-24.04" in workflow
    assert "SOURCE_ARGS+=(--agihunt-trending on)" in workflow
    assert "AGIHUNT_TRENDING_CHROME_BIN" in workflow
    assert "scripts/agihunt_trending_health.py" in workflow
    assert "agihunt-trending-health.json" in workflow
    assert "setup-chrome" not in workflow
