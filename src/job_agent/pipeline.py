"""确定性流水线：不经过 Agent 推理，按固定顺序跑完整流程。

CLI 的 tailor / match 命令走这里，好处是省 token、结果稳定、便于复现。
需要多轮追问和灵活决策时才用 agent.py 里的 AgentRunner。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .config import Settings, get_settings
from .jd import parse_jd, parse_jd_file
from .match import analyze_match
from .profile import build_candidate_profile
from .render import (
    cover_letter_to_markdown,
    interview_to_markdown,
    match_to_markdown,
    resume_to_docx,
    resume_to_markdown,
)
from .resume import prepare_interview, write_cover_letter, write_resume
from .schemas import (
    CandidateProfile,
    CoverLetter,
    InterviewPrep,
    JDProfile,
    MatchReport,
    TailoredResume,
)
from .storage import output_path, slugify, write_text

Progress = Callable[[str], None]


def _noop(_: str) -> None:
    return None


@dataclass
class PipelineResult:
    """一次完整流程的所有产物。"""

    jd: JDProfile
    candidate: CandidateProfile
    match: MatchReport
    resume: TailoredResume | None = None
    cover_letter: CoverLetter | None = None
    interview: InterviewPrep | None = None
    artifacts: list[Path] = field(default_factory=list)

    @property
    def match_markdown(self) -> str:
        return match_to_markdown(self.match, self.jd, self.candidate)

    @property
    def resume_markdown(self) -> str:
        return resume_to_markdown(self.resume) if self.resume else ""


def run_pipeline(
    *,
    jd_path: str | Path | None = None,
    jd_text: str | None = None,
    with_resume: bool = True,
    with_cover_letter: bool = False,
    with_interview: bool = False,
    candidate_source: str | Path | None = None,
    refresh: bool = False,
    settings: Settings | None = None,
    progress: Progress | None = None,
) -> PipelineResult:
    """按 parse JD -> 解析底稿 -> 匹配 -> 生成 的顺序跑完整流程。"""
    settings = settings or get_settings()
    say = progress or _noop

    # ---- 1. JD
    if jd_text:
        say("解析 JD…")
        jd = parse_jd(jd_text, settings=settings, refresh=refresh)
    elif jd_path:
        say(f"解析 JD：{jd_path}")
        jd = parse_jd_file(jd_path, settings=settings, refresh=refresh)
    else:
        raise ValueError("必须提供 jd_path 或 jd_text 之一。")

    # ---- 2. 候选人底稿
    say("解析简历底稿…")
    candidate = build_candidate_profile(
        candidate_source, settings=settings, refresh=refresh
    )

    # ---- 3. 匹配分析
    say("分析匹配度…")
    match = analyze_match(jd, candidate, settings=settings, refresh=refresh)

    result = PipelineResult(jd=jd, candidate=candidate, match=match)

    stem = slugify(jd.title)

    # 匹配报告落盘
    report_path = write_text(output_path(f"match-{stem}", ".md"), result.match_markdown)
    result.artifacts.append(report_path)

    # ---- 4. 简历
    if with_resume:
        say("撰写定制简历…")
        resume = write_resume(jd, candidate, match, settings=settings)
        result.resume = resume

        markdown = resume_to_markdown(resume)
        md_path = write_text(output_path(f"resume-{stem}", ".md"), markdown)
        result.artifacts.append(md_path)

        try:
            docx_path = resume_to_docx(resume, output_path(f"resume-{stem}", ".docx"))
            result.artifacts.append(docx_path)
        except ImportError as exc:
            say(f"跳过 Word 导出：{exc}")

    # ---- 5. 求职信
    if with_cover_letter:
        say("撰写求职信…")
        letter = write_cover_letter(
            jd,
            candidate,
            match,
            result.resume_markdown,
            settings=settings,
        )
        result.cover_letter = letter
        letter_path = write_text(
            output_path(f"cover-letter-{stem}", ".md"),
            cover_letter_to_markdown(letter),
        )
        result.artifacts.append(letter_path)

    # ---- 6. 面试准备
    if with_interview:
        say("准备面试题…")
        prep = prepare_interview(jd, candidate, match, settings=settings)
        result.interview = prep
        prep_path = write_text(
            output_path(f"interview-{stem}", ".md"),
            interview_to_markdown(prep),
        )
        result.artifacts.append(prep_path)

    return result
