from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

try:
    import tomllib
except ImportError:
    import tomli as tomllib


class MCPServer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,25}$")
    command: str
    args: list[str] = []
    env_names: list[str] = []


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    api: Literal["responses", "chat", "demo"] = "responses"
    model: str = ""
    base_url: str | None = None
    api_key_env: str = "OPENAI_API_KEY"
    max_steps: int = Field(default=16, ge=1, le=100)
    max_output_tokens: int = Field(default=4096, ge=128, le=32768)
    max_turn_tokens: int = Field(default=60000, ge=1024)
    max_turn_seconds: int = Field(default=600, ge=1, le=7200)
    context_chars: int = Field(default=80000, ge=4000, le=1000000)
    tool_result_chars: int = Field(default=10000, ge=1000, le=50000)
    tool_timeout: int = Field(default=90, ge=1, le=600)
    permission: Literal["read-only", "ask", "workspace-write"] = "ask"
    allow_network: bool = True
    execution: Literal["disabled", "docker", "local"] = "disabled"
    docker_image: str = "python:3.11-slim"
    docker_cpus: float = Field(default=1, ge=0.1, le=64, allow_inf_nan=False)
    docker_memory_mb: int = Field(default=1024, ge=128, le=262144)
    docker_gpus: str | None = Field(default=None, pattern=r"^(all|[0-9]+(,[0-9]+)*)$")
    max_job_seconds: int = Field(default=600, ge=1, le=604800)
    max_job_output_bytes: int = Field(default=2_000_000, ge=1024, le=50_000_000)
    embedding_model: str | None = None
    ocr_tessdata_path: str | None = None
    input_price_per_million: float | None = Field(default=None, ge=0)
    output_price_per_million: float | None = Field(default=None, ge=0)
    max_turn_cost: float | None = Field(default=None, gt=0)
    mcp: list[MCPServer] = []

    @classmethod
    def load(cls, path: Path | None = None) -> Settings:
        raw = {}
        if path is not None:
            with path.open("rb") as f:
                raw = tomllib.load(f)
        for key, env in [
            ("model", "RESEARCH_MODEL"),
            ("base_url", "OPENAI_BASE_URL"),
            ("api", "RESEARCH_API"),
            ("ocr_tessdata_path", "RESEARCH_OCR_TESSDATA"),
        ]:
            if os.environ.get(env):
                raw[key] = os.environ[env]
        result = cls.model_validate(raw)
        if result.max_turn_cost is not None and (
            result.input_price_per_million is None or result.output_price_per_million is None
        ):
            raise ValueError("max_turn_cost requires both token prices; unknown cost is not zero")
        return result
