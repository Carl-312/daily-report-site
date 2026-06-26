"""
Configuration Management using Pydantic
Loads settings from .env and config.yaml
"""

from __future__ import annotations
import os
from pathlib import Path
from typing import Dict, List
from pydantic import BaseModel, Field
from dotenv import load_dotenv
import yaml

# Load .env file
load_dotenv(encoding="utf-8", override=True)


class Settings(BaseModel):
    """Application settings with validation"""

    # Primary provider: ModelScope API
    api_key: str = Field(default="", description="ModelScope API Key")
    api_base_url: str = Field(
        default="https://api-inference.modelscope.cn/v1",
        description="ModelScope API Base URL",
    )
    model: str = Field(
        default="moonshotai/Kimi-K2.5", description="ModelScope model ID"
    )

    # Fallback provider: SiliconFlow (OpenAI-compatible)
    fallback_api_key: str = Field(default="", description="SiliconFlow API Key")
    fallback_api_base_url: str = Field(
        default="https://api.siliconflow.cn/v1", description="SiliconFlow API Base URL"
    )
    fallback_model: str = Field(
        default="Pro/zai-org/GLM-4.6", description="SiliconFlow model ID"
    )

    max_output: int = Field(default=2000, description="Max output tokens")

    # Timezone
    timezone: str = Field(default="Asia/Shanghai")

    # Sources config
    sources: Dict[str, bool] = Field(default_factory=dict)

    # Limits
    max_articles: int = Field(default=14)

    # Compress settings
    title_max: int = Field(default=150)
    desc_max: int = Field(default=300)

    # Paths
    prompt_path: str = Field(default="prompts/daily.md")
    data_dir: str = Field(default="data")
    content_dir: str = Field(default="content")
    site_dir: str = Field(default="dist")

    # Syft (optional)
    syft_web_app_url: str = Field(default="")
    syft_secret_key: str = Field(default="")

    # Tavily (optional)
    tavily_api_key: str = Field(default="", description="Tavily API Key")

    # Enrichment
    enrichment: "EnrichmentSettings" = Field(
        default_factory=lambda: EnrichmentSettings()
    )

    class Config:
        extra = "ignore"


class EnrichmentTrustedDomains(BaseModel):
    """Trusted domains for staged Tavily refill"""

    source_overlap_domains: List[str] = Field(
        default_factory=lambda: [
            "techcrunch.com",
            "www.theverge.com",
        ]
    )
    priority_tech_media_domains: List[str] = Field(
        default_factory=lambda: [
            "arstechnica.com",
            "thenextweb.com",
            "venturebeat.com",
            "engadget.com",
            "wired.com",
        ]
    )
    secondary_business_tech_domains: List[str] = Field(
        default_factory=lambda: [
            "reuters.com",
            "bloomberg.com",
            "cnbc.com",
        ]
    )
    priority_refill_media_whitelist: List[str] = Field(
        default_factory=lambda: [
            "thenextweb.com",
            "venturebeat.com",
        ]
    )
    secondary_refill_candidate_domains: List[str] = Field(
        default_factory=lambda: [
            "reuters.com",
            "arstechnica.com",
        ]
    )
    official_fallback_domains: List[str] = Field(
        default_factory=lambda: [
            "openai.com",
            "anthropic.com",
            "googleblog.com",
            "microsoft.com",
            "nvidia.com",
        ]
    )


class EnrichmentSettings(BaseModel):
    """Post-fetch Tavily enrichment settings"""

    enabled: bool = Field(default=False)
    trust_env: bool = Field(default=True)
    boundary_mode: str = Field(default="tech_news")
    preserve_source_on_verify_failure: bool = Field(default=True)
    min_articles: int = Field(default=10)
    max_articles_after_enrichment: int = Field(default=14)
    strict_hours: int = Field(default=24)
    max_total_calls: int = Field(default=10)
    max_verify_calls: int = Field(default=4)
    max_refill_rounds: int = Field(default=2)
    min_refill_rounds: int = Field(default=0)
    refill_to_max_articles: bool = Field(default=False)
    refill_max_results: int = Field(default=12)
    refill_search_window_hours: int = Field(default=48)
    soft_date_window_hours: int = Field(default=72)
    allow_soft_date_refill: bool = Field(default=True)
    verify_search_depth: str = Field(default="basic")
    refill_search_depth: str = Field(default="advanced")
    enable_fuzzy_second_pass: bool = Field(default=False)
    enable_official_fallback: bool = Field(default=False)
    lenient_refill_diagnostics_enabled: bool = Field(default=False)
    lenient_refill_window_hours: int = Field(default=72)
    refill_queries: List[str] = Field(
        default_factory=lambda: [
            "technology news software startups cybersecurity chips hardware apps cloud",
            "AI technology startups developer tools models robotics automation",
            "consumer technology platforms social apps security semiconductors funding",
        ]
    )
    refill_query_topics: List[str] = Field(default_factory=list)
    accept_refill_topic_buckets: List[str] = Field(
        default_factory=lambda: [
            "ai_core",
            "tech_core",
            "tech_business",
            "tech_adjacent",
        ]
    )
    priority_refill_query: str = Field(
        default="OpenAI Anthropic AI model launch startup funding developer tools"
    )
    official_fallback_query: str = Field(
        default="OpenAI Anthropic AI model launch startup funding developer tools"
    )
    trusted_domains: EnrichmentTrustedDomains = Field(
        default_factory=EnrichmentTrustedDomains
    )


Settings.model_rebuild()


def load_config(config_path: str = "config.yaml") -> Settings:
    """Load configuration from environment and YAML file"""

    # Load from environment
    env_settings = {
        "api_key": os.getenv("MODELSCOPE_API_KEY", ""),
        "api_base_url": os.getenv(
            "MODELSCOPE_BASE_URL", "https://api-inference.modelscope.cn/v1"
        ),
        "model": os.getenv("MODELSCOPE_MODEL", "moonshotai/Kimi-K2.5"),
        "fallback_api_key": os.getenv("SILICONFLOW_API_KEY", ""),
        "fallback_api_base_url": os.getenv(
            "SILICONFLOW_BASE_URL", "https://api.siliconflow.cn/v1"
        ),
        "fallback_model": os.getenv("SILICONFLOW_MODEL", "Pro/zai-org/GLM-4.6"),
        "max_output": int(os.getenv("MODELSCOPE_MAX_OUTPUT", "2000")),
        "timezone": os.getenv("TIMEZONE", "Asia/Shanghai"),
        "syft_web_app_url": os.getenv("SYFT_WEB_APP_URL", ""),
        "syft_secret_key": os.getenv("SYFT_SECRET_KEY", ""),
        "tavily_api_key": os.getenv("TAVILY_API_KEY", ""),
    }

    # Load from YAML if exists
    yaml_settings = {}
    if Path(config_path).exists():
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
            output_cfg = cfg.get("output", {})
            yaml_settings = {
                "sources": cfg.get("sources", {}),
                "max_articles": cfg.get("limits", {}).get("max_articles", 14),
                "title_max": cfg.get("summarize", {})
                .get("compress", {})
                .get("title_max", 150),
                "desc_max": cfg.get("summarize", {})
                .get("compress", {})
                .get("desc_max", 300),
                "prompt_path": cfg.get("summarize", {}).get(
                    "prompt_path", "prompts/daily.md"
                ),
                "data_dir": output_cfg.get("json_dir", "data"),
                "content_dir": output_cfg.get("md_dir", "content"),
                "site_dir": output_cfg.get(
                    "site_dir", output_cfg.get("docs_dir", "dist")
                ),
                "enrichment": cfg.get("enrichment", {}),
            }

    # Merge settings (env takes precedence for secrets)
    return Settings(**{**yaml_settings, **env_settings})


# Singleton instance
_config: Settings | None = None


def get_config() -> Settings:
    """Get or create config singleton"""
    global _config
    if _config is None:
        _config = load_config()
    return _config
