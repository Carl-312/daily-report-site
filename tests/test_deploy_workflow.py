from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_non_blocking_publish_steps_cannot_block_pages_deployment() -> None:
    workflow = yaml.safe_load(
        (REPO_ROOT / ".github" / "workflows" / "deploy.yml").read_text(encoding="utf-8")
    )
    steps = workflow["jobs"]["generate-and-deploy"]["steps"]
    steps_by_name = {step["name"]: step for step in steps}

    non_blocking = {
        "Prepare release archive assets",
        "Ensure archive release exists",
        "Upload archive assets to GitHub Release",
        "Prune generated content outside retention window",
        "Commit and push retained generated content",
        "Upload run logs (optional)",
    }
    assert all(
        steps_by_name[name]["continue-on-error"] is True for name in non_blocking
    )

    for blocking in (
        "Generate daily report",
        "Resolve one public site edition",
        "Upload Pages artifact",
    ):
        assert "continue-on-error" not in steps_by_name[blocking]

    log_upload = steps_by_name["Upload run logs (optional)"]
    assert ".runs/**/summary-attempts.json" in log_upload["with"]["path"]
    assert log_upload["with"]["include-hidden-files"] is True
