"""
Apply controlled Tavily gray experiment overrides for the isolated CI workflow.

The mappings here intentionally expose only named experiments. They do not accept
arbitrary domains, queries, budgets, or YAML snippets from workflow_dispatch.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import yaml

BASELINE_PROFILE = "gray_3_lenient_3day_diagnostic"
WIDE_FILTER_PROFILE = "wide_filter_ai_refill"
WIDE_FILTER_EXPERIMENT = "wide-filter-ai-refill"
EXPERIMENT_NAMES = (
    "baseline",
    "budget_9",
    "domain_priority_media",
    WIDE_FILTER_EXPERIMENT,
)

BASELINE_PRIORITY_DOMAINS = [
    "reuters.com",
    "arstechnica.com",
    "techcrunch.com",
]
DOMAIN_PRIORITY_MEDIA_DOMAINS = [
    "reuters.com",
    "arstechnica.com",
]
BASELINE_SECONDARY_DOMAINS = [
    "thenextweb.com",
    "venturebeat.com",
]
WIDE_PRIORITY_TECH_DOMAINS = [
    "arstechnica.com",
    "thenextweb.com",
    "venturebeat.com",
    "engadget.com",
    "wired.com",
    "reuters.com",
    "bloomberg.com",
    "cnbc.com",
]
WIDE_SOURCE_OVERLAP_DOMAINS = [
    "techcrunch.com",
    "www.theverge.com",
    "theverge.com",
]
WIDE_SECONDARY_BUSINESS_DOMAINS = [
    "reuters.com",
    "bloomberg.com",
    "cnbc.com",
]
WIDE_REFILL_QUERIES = [
    "today AI model product launch developer tools OpenAI Anthropic Google DeepMind Meta Mistral coding agents",
    "today AI companies startup funding acquisition merger regulation OpenAI Anthropic Microsoft Nvidia",
    "today AI chips cloud cybersecurity robotics data center semiconductors autonomous systems",
]
WIDE_REFILL_QUERY_TOPICS = [
    "ai_models_products_developer_tools",
    "ai_companies_funding_mna_regulation",
    "ai_adjacent_chips_cloud_security_robotics",
]


def baseline_enrichment(max_total_calls: int = 7) -> dict[str, Any]:
    return {
        "strict_hours": 24,
        "max_total_calls": max_total_calls,
        "refill_max_results": 8,
        "refill_search_window_hours": 72,
        "lenient_refill_diagnostics_enabled": True,
        "lenient_refill_window_hours": 72,
        "trusted_domains": {
            "priority_refill_media_whitelist": list(BASELINE_PRIORITY_DOMAINS),
            "secondary_refill_candidate_domains": list(BASELINE_SECONDARY_DOMAINS),
        },
    }


def build_experiment_overrides(
    experiment: str,
    enrichment_defaults: dict[str, Any],
) -> dict[str, Any]:
    if experiment not in EXPERIMENT_NAMES:
        allowed = ", ".join(EXPERIMENT_NAMES)
        raise ValueError(
            f"Unsupported Tavily gray experiment: {experiment}. Allowed: {allowed}"
        )

    enrichment = baseline_enrichment()
    changed_variable = "none"
    exact_override: dict[str, Any] = {
        "runtime_profile": BASELINE_PROFILE,
        "max_total_calls": 7,
        "priority_refill_media_whitelist": list(BASELINE_PRIORITY_DOMAINS),
        "secondary_refill_candidate_domains": list(BASELINE_SECONDARY_DOMAINS),
    }
    reason = (
        "Run the existing Gray 3 lenient 3-day diagnostic baseline without changing "
        "production defaults."
    )

    if experiment == "budget_9":
        enrichment = baseline_enrichment(max_total_calls=9)
        changed_variable = "max_total_calls"
        exact_override = {"max_total_calls": {"from": 7, "to": 9}}
        reason = (
            "Test only whether raising the Tavily gray total-call budget closes the "
            "strict final-count gap without changing domains, query, fallback, or "
            "production defaults."
        )
    elif experiment == "domain_priority_media":
        enrichment = baseline_enrichment(max_total_calls=7)
        enrichment["trusted_domains"]["priority_refill_media_whitelist"] = list(
            DOMAIN_PRIORITY_MEDIA_DOMAINS
        )
        changed_variable = "trusted_domains.priority_refill_media_whitelist"
        exact_override = {
            "trusted_domains.priority_refill_media_whitelist": {
                "from": list(BASELINE_PRIORITY_DOMAINS),
                "to": list(DOMAIN_PRIORITY_MEDIA_DOMAINS),
            }
        }
        reason = (
            "Test only whether removing TechCrunch from priority refill media changes "
            "priority refill quality while keeping the baseline call budget."
        )
    elif experiment == WIDE_FILTER_EXPERIMENT:
        enrichment = {
            "boundary_mode": "tech_news",
            "preserve_source_on_verify_failure": True,
            "strict_hours": 24,
            "max_total_calls": 10,
            "max_verify_calls": 4,
            "max_refill_rounds": 3,
            "min_refill_rounds": 3,
            "refill_to_max_articles": True,
            "refill_max_results": 12,
            "refill_search_window_hours": 24,
            "soft_date_window_hours": 72,
            "allow_soft_date_refill": False,
            "verify_search_depth": "basic",
            "refill_search_depth": "advanced",
            "lenient_refill_diagnostics_enabled": True,
            "lenient_refill_window_hours": 72,
            "refill_queries": list(WIDE_REFILL_QUERIES),
            "refill_query_topics": list(WIDE_REFILL_QUERY_TOPICS),
            "accept_refill_topic_buckets": [
                "ai_core",
                "tech_core",
                "tech_business",
                "tech_adjacent",
                "generic_or_low_signal",
            ],
            "trusted_domains": {
                "source_overlap_domains": list(WIDE_SOURCE_OVERLAP_DOMAINS),
                "priority_tech_media_domains": list(WIDE_PRIORITY_TECH_DOMAINS),
                "secondary_business_tech_domains": list(WIDE_SECONDARY_BUSINESS_DOMAINS),
                "priority_refill_media_whitelist": list(WIDE_PRIORITY_TECH_DOMAINS),
                "secondary_refill_candidate_domains": list(
                    WIDE_SECONDARY_BUSINESS_DOMAINS
                ),
            },
        }
        changed_variable = WIDE_FILTER_PROFILE
        exact_override = {
            "runtime_profile": WIDE_FILTER_PROFILE,
            "source_policy": "preserve_source_tech_news_with_date_confidence",
            "refill_rounds": {
                "min_refill_rounds": 3,
                "max_refill_rounds": 3,
                "query_topics": list(WIDE_REFILL_QUERY_TOPICS),
            },
            "date_policy": {
                "strict_hours": 24,
                "allow_soft_date_refill": False,
                "lenient_diagnostics_hours": 72,
            },
        }
        reason = (
            "Run one isolated wide-filter gray experiment that preserves source tech "
            "news, performs at least three Tavily news refill rounds, accepts only "
            "strict 24-hour refill candidates, and leaves production defaults unchanged."
        )

    return {
        "experiment": experiment,
        "changed_variable": changed_variable,
        "exact_override": exact_override,
        "reason": reason,
        "enrichment": enrichment,
        "unchanged_safety_defaults": {
            "enabled": enrichment_defaults.get("enabled", False),
            "enable_official_fallback": enrichment_defaults.get(
                "enable_official_fallback", False
            ),
            "priority_refill_query": enrichment_defaults.get("priority_refill_query"),
            "official_fallback_query": enrichment_defaults.get(
                "official_fallback_query"
            ),
        },
    }


def apply_overrides_to_config(
    cfg: dict[str, Any],
    overrides: dict[str, Any],
) -> dict[str, Any]:
    enrichment = cfg.setdefault("enrichment", {})
    trusted_domains = enrichment.setdefault("trusted_domains", {})

    for key, value in overrides["enrichment"].items():
        if key == "trusted_domains":
            for domain_key, domains in value.items():
                trusted_domains[domain_key] = list(domains)
        else:
            enrichment[key] = value

    return cfg


def apply_gray_experiment(
    config_path: Path,
    gray_dir: Path,
    experiment: str,
) -> dict[str, Any]:
    cfg = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    enrichment_defaults = cfg.setdefault("enrichment", {})
    overrides = build_experiment_overrides(experiment, enrichment_defaults)
    apply_overrides_to_config(cfg, overrides)

    config_path.write_text(
        yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    overrides_path = gray_dir / "logs" / "gray-experiment-overrides.json"
    overrides_path.parent.mkdir(parents=True, exist_ok=True)
    overrides_path.write_text(
        json.dumps(overrides, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    return overrides


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Apply a controlled Tavily gray experiment override."
    )
    parser.add_argument(
        "--experiment",
        choices=EXPERIMENT_NAMES,
        default="baseline",
        help="Controlled experiment name selected by workflow_dispatch.",
    )
    parser.add_argument(
        "--config",
        default="config.yaml",
        help="Path to config.yaml.",
    )
    parser.add_argument(
        "--gray-dir",
        required=True,
        help="Gray artifact directory where logs/gray-experiment-overrides.json is written.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    overrides = apply_gray_experiment(
        Path(args.config),
        Path(args.gray_dir),
        args.experiment,
    )
    print(
        "Applied Tavily gray experiment "
        f"{overrides['experiment']} ({overrides['changed_variable']})."
    )


if __name__ == "__main__":
    main()
