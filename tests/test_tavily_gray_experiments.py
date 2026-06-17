from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from scripts.tavily_gray_experiments import (
    BASELINE_PRIORITY_DOMAINS,
    BASELINE_SECONDARY_DOMAINS,
    DOMAIN_PRIORITY_MEDIA_DOMAINS,
    EXPERIMENT_NAMES,
    apply_gray_experiment,
    build_experiment_overrides,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "tavily-gray.yml"

BASE_ENRICHMENT_DEFAULTS = {
    "enabled": False,
    "trust_env": True,
    "min_articles": 10,
    "strict_hours": 24,
    "max_total_calls": 7,
    "max_verify_calls": 6,
    "max_refill_rounds": 1,
    "refill_max_results": 8,
    "verify_search_depth": "basic",
    "enable_fuzzy_second_pass": False,
    "enable_official_fallback": False,
    "priority_refill_query": "OpenAI Anthropic AI model launch startup funding developer tools",
    "official_fallback_query": "OpenAI Anthropic AI model launch startup funding developer tools",
    "trusted_domains": {
        "priority_refill_media_whitelist": [
            "thenextweb.com",
            "venturebeat.com",
        ],
        "secondary_refill_candidate_domains": [
            "reuters.com",
            "arstechnica.com",
        ],
        "official_fallback_domains": [
            "openai.com",
            "anthropic.com",
        ],
    },
}


def workflow_step(workflow: dict[str, Any], name: str) -> dict[str, Any]:
    return next(
        step
        for step in workflow["jobs"]["tavily-gray"]["steps"]
        if step["name"] == name
    )


def changed_paths(left: Any, right: Any, prefix: str = "") -> list[str]:
    if isinstance(left, dict) and isinstance(right, dict):
        paths: list[str] = []
        for key in sorted(set(left) | set(right)):
            child_prefix = f"{prefix}.{key}" if prefix else str(key)
            paths.extend(changed_paths(left.get(key), right.get(key), child_prefix))
        return paths
    if left != right:
        return [prefix]
    return []


def test_workflow_dispatch_exposes_only_controlled_experiment_choices() -> None:
    workflow = yaml.load(
        WORKFLOW_PATH.read_text(encoding="utf-8"), Loader=yaml.BaseLoader
    )

    dispatch_inputs = workflow["on"]["workflow_dispatch"]["inputs"]
    assert list(dispatch_inputs) == ["experiment"]

    experiment = dispatch_inputs["experiment"]
    assert experiment["type"] == "choice"
    assert experiment["default"] == "baseline"
    assert experiment["options"] == list(EXPERIMENT_NAMES)

    apply_step = workflow_step(workflow, "Apply gray experiment overrides")
    assert (
        apply_step["env"]["GRAY_EXPERIMENT"]
        == "${{ github.event_name == 'workflow_dispatch' && inputs.experiment || 'baseline' }}"
    )
    assert "schedule" in workflow["on"]


def test_scheduled_gray_report_publish_is_main_only_and_retained() -> None:
    workflow = yaml.load(
        WORKFLOW_PATH.read_text(encoding="utf-8"), Loader=yaml.BaseLoader
    )

    assert workflow["env"]["RETENTION_DAYS"] == "7"
    assert workflow["permissions"]["contents"] == "write"

    checkout_step = workflow_step(workflow, "Checkout repository")
    assert checkout_step["with"]["fetch-depth"] == "0"

    prune_step = workflow_step(workflow, "Prune retained final report window")
    commit_step = workflow_step(workflow, "Commit and push gray final report")
    publish_condition = "github.event_name == 'schedule' && github.ref == 'refs/heads/main'"

    assert prune_step["if"] == publish_condition
    assert prune_step["run"] == (
        'python scripts/manage_retention.py prune --keep-days "$RETENTION_DAYS"'
    )
    assert commit_step["if"] == publish_condition
    assert "git add -A content/ data/" in commit_step["run"]
    assert "Tavily gray final report:" in commit_step["run"]


def test_experiment_mapping_changes_only_the_declared_variable() -> None:
    baseline = build_experiment_overrides("baseline", BASE_ENRICHMENT_DEFAULTS)
    budget = build_experiment_overrides("budget_9", BASE_ENRICHMENT_DEFAULTS)
    domain = build_experiment_overrides(
        "domain_priority_media",
        BASE_ENRICHMENT_DEFAULTS,
    )

    assert baseline["experiment"] == "baseline"
    assert baseline["changed_variable"] == "none"
    assert baseline["enrichment"]["max_total_calls"] == 7
    assert baseline["enrichment"]["trusted_domains"] == {
        "priority_refill_media_whitelist": BASELINE_PRIORITY_DOMAINS,
        "secondary_refill_candidate_domains": BASELINE_SECONDARY_DOMAINS,
    }

    assert budget["changed_variable"] == "max_total_calls"
    assert budget["exact_override"] == {"max_total_calls": {"from": 7, "to": 9}}
    assert changed_paths(baseline["enrichment"], budget["enrichment"]) == [
        "max_total_calls"
    ]

    assert (
        domain["changed_variable"] == "trusted_domains.priority_refill_media_whitelist"
    )
    assert domain["exact_override"] == {
        "trusted_domains.priority_refill_media_whitelist": {
            "from": BASELINE_PRIORITY_DOMAINS,
            "to": DOMAIN_PRIORITY_MEDIA_DOMAINS,
        }
    }
    assert changed_paths(baseline["enrichment"], domain["enrichment"]) == [
        "trusted_domains.priority_refill_media_whitelist"
    ]
    assert domain["enrichment"]["max_total_calls"] == 7


def test_apply_experiment_writes_artifact_and_preserves_safety_defaults(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "config.yaml"
    gray_dir = tmp_path / "gray" / "tavily" / "2026-06-17"
    config_path.write_text(
        yaml.safe_dump(
            {"enrichment": BASE_ENRICHMENT_DEFAULTS},
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    overrides = apply_gray_experiment(config_path, gray_dir, "budget_9")
    artifact_payload = json.loads(
        (gray_dir / "logs" / "gray-experiment-overrides.json").read_text(
            encoding="utf-8"
        )
    )
    cfg = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    enrichment = cfg["enrichment"]

    assert artifact_payload == overrides
    assert overrides["unchanged_safety_defaults"] == {
        "enabled": False,
        "enable_official_fallback": False,
        "priority_refill_query": BASE_ENRICHMENT_DEFAULTS["priority_refill_query"],
        "official_fallback_query": BASE_ENRICHMENT_DEFAULTS["official_fallback_query"],
    }
    assert enrichment["enabled"] is False
    assert enrichment["enable_official_fallback"] is False
    assert (
        enrichment["priority_refill_query"]
        == BASE_ENRICHMENT_DEFAULTS["priority_refill_query"]
    )
    assert (
        enrichment["official_fallback_query"]
        == BASE_ENRICHMENT_DEFAULTS["official_fallback_query"]
    )
    assert enrichment["max_total_calls"] == 9
    assert enrichment["trusted_domains"]["priority_refill_media_whitelist"] == (
        BASELINE_PRIORITY_DOMAINS
    )


def test_unknown_experiment_is_rejected() -> None:
    with pytest.raises(ValueError, match="Unsupported Tavily gray experiment"):
        build_experiment_overrides("custom_yaml", BASE_ENRICHMENT_DEFAULTS)
