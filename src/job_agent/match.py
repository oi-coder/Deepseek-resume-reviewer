"""JD 与候选人的匹配度分析。"""

from __future__ import annotations

from . import prompts
from .config import EFFORT_EXTRACT, Settings, get_settings
from .llm import invoke_structured
from .schemas import CandidateProfile, JDProfile, MatchReport
from .storage import dump_json, load_cache, save_cache


def analyze_match(
    jd: JDProfile,
    candidate: CandidateProfile,
    *,
    settings: Settings | None = None,
    refresh: bool = False,
) -> MatchReport:
    """对岗位与候选人做逐项比对，输出匹配报告。

    缓存键由 JD 与候选人两份 JSON 共同决定，任一变化都会重新分析。
    """
    settings = settings or get_settings()

    jd_json = dump_json(jd)
    profile_json = dump_json(candidate)
    cache_key = f"{jd_json}\n---\n{profile_json}"

    if settings.use_cache and not refresh:
        cached = load_cache("match", cache_key)
        if cached:
            return MatchReport.model_validate(cached)

    report = invoke_structured(
        MatchReport,
        prompts.MATCH_SYSTEM,
        prompts.match_user_prompt(jd_json, profile_json),
        settings=settings,
        effort=EFFORT_EXTRACT,
        temperature=0.2,
    )

    if settings.use_cache:
        save_cache("match", cache_key, report)

    if settings.verbose:
        print(
            f"[match] {report.overall_score} 分 / {report.verdict} | "
            f"命中 {len(report.matched_skills)} 项，缺口 {len(report.gaps)} 项"
        )

    return report
