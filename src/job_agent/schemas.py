"""数据契约（Pydantic 模型）。

这些模型同时承担两个职责：
1. 校验 LLM 输出的结构；
2. 因为字段 description 会被序列化进 JSON Schema 一起喂给模型，
   所以它们也是**提示词的一部分** —— 描述写得越具体，抽取质量越高。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# ---------------------------------------------------------------- 枚举

#: JD 里对某项技能要求的熟练度
Level = Literal["了解", "熟练", "精通", "专家"]

#: 候选人实际具备的熟练度，"无" 表示底稿里找不到证据
CandidateLevel = Literal["无", "了解", "熟练", "精通", "专家"]

#: 综合匹配结论
Verdict = Literal["强烈推荐", "推荐", "可以一试", "不匹配"]


# ---------------------------------------------------------------- JD 侧


class SkillRequirement(BaseModel):
    """JD 中的一条技能要求。"""

    name: str = Field(description="技能名称，规范写法，例如 'PostgreSQL' 而不是 'pg'")
    level: Level = Field(description="JD 要求的熟练度等级")
    must_have: bool = Field(description="true=硬性要求/任职资格；false=加分项")
    evidence: str = Field(
        default="",
        description="JD 原文中支撑这条要求的句子片段，用于溯源，不要改写",
    )
    category: str = Field(
        default="其他",
        description="技能分类，取值示例：编程语言/框架/数据库/云与运维/算法与模型/工具/软技能/行业知识",
    )


class JDProfile(BaseModel):
    """一份招聘 JD 的结构化画像。"""

    title: str = Field(description="岗位名称，去掉公司名和括号里的编号")
    company: str = Field(default="未提及", description="招聘公司名称，未写明则填 '未提及'")
    seniority: str = Field(
        default="未说明",
        description="职级，例如 实习/初级/中级/高级/专家/管理，未写明填 '未说明'",
    )
    location: str = Field(default="未提及", description="工作地点，未写明填 '未提及'")
    employment_type: str = Field(
        default="全职", description="用工性质：全职/实习/兼职/外包/合同制"
    )
    domain: str = Field(default="通用", description="业务领域，例如 电商/AI基础设施/金融/医疗")

    summary: str = Field(description="用 2~3 句话概括这个岗位在找什么样的人")

    responsibilities: list[str] = Field(
        default_factory=list, description="岗位职责，逐条列出，保留原意"
    )
    must_have: list[SkillRequirement] = Field(
        default_factory=list, description="硬性要求（任职资格）列表"
    )
    nice_to_have: list[str] = Field(
        default_factory=list, description="加分项列表，每条一句话"
    )
    soft_skills: list[str] = Field(
        default_factory=list, description="软技能要求，例如 沟通能力/跨团队协作/自驱"
    )
    keywords: list[str] = Field(
        default_factory=list,
        description="用于通过 ATS 简历筛选系统的关键词，含技术名词与业务名词",
    )
    hidden_expectations: list[str] = Field(
        default_factory=list,
        description=(
            "JD 没明说但从措辞能推断出的隐含期待或风险，"
            "例如 '从0到1' 意味着要能独立开荒、'抗压能力强' 可能意味着加班多"
        ),
    )


# ---------------------------------------------------------------- 候选人侧


class ContactInfo(BaseModel):
    """联系方式。缺失的字段留空字符串，不要编造。"""

    name: str = Field(default="", description="姓名")
    phone: str = Field(default="", description="手机号，没有就留空")
    email: str = Field(default="", description="邮箱，没有就留空")
    city: str = Field(default="", description="所在城市")
    links: list[str] = Field(
        default_factory=list, description="GitHub/博客/主页等链接，仅保留底稿中真实出现的"
    )


class ExperienceItem(BaseModel):
    """一段工作经历（来自底稿的原始信息，不要润色）。"""

    company: str = Field(description="公司名称")
    title: str = Field(description="职位名称")
    period: str = Field(default="", description="起止时间，例如 '2022.03 - 2024.06'")
    description: str = Field(default="", description="这段经历的原始描述，保持原样")
    highlights: list[str] = Field(
        default_factory=list, description="从原始描述中拆出的要点，尽量保留数字与结果"
    )
    tech: list[str] = Field(default_factory=list, description="这段经历用到的技术栈")


class ProjectItem(BaseModel):
    """一个项目经历。"""

    name: str = Field(description="项目名称")
    role: str = Field(default="", description="担任角色")
    period: str = Field(default="", description="时间区间")
    description: str = Field(default="", description="项目描述原文")
    highlights: list[str] = Field(default_factory=list, description="项目要点，保留量化结果")
    tech: list[str] = Field(default_factory=list, description="技术栈")


class EducationItem(BaseModel):
    """一段教育经历。"""

    school: str = Field(description="学校名称")
    major: str = Field(default="", description="专业")
    degree: str = Field(default="", description="学历，例如 本科/硕士/博士")
    period: str = Field(default="", description="时间区间")


class CandidateProfile(BaseModel):
    """候选人底稿的结构化结果，是后续所有生成的**唯一事实来源**。"""

    contact: ContactInfo = Field(default_factory=ContactInfo)
    headline: str = Field(
        default="", description="一句话职业定位，例如 '5 年经验的 Python 后端 / LLM 应用工程师'"
    )
    years_experience: float = Field(
        default=0.0, description="累计工作年限，只按工作经历计算，实习可按 0.5 折算"
    )
    target_roles: list[str] = Field(
        default_factory=list, description="候选人想投的岗位方向"
    )
    skills: list[str] = Field(
        default_factory=list, description="全部技能标签，规范命名，便于与 JD 做匹配"
    )
    skill_details: dict[str, str] = Field(
        default_factory=dict,
        description="技能 -> 佐证，例如 {'Python': '3 年主力语言，写过 FastAPI 服务'}",
    )
    experiences: list[ExperienceItem] = Field(default_factory=list)
    projects: list[ProjectItem] = Field(default_factory=list)
    campus_experience: list[ExperienceItem] = Field(
        default_factory=list,
        description=(
            "校园职务与组织经历，例如 学生会/班委/社团负责人/志愿活动。"
            "company 填组织或班级名，title 填职务。"
            "应届生没有正式工作经历时，这里是重要的能力佐证，务必抽全"
        ),
    )
    education: list[EducationItem] = Field(default_factory=list)
    achievements: list[str] = Field(
        default_factory=list,
        description="获奖、竞赛名次、证书、开源贡献、专利等；不要把校园职务写在这里",
    )
    raw_summary: str = Field(
        default="", description="对底稿整体内容的简短复述，便于人工核对解析是否失真"
    )


# ---------------------------------------------------------------- 匹配分析


class SkillGap(BaseModel):
    """一条技能层面的匹配结论。"""

    skill: str = Field(description="技能名称")
    required_level: Level = Field(description="JD 要求的等级")
    candidate_level: CandidateLevel = Field(description="从底稿判断出的候选人等级")
    matched: bool = Field(description="是否满足要求")
    evidence: str = Field(
        default="",
        description="底稿中支撑该判断的原文证据；找不到证据就写 '底稿中未见相关经历'",
    )
    suggestion: str = Field(
        default="",
        description="若不满足：如何在简历中弱化或如何快速补齐；若满足：如何在简历中放大",
    )


class DimensionScore(BaseModel):
    """分维度评分。"""

    dimension: str = Field(
        description="维度名，固定用这几个：硬性技能/经验年限/项目含金量/领域匹配/学历背景/软技能"
    )
    score: int = Field(description="该维度得分，0-100 的整数")
    comment: str = Field(description="一句话说明打分理由")


class MatchReport(BaseModel):
    """JD 与候选人的匹配度分析报告。"""

    overall_score: int = Field(description="综合匹配分，0-100 整数")
    verdict: Verdict = Field(description="综合结论")
    dimensions: list[DimensionScore] = Field(
        default_factory=list, description="各维度得分明细"
    )
    matched_skills: list[SkillGap] = Field(
        default_factory=list, description="已满足的技能要求"
    )
    gaps: list[SkillGap] = Field(
        default_factory=list, description="未满足或存疑的技能要求，按重要性排序"
    )
    strengths: list[str] = Field(
        default_factory=list, description="相对该 JD 的核心竞争优势，3-5 条"
    )
    weaknesses: list[str] = Field(
        default_factory=list, description="相对该 JD 的短板，诚实评估，不要粉饰"
    )
    strategy: list[str] = Field(
        default_factory=list,
        description="针对这份 JD 的简历撰写策略，例如 '把 RAG 项目提到最前面'",
    )
    keyword_coverage: float = Field(
        default=0.0, description="JD 关键词在底稿中的覆盖率，0-1 之间的小数"
    )
    ats_keywords_to_add: list[str] = Field(
        default_factory=list,
        description="底稿里没有但 JD 要求的关键词，只能在真实具备时补进简历",
    )


# ---------------------------------------------------------------- 输出：简历


class ResumeExperience(BaseModel):
    """简历里的工作经历条目（已针对 JD 改写）。"""

    company: str = Field(description="公司名称，必须与底稿一致")
    title: str = Field(description="职位名称，可按目标岗位微调措辞但不得虚构职级")
    period: str = Field(default="", description="起止时间，与底稿一致")
    bullets: list[str] = Field(
        default_factory=list,
        description=(
            "针对该 JD 重写的要点，每条 1-2 行。优先用 '动作 + 技术 + 量化结果' 结构。"
            "严禁编造底稿中没有的数字、公司、项目或职责"
        ),
    )
    tech: list[str] = Field(default_factory=list, description="本条经历重点突出的技术栈")


class ResumeProject(BaseModel):
    """简历里的项目条目。"""

    name: str = Field(description="项目名称，与底稿一致")
    role: str = Field(default="", description="角色")
    period: str = Field(default="", description="时间区间")
    bullets: list[str] = Field(default_factory=list, description="要点，突出与 JD 的关联")
    tech: list[str] = Field(default_factory=list, description="技术栈")


class TailoredResume(BaseModel):
    """定制化简历的结构化表示（同时用于渲染 Markdown 与 Word）。"""

    target_title: str = Field(
        description=(
            "目标岗位名称，只写岗位本身"
            "（例如 '高级 Python 后端工程师（AI Agent 方向）'），"
            "不要带姓名，姓名由模板单独渲染"
        )
    )
    contact: ContactInfo = Field(default_factory=ContactInfo)
    summary: str = Field(
        description="个人简介 / 职业概述，3-4 句话，直接呼应 JD 的核心要求，不要空话"
    )
    core_skills: list[str] = Field(
        default_factory=list, description="核心技能标签，按与 JD 的相关度排序"
    )
    experiences: list[ResumeExperience] = Field(default_factory=list)
    projects: list[ResumeProject] = Field(default_factory=list)
    campus: list[ResumeExperience] = Field(
        default_factory=list,
        description=(
            "校园职务与组织经历。应届生没有工作经历时，这一节是软技能与执行力的主要佐证，"
            "要用「动作 + 规模 + 结果」改写；有丰富工作经验时可以精简或留空"
        ),
    )
    education: list[str] = Field(
        default_factory=list, description="教育经历，每条一行，例如 'XX大学 计算机科学与技术 本科 2016-2020'"
    )
    extras: list[str] = Field(
        default_factory=list, description="证书、开源、语言、获奖等补充信息"
    )
    ats_keywords: list[str] = Field(
        default_factory=list, description="本简历中已覆盖的 JD 关键词，用于自检"
    )
    change_notes: list[str] = Field(
        default_factory=list,
        description="相比底稿做了哪些调整及原因，便于候选人复核，不进入简历正文",
    )


# ---------------------------------------------------------------- 输出：求职信 / 面试


class CoverLetter(BaseModel):
    """求职信。"""

    greeting: str = Field(default="尊敬的招聘经理：", description="称呼")
    body: list[str] = Field(default_factory=list, description="正文段落，3-4 段")
    closing: str = Field(default="此致\\n敬礼", description="结尾敬语")


class InterviewQuestion(BaseModel):
    """一道预测面试题。"""

    question: str = Field(description="面试官可能问的问题")
    intent: str = Field(description="面试官问这题想考察什么")
    answer_outline: list[str] = Field(
        default_factory=list, description="回答要点提纲，必须基于候选人真实经历"
    )
    risk: str = Field(default="", description="回答时容易踩的坑")
    category: str = Field(
        default="技术",
        description="问题类型：技术/项目深挖/行为面试/职业规划/反问环节",
    )


class InterviewPrep(BaseModel):
    """面试准备包。"""

    questions: list[InterviewQuestion] = Field(default_factory=list)
    questions_to_ask: list[str] = Field(
        default_factory=list, description="建议候选人反问面试官的问题"
    )
    prep_focus: list[str] = Field(
        default_factory=list, description="面试前应重点复习的方向"
    )
