"""
Configuration Management using Pydantic
Loads settings from .env and config.yaml
"""

from __future__ import annotations
import os
from pathlib import Path
import re
from typing import Dict, List, Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from dotenv import load_dotenv
import yaml

# Load local defaults without overriding explicit process/Actions settings.
load_dotenv(encoding="utf-8", override=False)

DEFAULT_MODELSCOPE_MODEL = "Qwen/Qwen3.5-35B-A3B"
DEFAULT_MODELSCOPE_SECONDARY_MODEL = ""
DEFAULT_SILICONFLOW_MODEL = "Pro/moonshotai/Kimi-K2.6"


_AGIHUNT_CHANNEL_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


class AgihuntSettings(BaseModel):
    """Non-secret settings for the bounded AGIHunt Agent API client."""

    model_config = ConfigDict(extra="forbid")

    api_base_url: str = Field(default="https://agihunt.info/agent/v1")
    skill_version: str = Field(default="1.2.2")
    cache_ttl_seconds: int = Field(default=600, ge=60, le=3600)
    request_budget: int = Field(default=5, ge=1, le=5)
    timeout_seconds: float = Field(default=15, gt=0, le=30)
    retry_wait_cap_seconds: float = Field(default=30, ge=0, le=30)
    use_environment_proxy: bool = Field(default=True)
    include_report: bool = Field(default=True)
    core_channels: List[str] = Field(
        default_factory=lambda: ["models", "research", "coding-agents"]
    )
    supplemental_channel: str = Field(default="products")
    # This is intentionally separate from the global daily-source limit. The
    # Agent API returns a top-100 list per channel, so selection is bounded
    # locally without increasing request volume.
    max_articles: int = Field(default=20, ge=1, le=100)
    per_channel_limit: int = Field(default=6, ge=1, le=20)
    core_channel_quota: int = Field(default=3, ge=1, le=14)
    supplemental_quota: int = Field(default=3, ge=1, le=14)
    max_age_hours: int = Field(default=30, ge=1, le=72)
    future_tolerance_minutes: int = Field(default=5, ge=0, le=60)
    entity_limit: int = Field(default=2, ge=1, le=5)
    entity_keywords: List[str] = Field(
        default_factory=lambda: [
            "openai",
            "anthropic",
            "google",
            "meta",
            "microsoft",
            "xai",
            "deepseek",
            "nvidia",
        ]
    )
    source_priority: int = Field(default=3, ge=0, le=10)

    @field_validator("core_channels")
    @classmethod
    def validate_core_channels(cls, channels: List[str]) -> List[str]:
        if not channels:
            raise ValueError("agihunt core_channels must not be empty")
        normalized = [cls._validate_channel_slug(channel) for channel in channels]
        if len(normalized) != len(set(normalized)):
            raise ValueError("agihunt core_channels must be unique")
        return normalized

    @field_validator("supplemental_channel")
    @classmethod
    def validate_supplemental_channel(cls, channel: str) -> str:
        return cls._validate_channel_slug(channel)

    @field_validator("entity_keywords")
    @classmethod
    def validate_entity_keywords(cls, values: List[str]) -> List[str]:
        normalized = [value.strip().lower() for value in values if value.strip()]
        if len(normalized) != len(set(normalized)):
            raise ValueError("agihunt entity_keywords must be unique")
        return normalized

    @model_validator(mode="after")
    def validate_request_plan(self) -> "AgihuntSettings":
        if not self.api_base_url.startswith("https://"):
            raise ValueError("agihunt api_base_url must use https")
        if self.supplemental_channel in self.core_channels:
            raise ValueError(
                "agihunt supplemental_channel must differ from core_channels"
            )
        planned_requests = len(self.core_channels) + 1 + int(self.include_report)
        if planned_requests > self.request_budget:
            raise ValueError(
                "agihunt request_budget is lower than the configured endpoint plan"
            )
        candidate_capacity = (len(self.core_channels) + 1) * self.per_channel_limit
        if self.max_articles > candidate_capacity:
            raise ValueError(
                "agihunt max_articles exceeds configured channel candidate capacity"
            )
        return self

    @staticmethod
    def _validate_channel_slug(value: str) -> str:
        normalized = value.strip().lower()
        if not _AGIHUNT_CHANNEL_SLUG.fullmatch(normalized):
            raise ValueError("agihunt channel slug is invalid")
        return normalized


class AgihuntTrendingSettings(BaseModel):
    """Deterministic rendered-page settings for AGI Hunt Trending."""

    model_config = ConfigDict(extra="forbid")

    page_url: str = Field(default="https://agihunt.info/")
    window: Literal["1d"] = "1d"
    language: Literal["zh-CN", "en"] = "zh-CN"
    timezone: str = Field(default="Asia/Shanghai")
    day_offset: int = Field(default=0, ge=-1, le=0)
    expected_articles: int = Field(default=15, ge=10, le=20)
    minimum_articles: int = Field(default=10, ge=1, le=20)
    max_articles: int = Field(default=15, ge=1, le=20)
    render_timeout_seconds: float = Field(default=30, gt=0, le=60)
    virtual_time_budget_ms: int = Field(default=12000, ge=1000, le=30000)
    max_dom_bytes: int = Field(default=2_000_000, ge=100_000, le=10_000_000)
    chrome_binary: str = Field(default="")
    source_priority: int = Field(default=3, ge=1, le=9)

    @field_validator("page_url")
    @classmethod
    def validate_page_url(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized.startswith("https://"):
            raise ValueError("agihunt_trending page_url must use https")
        return normalized

    @model_validator(mode="after")
    def validate_article_contract(self) -> "AgihuntTrendingSettings":
        if self.minimum_articles > self.expected_articles:
            raise ValueError(
                "agihunt_trending minimum_articles exceeds expected_articles"
            )
        if self.max_articles > self.expected_articles:
            raise ValueError("agihunt_trending max_articles exceeds expected_articles")
        return self


class Settings(BaseModel):
    """Application settings with validation"""

    # Primary provider: ModelScope API
    api_key: str = Field(default="", description="ModelScope API Key")
    api_base_url: str = Field(
        default="https://api-inference.modelscope.cn/v1",
        description="ModelScope API Base URL",
    )
    model: str = Field(
        default=DEFAULT_MODELSCOPE_MODEL, description="Primary ModelScope model ID"
    )
    modelscope_secondary_model: str = Field(
        default=DEFAULT_MODELSCOPE_SECONDARY_MODEL,
        description="Secondary ModelScope model ID",
    )

    # Fallback provider: SiliconFlow (OpenAI-compatible)
    fallback_api_key: str = Field(default="", description="SiliconFlow API Key")
    fallback_api_base_url: str = Field(
        default="https://api.siliconflow.cn/v1", description="SiliconFlow API Base URL"
    )
    fallback_model: str = Field(
        default=DEFAULT_SILICONFLOW_MODEL, description="SiliconFlow model ID"
    )

    max_output: int = Field(default=2000, description="Max output tokens")

    # Timezone
    timezone: str = Field(default="Asia/Shanghai")
    run_deadline_minutes: float = Field(default=20, gt=0)

    # Sources config
    sources: Dict[str, bool] = Field(default_factory=dict)

    # Limits
    max_articles: int = Field(default=14)
    max_summary_items: int = Field(default=10, gt=0)

    # Compress settings
    title_max: int = Field(default=150)
    desc_max: int = Field(default=300)

    # Paths
    prompt_path: str = Field(default="prompts/daily.md")
    data_dir: str = Field(default="data")
    content_dir: str = Field(default="content")
    site_dir: str = Field(default="dist")
    publication_root: str = Field(default=".publication")
    runs_dir: str = Field(default=".runs")

    # Syft (optional)
    syft_web_app_url: str = Field(default="")
    syft_secret_key: str = Field(default="")

    # AGIHunt (optional; key is environment-only)
    agihunt_api_key: str = Field(default="", description="AGIHunt API Key")
    agihunt: AgihuntSettings = Field(default_factory=AgihuntSettings)
    agihunt_trending: AgihuntTrendingSettings = Field(
        default_factory=AgihuntTrendingSettings
    )

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
        ]
    )


class EnrichmentSettings(BaseModel):
    """Post-fetch Tavily enrichment settings"""

    enabled: bool = Field(default=False)
    trust_env: bool = Field(default=True)
    min_articles: int = Field(default=10)
    strict_hours: int = Field(default=24)
    max_total_calls: int = Field(default=7)
    max_verify_calls: int = Field(default=6)
    max_refill_rounds: int = Field(default=1)
    refill_max_results: int = Field(default=8)
    refill_search_window_hours: int = Field(default=24)
    verify_search_depth: str = Field(default="basic")
    enable_fuzzy_second_pass: bool = Field(default=False)
    enable_official_fallback: bool = Field(default=False)
    lenient_refill_diagnostics_enabled: bool = Field(default=False)
    lenient_refill_window_hours: int = Field(default=72)
    priority_refill_query: str = Field(
        default="OpenAI Anthropic AI model launch startup funding developer tools"
    )
    priority_refill_queries: List[str] = Field(default_factory=list)
    official_fallback_query: str = Field(
        default="OpenAI Anthropic AI model launch startup funding developer tools"
    )
    official_fallback_queries: List[str] = Field(default_factory=list)
    trusted_domains: EnrichmentTrustedDomains = Field(
        default_factory=EnrichmentTrustedDomains
    )

    @field_validator("priority_refill_queries", "official_fallback_queries")
    @classmethod
    def validate_query_packs(cls, values: List[str]) -> List[str]:
        normalized = [value.strip() for value in values if value.strip()]
        if len(normalized) != len(set(normalized)):
            raise ValueError("enrichment query packs must be unique")
        return normalized


Settings.model_rebuild()


def load_config(config_path: str = "config.yaml") -> Settings:
    """Load configuration from environment and YAML file"""

    # Load from environment
    env_settings = {
        "api_key": os.getenv("MODELSCOPE_API_KEY", ""),
        "api_base_url": os.getenv(
            "MODELSCOPE_BASE_URL", "https://api-inference.modelscope.cn/v1"
        ),
        "model": os.getenv("MODELSCOPE_MODEL", DEFAULT_MODELSCOPE_MODEL),
        "modelscope_secondary_model": os.getenv(
            "MODELSCOPE_SECONDARY_MODEL", DEFAULT_MODELSCOPE_SECONDARY_MODEL
        ),
        "fallback_api_key": os.getenv("SILICONFLOW_API_KEY", ""),
        "fallback_api_base_url": os.getenv(
            "SILICONFLOW_BASE_URL", "https://api.siliconflow.cn/v1"
        ),
        "fallback_model": os.getenv("SILICONFLOW_MODEL", DEFAULT_SILICONFLOW_MODEL),
        "max_output": int(os.getenv("MODELSCOPE_MAX_OUTPUT", "2000")),
        "timezone": os.getenv("TIMEZONE", "Asia/Shanghai"),
        "run_deadline_minutes": float(os.getenv("RUN_DEADLINE_MINUTES", "20")),
        "syft_web_app_url": os.getenv("SYFT_WEB_APP_URL", ""),
        "syft_secret_key": os.getenv("SYFT_SECRET_KEY", ""),
        "agihunt_api_key": os.getenv("AGIHUNT_API_KEY", ""),
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
                "max_summary_items": cfg.get("limits", {}).get("max_summary_items", 10),
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
                "publication_root": output_cfg.get("publication_root", ".publication"),
                "run_deadline_minutes": cfg.get("run", {}).get("deadline_minutes", 20),
                "agihunt": cfg.get("agihunt", {}),
                "agihunt_trending": cfg.get("agihunt_trending", {}),
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
