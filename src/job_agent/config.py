"""全局配置：模型、路径、运行参数。

所有可调项都可以用环境变量覆盖，方便在不同机器 / CI 上跑。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv

# ---------------------------------------------------------------- 路径

# src/job_agent/config.py -> 上溯三层就是项目根目录
PROJECT_ROOT = Path(__file__).resolve().parents[2]

DATA_DIR = PROJECT_ROOT / "data"
JD_DIR = DATA_DIR / "jds"
OUTPUT_DIR = PROJECT_ROOT / "outputs"
CACHE_DIR = PROJECT_ROOT / ".cache"

MASTER_PROFILE_MD = DATA_DIR / "master_profile.md"
PROFILE_CACHE = CACHE_DIR / "candidate_profile.json"

# ---------------------------------------------------------------- 模型

# 注意：模型名必须与 https://api.deepseek.com/models 返回的 id 完全一致。
# 曾经写成 "deepseek-v4-flash" 会直接 400，正确 id 是 "deepseek-flash"。
FLASH_MODEL = "deepseek-flash"  # 支持图片输入，1M 上下文
PRO_MODEL = "deepseek-v4-pro"  # 纯文本，1M 上下文
VALID_MODELS = (FLASH_MODEL, PRO_MODEL)

# deepseek-flash / v4-pro 都是思考模型，支持三档 reasoning effort
Effort = Literal["low", "high", "max"]

#: 结构化抽取类任务用低档，够用且更快更便宜
EFFORT_EXTRACT: Effort = "low"
#: 需要创造力和措辞的任务（写简历、写求职信）用高档
EFFORT_WRITE: Effort = "high"


# ---------------------------------------------------------------- 配置对象


@dataclass
class Settings:
    """一次运行的全部可调参数。"""

    api_key: str = ""
    model: str = FLASH_MODEL
    temperature: float = 0.3
    max_tokens: int | None = None
    timeout: float = 120.0
    max_retries: int = 3

    # 是否使用缓存（解析 JD / 简历底稿的结果落盘，避免重复烧 token）
    use_cache: bool = True
    verbose: bool = False

    output_dir: Path = field(default_factory=lambda: OUTPUT_DIR)

    def __post_init__(self) -> None:
        if self.model not in VALID_MODELS:
            raise ValueError(
                f"不支持的模型 {self.model!r}，可选：{', '.join(VALID_MODELS)}"
            )

    @property
    def has_api_key(self) -> bool:
        return bool(self.api_key)

    def require_api_key(self) -> str:
        if not self.api_key:
            raise RuntimeError(
                "未找到 DEEPSEEK_API_KEY。请复制 .env.example 为 .env，"
                "并填入你的 DeepSeek API Key。"
            )
        return self.api_key


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def ensure_dirs() -> None:
    """确保运行期需要的目录存在。"""
    for path in (DATA_DIR, JD_DIR, OUTPUT_DIR, CACHE_DIR):
        path.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """读取 .env 并构造全局配置（进程内只构造一次）。"""
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    ensure_dirs()

    return Settings(
        api_key=os.getenv("DEEPSEEK_API_KEY", "").strip(),
        model=os.getenv("DEEPSEEK_MODEL", FLASH_MODEL).strip() or FLASH_MODEL,
        temperature=_env_float("DEEPSEEK_TEMPERATURE", 0.3),
        timeout=_env_float("DEEPSEEK_TIMEOUT", 120.0),
        use_cache=_env_bool("JOB_AGENT_CACHE", True),
        verbose=_env_bool("JOB_AGENT_VERBOSE", False),
    )
