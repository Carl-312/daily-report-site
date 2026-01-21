"""
Configuration Management using Pydantic
Loads settings from .env and config.yaml
"""
from __future__ import annotations
import os
from pathlib import Path
from typing import Dict, Any
from pydantic import BaseModel, Field
from dotenv import load_dotenv
import yaml

# Load .env file
load_dotenv(encoding='utf-8', override=True)


class Settings(BaseModel):
    """Application settings with validation"""
    
    # ModelScope API
    api_key: str = Field(default="", description="ModelScope API Key")
    api_base_url: str = Field(
        default="https://api-inference.modelscope.cn/v1",
        description="API Base URL"
    )
    model: str = Field(default="ZhipuAI/GLM-4.7", description="Model ID")
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
    docs_dir: str = Field(default="docs")
    
    # Syft (optional)
    syft_web_app_url: str = Field(default="")
    syft_secret_key: str = Field(default="")
    
    class Config:
        extra = "ignore"


def load_config(config_path: str = "config.yaml") -> Settings:
    """Load configuration from environment and YAML file"""
    
    # Load from environment
    env_settings = {
        "api_key": os.getenv("MODELSCOPE_API_KEY", ""),
        "api_base_url": os.getenv("MODELSCOPE_BASE_URL", "https://api-inference.modelscope.cn/v1"),
        "model": os.getenv("MODELSCOPE_MODEL", "ZhipuAI/GLM-4.7"),
        "max_output": int(os.getenv("MODELSCOPE_MAX_OUTPUT", "2000")),
        "timezone": os.getenv("TIMEZONE", "Asia/Shanghai"),
        "syft_web_app_url": os.getenv("SYFT_WEB_APP_URL", ""),
        "syft_secret_key": os.getenv("SYFT_SECRET_KEY", ""),
    }
    
    # Load from YAML if exists
    yaml_settings = {}
    if Path(config_path).exists():
        with open(config_path, 'r', encoding='utf-8') as f:
            cfg = yaml.safe_load(f) or {}
            yaml_settings = {
                "sources": cfg.get("sources", {}),
                "max_articles": cfg.get("limits", {}).get("max_articles", 14),
                "title_max": cfg.get("summarize", {}).get("compress", {}).get("title_max", 150),
                "desc_max": cfg.get("summarize", {}).get("compress", {}).get("desc_max", 300),
                "prompt_path": cfg.get("summarize", {}).get("prompt_path", "prompts/daily.md"),
                "data_dir": cfg.get("output", {}).get("json_dir", "data"),
                "content_dir": cfg.get("output", {}).get("md_dir", "content"),
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
