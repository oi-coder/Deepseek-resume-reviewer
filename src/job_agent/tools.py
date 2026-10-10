"""Agent 的工具集。

工具通过闭包持有一次会话的上下文（当前 JD、候选人档案、匹配报告……），
这样 Agent 只需要说「分析匹配度」而不必每次都把整份 JD 和简历塞进工具参数里，
既省 token 也避免模型改坏原文。

说明：langchain-core 1.x 自带 bind_tools，但 langgraph 未安装，
所以这里用最朴素的「bind_tools + 手工执行 tool_calls」循环，
不引入额外依赖也能得到真正的 Agent 行为。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from langchain_core.tools import BaseTool, tool

from .config import OUTPUT_DIR, Settings, get_settings
from .jd import parse_jd
from .match import analyze_match as run_match
from .profile import build_candidate_profile, load_cached_profile
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
from .storage import dump_json, output_path, read_text, slugify, write_text


@dataclass
class AgentSession:
    """一次 Agent 会话的状态。"""

    settings: Settings = field(default_factory=get_settings)
    jd_text: str | None = None
    jd: JDProfile | None = None
    candidate: CandidateProfile | None = None
    match: MatchReport | None = None
    resume: TailoredResume | None = None
    cover_letter: CoverLetter | None = None
    interview: InterviewPrep | None = None
    #: 本次会话生成的文件，供最终汇报
    artifacts: list[Path] = field(default_factory=list)

    # ---- 惰性获取候选人档案
    def ensure_candidate(self, *, refresh: bool = False) -> CandidateProfile:
        if self.candidate is None or refresh:
            self.candidate = build_candidate_profile(
                settings=self.settings, refresh=refresh
            )
        return self.candidate

    def ensure_jd(self, jd_text: str | None = None, *, refresh: bool = False):
        if jd_text:
            self.jd_text = jd_text
        if not self.jd_text:
            raise ValueError(
                "还没有载入 JD。请先调用 load_job_description 把 JD 文本传进来。"
            )
        if self.jd is None or refresh:
            self.jd = parse_jd(self.jd_text, settings=self.settings, refresh=refresh)
        return self.jd

    def ensure_match(self) -> MatchReport:
        if self.match is None:
            jd = self.ensure_jd()
            candidate = self.ensure_candidate()
            self.match = run_match(jd, candidate, settings=self.settings)
        return self.match


# ================================================================ 工具工厂


def build_tools(session: AgentSession) -> list[BaseTool]:
    """为给定会话构造工具列表。"""

    @tool
    def load_job_description(jd_text: str) -> str:
        """载入并解析一份招聘 JD。当你拿到用户贴的 JD 原文时，第一步就调用它。
        参数 jd_text 必须是 JD 的完整原文，不要摘要、不要改写。"""
        jd = session.ensure_jd(jd_text, refresh=True)
        return (
            f"已解析 JD：{jd.title}（{jd.company}，{jd.seniority}，{jd.domain}）\n"
            f"硬性要求 {len(jd.must_have)} 条，加分项 {len(jd.nice_to_have)} 条，"
            f"关键词 {len(jd.keywords)} 个。\n"
            f"岗位概述：{jd.summary}"
        )

    @tool
    def get_candidate_profile(refresh: bool = False) -> str:
        """读取候选人的结构化档案（技能、经历、项目、教育）。
        当需要确认候选人到底会什么时调用。refresh=True 会重新解析底稿。"""
        candidate = session.ensure_candidate(refresh=refresh)
        return dump_json(candidate)

    @tool
    def analyze_match() -> str:
        """对已载入的 JD 和候选人档案做匹配度分析，返回 Markdown 报告。
        需要先调用 load_job_description。"""
        report = session.ensure_match()
        if session.jd is None:
            return "请先调用 load_job_description 载入 JD。"
        return match_to_markdown(report, session.jd, session.candidate)

    @tool
    def generate_resume() -> str:
        """生成针对当前 JD 的定制简历，同时保存 Markdown 和 Word 两个文件。
        需要先调用 load_job_description。返回文件路径与改动说明。"""
        jd = session.ensure_jd()
        candidate = session.ensure_candidate()
        match = session.ensure_match()

        resume = write_resume(jd, candidate, match, settings=session.settings)
        session.resume = resume

        markdown = resume_to_markdown(resume)
        stem = f"resume-{slugify(jd.title)}"
        md_path = write_text(output_path(stem, ".md"), markdown)
        session.artifacts.append(md_path)

        docx_note = ""
        try:
            docx_path = resume_to_docx(resume, output_path(stem, ".docx"))
            session.artifacts.append(docx_path)
            docx_note = f"\nWord 版：{docx_path}"
        except ImportError as exc:
            docx_note = f"\nWord 导出跳过：{exc}"

        notes = "\n".join(f"- {note}" for note in resume.change_notes) or "- （无）"
        return (
            f"简历已生成。\nMarkdown 版：{md_path}{docx_note}\n"
            f"求职意向：{resume.target_title}\n"
            f"已覆盖 ATS 关键词：{'、'.join(resume.ats_keywords) or '（无）'}\n"
            f"相对底稿的调整：\n{notes}"
        )

    @tool
    def generate_cover_letter() -> str:
        """生成针对当前 JD 的求职信，保存为 Markdown。
        需要先调用 load_job_description。"""
        jd = session.ensure_jd()
        candidate = session.ensure_candidate()
        match = session.ensure_match()

        resume_md = session.resume and resume_to_markdown(session.resume) or ""
        letter = write_cover_letter(
            jd, candidate, match, resume_md, settings=session.settings
        )
        session.cover_letter = letter

        path = write_text(
            output_path(f"cover-letter-{slugify(jd.title)}", ".md"),
            cover_letter_to_markdown(letter),
        )
        session.artifacts.append(path)
        return f"求职信已生成：{path}\n\n" + "\n\n".join(letter.body)

    @tool
    def generate_interview_prep() -> str:
        """生成面试预测题与准备建议，保存为 Markdown。
        需要先调用 load_job_description。"""
        jd = session.ensure_jd()
        candidate = session.ensure_candidate()
        match = session.ensure_match()

        prep = prepare_interview(jd, candidate, match, settings=session.settings)
        session.interview = prep

        path = write_text(
            output_path(f"interview-{slugify(jd.title)}", ".md"),
            interview_to_markdown(prep),
        )
        session.artifacts.append(path)
        return f"面试准备包已生成：{path}（共 {len(prep.questions)} 道预测题）"

    @tool
    def list_outputs() -> str:
        """列出 outputs 目录下已生成的所有文件。"""
        directory = Path(OUTPUT_DIR)
        if not directory.is_dir():
            return "outputs 目录还不存在。"
        files = sorted(
            (p for p in directory.rglob("*") if p.is_file()),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if not files:
            return "outputs 目录还是空的。"
        return "\n".join(f"- {p.name}（{p.stat().st_size} 字节）" for p in files[:30])

    @tool
    def read_output(filename: str) -> str:
        """读取 outputs 目录下某个文件的内容。filename 传文件名即可。"""
        directory = Path(OUTPUT_DIR)
        matches = [p for p in directory.rglob("*") if p.is_file() and p.name == filename]
        if not matches:
            matches = [
                p for p in directory.rglob("*") if p.is_file() and filename in p.name
            ]
        if not matches:
            return f"找不到文件：{filename}"
        return read_text(matches[0])[:8000]

    @tool
    def save_note(title: str, content: str) -> str:
        """把一段分析结论或备忘保存到 outputs 目录，标题用于文件名。"""
        path = write_text(output_path(slugify(title), ".md"), content)
        session.artifacts.append(path)
        return f"已保存：{path}"

    return [
        load_job_description,
        get_candidate_profile,
        analyze_match,
        generate_resume,
        generate_cover_letter,
        generate_interview_prep,
        list_outputs,
        read_output,
        save_note,
    ]


__all__ = ["AgentSession", "build_tools", "load_cached_profile"]
