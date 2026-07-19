from pathlib import Path

import yaml

from config import load_config


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_tavily_gray_uses_fetch_checkpoint_and_diversified_36h_strategy() -> None:
    workflow_path = REPO_ROOT / ".github" / "workflows" / "tavily-gray.yml"
    workflow_text = workflow_path.read_text(encoding="utf-8")
    workflow = yaml.safe_load(workflow_text)
    steps = workflow["jobs"]["tavily-gray"]["steps"]
    override_script = next(
        step["run"]
        for step in steps
        if step["name"] == "Apply gray experiment overrides"
    )
    run_script = next(
        step["run"]
        for step in steps
        if step["name"] == "Run Tavily-on gray fetch checkpoint"
    )
    collect_script = next(
        step["run"] for step in steps if step["name"] == "Collect gray outputs"
    )

    assert '"strict_hours": 36' in override_script
    assert '"max_total_calls": 12' in override_script
    assert '"max_refill_rounds": 2' in override_script
    assert '"enable_official_fallback": True' in override_script
    assert '"priority_refill_queries"' in override_script
    assert '"secondary_refill_queries"' in override_script
    assert '"official_fallback_queries"' in override_script
    assert 'output["json_dir"]' in override_script
    assert 'output["runs_dir"]' in override_script
    assert 'cfg["data_dir"]' not in override_script
    assert "python3 main.py fetch --enrichment on" in run_script
    assert "checkpoint/data/$RUN_DATE.json" in collect_script
    assert "data/$RUN_DATE.json" not in collect_script.replace(
        "checkpoint/data/$RUN_DATE.json", ""
    )


def test_output_runs_dir_is_loaded_from_yaml(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "output": {
                    "json_dir": "gray/checkpoint/data",
                    "runs_dir": "gray/checkpoint/runs",
                    "publication_root": "gray/checkpoint/publication",
                }
            }
        ),
        encoding="utf-8",
    )

    cfg = load_config(str(config_path))

    assert cfg.data_dir == "gray/checkpoint/data"
    assert cfg.runs_dir == "gray/checkpoint/runs"
    assert cfg.publication_root == "gray/checkpoint/publication"
