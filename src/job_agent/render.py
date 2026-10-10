"""把结构化结果渲染成 Markdown / Word / 纯文本。

Word 导出依赖 python-docx，缺失时给出明确的安装提示而不是静默失败。
"""

from __future__ import annotations

from pathlib import Path

from .schemas import (
    CandidateProfile,
    CoverLetter,
    InterviewPrep,
    JDProfile,
    MatchReport,
    TailoredResume,
)

# ================================================================ 小工具


def _score_bar(score: int, width: int = 20) -> str:
    filled = max(0, min(width, round(score / 100 * width)))
    return "█" * filled + "░" * (width - filled)


def _bullet_lines(items: list[str], indent: str = "- ") -> list[str]:
    return [f"{indent}{item}" for item in items if str(item).strip()]


# ================================================================ 匹配报告


def match_to_markdown(
    report: MatchReport,
    jd: JDProfile | None = None,
    candidate: CandidateProfile | None = None,
) -> str:
    """把匹配报告渲染成可读的 Markdown。"""
    lines: list[str] = []

    title = f"# 匹配度分析报告{f'：{jd.title}' if jd else ''}"
    lines.append(title)
    lines.append("")

    if jd:
        meta = [f"**公司**：{jd.company}", f"**职级**：{jd.seniority}"]
        if jd.location and jd.location != "未提及":
            meta.append(f"**地点**：{jd.location}")
        meta.append(f"**领域**：{jd.domain}")
        lines.append(" ｜ ".join(meta))
        lines.append("")

    lines.append(f"## 综合评分：{report.overall_score} / 100")
    lines.append("")
    lines.append(f"`{_score_bar(report.overall_score)}`")
    lines.append("")
    lines.append(f"**结论：{report.verdict}**")
    lines.append("")

    if report.dimensions:
        lines.append("### 分维度评分")
        lines.append("")
        lines.append("| 维度 | 得分 | 说明 |")
        lines.append("| --- | --- | --- |")
        for dim in report.dimensions:
            lines.append(f"| {dim.dimension} | {dim.score} | {dim.comment} |")
        lines.append("")

    if report.strengths:
        lines.append("### 你的优势")
        lines.append("")
        lines.extend(_bullet_lines(report.strengths))
        lines.append("")

    if report.weaknesses:
        lines.append("### 你的短板")
        lines.append("")
        lines.extend(_bullet_lines(report.weaknesses))
        lines.append("")

    if report.matched_skills:
        lines.append("### 已满足的要求")
        lines.append("")
        lines.append("| 技能 | JD 要求 | 你的水平 | 证据 |")
        lines.append("| --- | --- | --- | --- |")
        for item in report.matched_skills:
            lines.append(
                f"| {item.skill} | {item.required_level} | "
                f"{item.candidate_level} | {item.evidence} |"
            )
        lines.append("")

    if report.gaps:
        lines.append("### 待补足的差距")
        lines.append("")
        for item in report.gaps:
            lines.append(
                f"- **{item.skill}**（JD 要求 {item.required_level}，"
                f"你的水平 {item.candidate_level}）"
            )
            if item.evidence:
                lines.append(f"  - 证据：{item.evidence}")
            if item.suggestion:
                lines.append(f"  - 建议：{item.suggestion}")
        lines.append("")

    lines.append(f"### 关键词覆盖率：{report.keyword_coverage:.0%}")
    lines.append("")
    if report.ats_keywords_to_add:
        lines.append("以下 JD 关键词尚未在底稿中体现，**仅在真实具备时**才补进简历：")
        lines.append("")
        lines.extend(_bullet_lines(report.ats_keywords_to_add))
        lines.append("")

    if report.strategy:
        lines.append("### 简历撰写策略")
        lines.append("")
        for index, item in enumerate(report.strategy, 1):
            lines.append(f"{index}. {item}")
        lines.append("")

    return "\n".join(lines).strip() + "\n"


# ================================================================ 简历 Markdown

#: 有工作经历时的章节顺序
_ORDER_EXPERIENCED = (
    "summary",
    "skills",
    "experiences",
    "projects",
    "campus",
    "education",
    "extras",
)

#: 应届生（无工作经历）时的顺序：教育背景与项目前置，不让空的工作经历占版面
_ORDER_STUDENT = (
    "summary",
    "education",
    "projects",
    "campus",
    "skills",
    "extras",
)


def _section_order(resume: TailoredResume) -> tuple[str, ...]:
    """按候选人类型决定章节顺序。"""
    return _ORDER_EXPERIENCED if resume.experiences else _ORDER_STUDENT


def _compose_heading(primary: str, secondary: str = "") -> str:
    return f"{primary} — {secondary}" if secondary else primary


def _entry_lines(
    heading: str, period: str, bullets: list[str], tech: list[str]
) -> list[str]:
    """Markdown 下一条经历/项目/校园职务的渲染，三种小节共用。"""
    lines = [f"### {heading}", ""]
    if period:
        lines += [f"*{period}*", ""]
    lines += _bullet_lines(bullets)
    if tech:
        lines += ["", f"技术栈：{'、'.join(tech)}"]
    lines.append("")
    return lines


def resume_to_markdown(resume: TailoredResume) -> str:
    """把定制简历渲染成 Markdown。"""
    lines: list[str] = []

    contact = resume.contact
    lines.append(f"# {contact.name or resume.target_title}")
    lines.append("")

    header_parts: list[str] = []
    if contact.phone:
        header_parts.append(contact.phone)
    if contact.email:
        header_parts.append(contact.email)
    if contact.city:
        header_parts.append(contact.city)
    header_parts.extend(contact.links)
    if header_parts:
        lines.append(" ｜ ".join(header_parts))
        lines.append("")

    if resume.target_title:
        lines.append(f"**求职意向：{resume.target_title}**")
        lines.append("")

    # 按候选人类型决定章节顺序：在校生把教育背景和项目前置
    for key in _section_order(resume):
        if key == "summary" and resume.summary:
            lines += ["## 个人简介", "", resume.summary, ""]

        elif key == "skills" and resume.core_skills:
            lines += ["## 核心技能", ""]
            lines += [f"- {skill}" for skill in resume.core_skills]
            lines.append("")

        elif key == "experiences" and resume.experiences:
            lines += ["## 工作经历", ""]
            for exp in resume.experiences:
                lines += _entry_lines(
                    _compose_heading(exp.company, exp.title),
                    exp.period,
                    exp.bullets,
                    exp.tech,
                )

        elif key == "projects" and resume.projects:
            lines += ["## 项目经历", ""]
            for project in resume.projects:
                lines += _entry_lines(
                    _compose_heading(project.name, project.role),
                    project.period,
                    project.bullets,
                    project.tech,
                )

        elif key == "campus" and resume.campus:
            lines += ["## 校园经历", ""]
            for item in resume.campus:
                lines += _entry_lines(
                    _compose_heading(item.company, item.title),
                    item.period,
                    item.bullets,
                    item.tech,
                )

        elif key == "education" and resume.education:
            lines += ["## 教育背景", ""]
            lines += _bullet_lines(resume.education)
            lines.append("")

        elif key == "extras" and resume.extras:
            lines += ["## 其他", ""]
            lines += _bullet_lines(resume.extras)
            lines.append("")

    return "\n".join(lines).strip() + "\n"


# ================================================================ 求职信 / 面试


def cover_letter_to_markdown(letter: CoverLetter) -> str:
    lines = [f"# 求职信", "", letter.greeting, ""]
    for paragraph in letter.body:
        lines.append(paragraph)
        lines.append("")
    lines.append(letter.closing)
    lines.append("")
    return "\n".join(lines).strip() + "\n"


def interview_to_markdown(prep: InterviewPrep) -> str:
    lines: list[str] = ["# 面试准备包", ""]

    if prep.prep_focus:
        lines.append("## 重点复习方向")
        lines.append("")
        lines.extend(_bullet_lines(prep.prep_focus))
        lines.append("")

    if prep.questions:
        lines.append("## 预测面试题")
        lines.append("")
        for index, item in enumerate(prep.questions, 1):
            lines.append(f"### {index}. [{item.category}] {item.question}")
            lines.append("")
            lines.append(f"- **考察点**：{item.intent}")
            if item.answer_outline:
                lines.append("- **回答提纲**：")
                lines.extend(f"  - {point}" for point in item.answer_outline)
            if item.risk:
                lines.append(f"- **容易踩的坑**：{item.risk}")
            lines.append("")

    if prep.questions_to_ask:
        lines.append("## 建议你反问的问题")
        lines.append("")
        lines.extend(_bullet_lines(prep.questions_to_ask))
        lines.append("")

    return "\n".join(lines).strip() + "\n"


# ================================================================ Word 导出


def _require_docx():
    try:
        import docx  # noqa: F401
    except ImportError as exc:  # pragma: no cover - 取决于环境
        raise ImportError(
            "导出 Word 需要 python-docx，请先安装：\n"
            r"  D:\Project\Anaconda\envs\langchain_env\python.exe -m pip install python-docx"
        ) from exc
    return docx


def _set_font(run, *, name: str = "微软雅黑", size=None, bold=None, color=None) -> None:
    """设置 run 的字体，同时处理中文字体（eastAsia）。"""
    from docx.oxml.ns import qn
    from docx.shared import Pt, RGBColor

    run.font.name = name
    if size is not None:
        run.font.size = Pt(size)
    if bold is not None:
        run.font.bold = bold
    if color is not None:
        run.font.color.rgb = RGBColor(*color)

    rpr = run._element.get_or_add_rPr()
    rfonts = rpr.get_or_add_rFonts()
    rfonts.set(qn("w:eastAsia"), name)
    rfonts.set(qn("w:ascii"), name)
    rfonts.set(qn("w:hAnsi"), name)


def _add_section_heading(document, text: str) -> None:
    """带下划线的分节标题。"""
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Pt

    paragraph = document.add_paragraph()
    paragraph.paragraph_format.space_before = Pt(10)
    paragraph.paragraph_format.space_after = Pt(4)
    run = paragraph.add_run(text)
    _set_font(run, size=12, bold=True, color=(0x1F, 0x3A, 0x5F))

    ppr = paragraph._p.get_or_add_pPr()
    borders = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), "8")
    bottom.set(qn("w:space"), "2")
    bottom.set(qn("w:color"), "1F3A5F")
    borders.append(bottom)
    ppr.append(borders)


def _add_bullet(document, text: str, *, size: float = 10.5) -> None:
    paragraph = document.add_paragraph(style="List Bullet")
    paragraph.paragraph_format.space_after = None
    run = paragraph.add_run(text)
    _set_font(run, size=size)


def _add_org_line(document, left: str, right: str = "") -> None:
    """一行两栏：左侧公司/职位加粗，右侧时间右对齐。"""
    from docx.enum.text import WD_TAB_ALIGNMENT
    from docx.shared import Cm, Pt

    paragraph = document.add_paragraph()
    paragraph.paragraph_format.space_before = Pt(6)
    paragraph.paragraph_format.space_after = None
    paragraph.paragraph_format.tab_stops.add_tab_stop(
        Cm(17.0), WD_TAB_ALIGNMENT.RIGHT
    )
    left_run = paragraph.add_run(left)
    _set_font(left_run, size=11, bold=True)
    if right:
        right_run = paragraph.add_run(f"\t{right}")
        _set_font(right_run, size=10, color=(0x59, 0x59, 0x59))


def _add_entry_block(
    document,
    primary: str,
    secondary: str,
    period: str,
    bullets: list[str],
    tech: list[str],
) -> None:
    """一条经历/项目/校园职务：标题行 + 要点 + 技术栈。"""
    _add_org_line(document, _compose_heading(primary, secondary), period)
    for bullet in bullets:
        _add_bullet(document, bullet)
    if tech:
        tech_paragraph = document.add_paragraph()
        tech_run = tech_paragraph.add_run(f"技术栈：{'、'.join(tech)}")
        _set_font(tech_run, size=9.5, color=(0x59, 0x59, 0x59))


def resume_to_docx(resume: TailoredResume, path: str | Path) -> Path:
    """把定制简历写成 ATS 友好的单栏 Word 文档。"""
    _require_docx()
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Cm, Pt

    document = Document()

    # 页面设置：A4 + 适中页边距
    section = document.sections[0]
    section.page_width = Cm(21.0)
    section.page_height = Cm(29.7)
    for attr in ("top_margin", "bottom_margin"):
        setattr(section, attr, Cm(1.6))
    for attr in ("left_margin", "right_margin"):
        setattr(section, attr, Cm(2.0))

    # 全局默认字体
    normal = document.styles["Normal"]
    normal.font.name = "微软雅黑"
    normal.font.size = Pt(10.5)

    contact = resume.contact

    # ---- 抬头
    name_paragraph = document.add_paragraph()
    name_paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    name_paragraph.paragraph_format.space_after = None
    name_run = name_paragraph.add_run(contact.name or resume.target_title)
    _set_font(name_run, size=20, bold=True)

    if resume.target_title:
        target_paragraph = document.add_paragraph()
        target_paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        target_paragraph.paragraph_format.space_after = None
        target_run = target_paragraph.add_run(f"求职意向：{resume.target_title}")
        _set_font(target_run, size=11, color=(0x40, 0x40, 0x40))

    contact_parts = [
        part for part in (contact.phone, contact.email, contact.city) if part
    ]
    contact_parts.extend(contact.links)
    if contact_parts:
        contact_paragraph = document.add_paragraph()
        contact_paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        contact_run = contact_paragraph.add_run(" ｜ ".join(contact_parts))
        _set_font(contact_run, size=9.5, color=(0x59, 0x59, 0x59))

    # ---- 正文各节（顺序由 _section_order 决定）
    for key in _section_order(resume):
        if key == "summary" and resume.summary:
            _add_section_heading(document, "个人简介")
            document.add_paragraph(resume.summary)

        elif key == "skills" and resume.core_skills:
            _add_section_heading(document, "核心技能")
            for skill in resume.core_skills:
                _add_bullet(document, skill)

        elif key == "experiences" and resume.experiences:
            _add_section_heading(document, "工作经历")
            for exp in resume.experiences:
                _add_entry_block(
                    document, exp.company, exp.title, exp.period, exp.bullets, exp.tech
                )

        elif key == "projects" and resume.projects:
            _add_section_heading(document, "项目经历")
            for project in resume.projects:
                _add_entry_block(
                    document,
                    project.name,
                    project.role,
                    project.period,
                    project.bullets,
                    project.tech,
                )

        elif key == "campus" and resume.campus:
            _add_section_heading(document, "校园经历")
            for item in resume.campus:
                _add_entry_block(
                    document,
                    item.company,
                    item.title,
                    item.period,
                    item.bullets,
                    item.tech,
                )

        elif key == "education" and resume.education:
            _add_section_heading(document, "教育背景")
            for item in resume.education:
                _add_bullet(document, item)

        elif key == "extras" and resume.extras:
            _add_section_heading(document, "其他")
            for item in resume.extras:
                _add_bullet(document, item)

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    document.save(str(target))
    return target
