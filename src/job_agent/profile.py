"""把候选人的简历底稿解析成结构化档案。"""

from __future__ import annotations

import json
from pathlib import Path

from . import prompts
from .config import EFFORT_EXTRACT, MASTER_PROFILE_MD, PROFILE_CACHE, Settings, get_settings
from .llm import invoke_structured
from .schemas import CandidateProfile
from .storage import dump_json, load_cache, read_text, save_cache, write_text

# 底稿太短通常说明用户还没填，提前拦住比让模型瞎猜更好
_MIN_LENGTH = 60


def load_master_profile_text(path: str | Path | None = None) -> str:
    """读取简历底稿原文。"""
    target = Path(path) if path else Path(MASTER_PROFILE_MD)
    if not target.is_file():
        raise FileNotFoundError(
            f"找不到简历底稿：{target}\n"
            f"请先编辑 {MASTER_PROFILE_MD}，填入你的真实经历。"
        )
    text = read_text(target)
    if len(text.strip()) < _MIN_LENGTH:
        raise ValueError(
            f"简历底稿内容太短（{len(text.strip())} 字符），请先补充真实经历再运行。"
        )
    return text


def build_candidate_profile(
    source: str | Path | None = None,
    *,
    settings: Settings | None = None,
    refresh: bool = False,
    persist: bool = True,
) -> CandidateProfile:
    """把底稿文本解析成 CandidateProfile。

    Args:
        source: 底稿文件路径；不传则用 data/master_profile.md。
            也可以直接传一大段底稿文本（长度超过 200 且含换行时视为文本）。
        refresh: 忽略缓存，强制重新解析。
        persist: 是否把结果写入 .cache/candidate_profile.json。
    """
    settings = settings or get_settings()

    if isinstance(source, str) and len(source) > 200 and "\n" in source:
        text = source
        source_label = "inline"
    else:
        text = load_master_profile_text(source)
        source_label = str(source or MASTER_PROFILE_MD)

    if settings.use_cache and not refresh:
        cached = load_cache("profile", text)
        if cached:
            return CandidateProfile.model_validate(cached)

    profile = invoke_structured(
        CandidateProfile,
        prompts.PROFILE_SYSTEM,
        prompts.profile_user_prompt(text),
        settings=settings,
        effort=EFFORT_EXTRACT,
        temperature=0.0,
    )

    if settings.use_cache:
        save_cache("profile", text, profile)

    if persist:
        write_text(PROFILE_CACHE, dump_json(profile))

    if settings.verbose:
        print(f"[profile] 已解析 {source_label} -> {len(profile.skills)} 项技能")

    return profile


def load_cached_profile() -> CandidateProfile | None:
    """读取上一次解析好的档案缓存（不调用模型）。"""
    path = Path(PROFILE_CACHE)
    if not path.is_file():
        return None
    try:
        return CandidateProfile.model_validate(json.loads(read_text(path)))
    except Exception:  # noqa: BLE001 - 缓存损坏就当没有
        return None
