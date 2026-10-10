"""把招聘 JD 解析成结构化画像。"""

from __future__ import annotations

from pathlib import Path

from . import prompts
from .config import EFFORT_EXTRACT, Settings, get_settings
from .llm import invoke_structured
from .schemas import JDProfile
from .storage import load_cache, read_text, resolve_jd_path, save_cache

_MIN_LENGTH = 40


def parse_jd(
    jd_text: str,
    *,
    settings: Settings | None = None,
    refresh: bool = False,
) -> JDProfile:
    """把一段 JD 文本解析成 JDProfile。"""
    settings = settings or get_settings()
    text = (jd_text or "").strip()
    if len(text) < _MIN_LENGTH:
        raise ValueError(
            f"JD 内容太短（{len(text)} 字符），至少需要 {_MIN_LENGTH} 字符才能解析。"
        )

    if settings.use_cache and not refresh:
        cached = load_cache("jd", text)
        if cached:
            return JDProfile.model_validate(cached)

    profile = invoke_structured(
        JDProfile,
        prompts.JD_SYSTEM,
        prompts.jd_user_prompt(text),
        settings=settings,
        effort=EFFORT_EXTRACT,
        # 抽取任务用 0 温度：思考模型本身仍有采样方差，但能显著减少
        # 同一份 JD 两次解析出不同条目数的情况
        temperature=0.0,
    )

    if settings.use_cache:
        save_cache("jd", text, profile)

    if settings.verbose:
        print(
            f"[jd] {profile.title} | 硬性要求 {len(profile.must_have)} 条 | "
            f"关键词 {len(profile.keywords)} 个"
        )

    return profile


def parse_jd_file(
    path: str | Path,
    *,
    settings: Settings | None = None,
    refresh: bool = False,
) -> JDProfile:
    """从文件解析 JD，支持省略扩展名、支持 gbk 编码。"""
    resolved = resolve_jd_path(str(path))
    return parse_jd(read_text(resolved), settings=settings, refresh=refresh)
