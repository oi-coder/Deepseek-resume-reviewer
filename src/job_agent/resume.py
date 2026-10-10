"""生成定制简历、求职信与面试准备包。"""

from __future__ import annotations

from . import prompts
from .config import EFFORT_EXTRACT, EFFORT_WRITE, Settings, get_settings
from .llm import invoke_structured
from .schemas import (
    CandidateProfile,
    CoverLetter,
    InterviewPrep,
    JDProfile,
    MatchReport,
    TailoredResume,
)
from .storage import dump_json


def write_resume(
    jd: JDProfile,
    candidate: CandidateProfile,
    match: MatchReport,
    *,
    settings: Settings | None = None,
) -> TailoredResume:
    """生成针对该 JD 的定制简历（结构化）。"""
    settings = settings or get_settings()
    return invoke_structured(
        TailoredResume,
        prompts.RESUME_SYSTEM,
        prompts.resume_user_prompt(
            dump_json(jd), dump_json(candidate), dump_json(match)
        ),
        settings=settings,
        effort=EFFORT_WRITE,
        temperature=0.5,
    )


def write_cover_letter(
    jd: JDProfile,
    candidate: CandidateProfile,
    match: MatchReport,
    resume_markdown: str,
    *,
    settings: Settings | None = None,
) -> CoverLetter:
    """生成求职信。"""
    settings = settings or get_settings()
    return invoke_structured(
        CoverLetter,
        prompts.COVER_LETTER_SYSTEM,
        prompts.cover_letter_user_prompt(
            dump_json(jd), dump_json(candidate), dump_json(match), resume_markdown
        ),
        settings=settings,
        effort=EFFORT_WRITE,
        temperature=0.6,
    )


def prepare_interview(
    jd: JDProfile,
    candidate: CandidateProfile,
    match: MatchReport,
    *,
    settings: Settings | None = None,
) -> InterviewPrep:
    """生成面试预测题与准备建议。"""
    settings = settings or get_settings()
    return invoke_structured(
        InterviewPrep,
        prompts.INTERVIEW_SYSTEM,
        prompts.interview_user_prompt(
            dump_json(jd), dump_json(candidate), dump_json(match)
        ),
        settings=settings,
        effort=EFFORT_EXTRACT,
        temperature=0.4,
    )
