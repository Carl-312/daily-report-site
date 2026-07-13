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

DEFAULT_MODELSCOPE_MODEL = "ZhipuAI/GLM-5.2"
DEFAULT_MODELSCOPE_SECONDARY_MODEL = "moonshotai/Kimi-K2.7-Code"
DEFAULT_SILICONFLOW_MODEL = "Pro/moonshotai/Kimi-K2.6"


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
                "publication_root": output_cfg.get("publication_root", ".publication"),
                "run_deadline_minutes": cfg.get("run", {}).get("deadline_minutes", 20),
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
