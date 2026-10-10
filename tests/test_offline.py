"""离线自测：不调用 API，验证解析、渲染、缓存等纯本地逻辑。

环境里没有装 pytest，所以这里用一个极简的断言收集器，直接用 python 运行：

    D:\\Project\\Anaconda\\envs\\langchain_env\\python.exe tests\\test_offline.py

加 --live 参数会额外跑一次真实 API 调用（会消耗 token）。
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
for _path in (str(SRC_DIR), str(PROJECT_ROOT)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from job_agent import prompts  # noqa: E402
from job_agent.config import Settings  # noqa: E402
from job_agent.llm import _build_system, extract_json  # noqa: E402
from job_agent.render import match_to_markdown, resume_to_markdown  # noqa: E402
from job_agent.schemas import (  # noqa: E402
    CandidateProfile,
    ContactInfo,
    DimensionScore,
    JDProfile,
    MatchReport,
    ResumeExperience,
    ResumeProject,
    SkillRequirement,
    TailoredResume,
)
from job_agent.storage import resolve_jd_path, slugify  # noqa: E402

_TESTS: list[tuple[str, callable]] = []


def test(func):
    _TESTS.append((func.__name__, func))
    return func


# ================================================================ 测试用例


@test
def test_extract_json_plain():
    assert extract_json('{"a": 1}') == {"a": 1}


@test
def test_extract_json_fenced():
    text = '好的，结果如下：\n```json\n{"a": [1, 2], "b": "中文"}\n```\n希望有帮助'
    assert extract_json(text) == {"a": [1, 2], "b": "中文"}


@test
def test_extract_json_with_prose_and_nested_braces():
    text = '我认为 {"outer": {"inner": 1}, "n": 2} 就是答案。'
    assert extract_json(text) == {"outer": {"inner": 1}, "n": 2}


@test
def test_extract_json_bad_input_raises():
    try:
        extract_json("这里完全没有 JSON")
    except ValueError:
        return
    raise AssertionError("应当抛出 ValueError")


@test
def test_build_system_forces_json_keyword():
    class Dummy(JDProfile):
        pass

    system = _build_system("你是分析师。", JDProfile)
    assert "json" in system.lower(), "system prompt 必须包含 json 字样"
    assert "JSON Schema" in system
    assert system.startswith("你是分析师。")


@test
def test_build_system_keeps_existing_json_mention():
    system = _build_system("请输出 json 格式。", JDProfile)
    assert system.count("你只能输出一个 json 对象") == 0


@test
def test_settings_rejects_bad_model():
    try:
        Settings(api_key="x", model="deepseek-v4-flash")
    except ValueError:
        return
    raise AssertionError("无效模型名应当被拒绝")


@test
def test_settings_accepts_valid_models():
    for model in ("deepseek-flash", "deepseek-v4-pro"):
        Settings(api_key="x", model=model)


@test
def test_slugify_handles_chinese_and_symbols():
    assert slugify("高级 Python 后端工程师（AI方向）") == "高级-Python-后端工程师-AI方向"
    assert slugify("") == "untitled"
    assert slugify("///") == "untitled"
    assert "/" not in slugify("a/b\\c:d")


@test
def test_slugify_truncates():
    assert len(slugify("字" * 200)) <= 60


@test
def test_resolve_jd_path_by_name_and_extension():
    by_name = resolve_jd_path("sample_ai_backend.txt")
    by_stem = resolve_jd_path("sample_ai_backend")
    assert by_name == by_stem
    assert by_name.is_file()


@test
def test_resolve_jd_path_missing_raises():
    try:
        resolve_jd_path("这个文件不存在.txt")
    except FileNotFoundError:
        return
    raise AssertionError("应当抛出 FileNotFoundError")


@test
def test_schemas_accept_minimal_payload():
    jd = JDProfile.model_validate(
        {
            "title": "Python 后端",
            "summary": "找一名后端",
            "must_have": [
                {"name": "Python", "level": "精通", "must_have": True}
            ],
        }
    )
    assert jd.company == "未提及"
    assert jd.must_have[0].level == "精通"

    candidate = CandidateProfile.model_validate(
        {"contact": {"name": "张三"}, "skills": ["Python"]}
    )
    assert candidate.contact.name == "张三"
    assert candidate.years_experience == 0.0


@test
def test_schemas_reject_bad_enum():
    try:
        SkillRequirement.model_validate(
            {"name": "Python", "level": "超级精通", "must_have": True}
        )
    except Exception:
        return
    raise AssertionError("非法枚举值应当校验失败")


@test
def test_match_markdown_renders():
    jd = JDProfile(
        title="AI 后端",
        summary="做 Agent 平台",
        must_have=[
            SkillRequirement(
                name="Python", level="精通", must_have=True, evidence="精通 Python"
            )
        ],
    )
    report = MatchReport(
        overall_score=78,
        verdict="推荐",
        dimensions=[DimensionScore(dimension="硬性技能", score=80, comment="基本满足")],
        strengths=["RAG 经验扎实"],
        weaknesses=["没有 K8s 生产经验"],
        strategy=["把 RAG 项目提到最前"],
        keyword_coverage=0.72,
    )
    md = match_to_markdown(report, jd, CandidateProfile())
    assert "78 / 100" in md
    assert "AI 后端" in md
    assert "推荐" in md
    assert "█" in md
    assert "72%" in md
    assert "没有 K8s 生产经验" in md


@test
def test_resume_markdown_renders_all_sections():
    resume = TailoredResume(
        target_title="张伟 - AI 后端工程师",
        contact=ContactInfo(name="张伟", phone="138", email="a@b.c", city="杭州"),
        summary="5 年 Python 后端经验。",
        core_skills=["Python", "LangChain"],
        experiences=[
            ResumeExperience(
                company="某科技",
                title="高级后端",
                period="2022-2024",
                bullets=["主导 RAG 问答系统"],
                tech=["FastAPI"],
            )
        ],
        education=["某大学 计算机 本科"],
        extras=["AWS 认证"],
        ats_keywords=["LangChain"],
        change_notes=["把 RAG 项目前置"],
    )
    md = resume_to_markdown(resume)
    for expected in (
        "# 张伟",
        "138 ｜ a@b.c ｜ 杭州",
        "## 个人简介",
        "## 核心技能",
        "## 工作经历",
        "### 某科技 — 高级后端",
        "## 教育背景",
        "## 其他",
        "主导 RAG 问答系统",
    ):
        assert expected in md, f"简历 Markdown 缺少：{expected}"
    # change_notes 是给用户复核用的，不应进入简历正文
    assert "把 RAG 项目前置" not in md


@test
def test_resume_docx_writes_file():
    from job_agent.render import resume_to_docx

    resume = TailoredResume(
        target_title="测试 - 工程师",
        contact=ContactInfo(name="测试", phone="138", email="t@e.st"),
        summary="测试简介。",
        core_skills=["Python"],
        experiences=[
            ResumeExperience(
                company="测试公司",
                title="工程师",
                period="2020-2024",
                bullets=["做了一些事情"],
                tech=["Python"],
            )
        ],
        education=["测试大学 计算机 本科"],
    )
    target = PROJECT_ROOT / "outputs" / "_test_resume.docx"
    path = resume_to_docx(resume, target)
    assert path.is_file()
    assert path.stat().st_size > 5000, "docx 体积异常，可能没写进内容"
    path.unlink()


@test
def test_resume_target_title_does_not_duplicate_name():
    """target_title 只应包含岗位名，姓名由抬头单独渲染，不能重复出现。"""
    resume = TailoredResume(
        target_title="高级 Python 后端工程师",
        contact=ContactInfo(name="张伟", phone="138"),
        summary="简介。",
    )
    md = resume_to_markdown(resume)
    assert md.count("张伟") == 1, f"姓名出现了 {md.count('张伟')} 次，应当只有 1 次"
    assert "**求职意向：高级 Python 后端工程师**" in md


@test
def test_resume_renders_when_name_missing():
    """档案里没填姓名时也要能正常渲染，不能出现空白标题。"""
    resume = TailoredResume(target_title="后端工程师", summary="简介。")
    md = resume_to_markdown(resume)
    assert md.startswith("# 后端工程师")
    assert "求职意向：后端工程师" in md


@test
def test_student_resume_puts_education_and_projects_before_skills():
    """应届生没有工作经历：不出现空的工作经历小节，校园经历单独成节且靠前。"""
    resume = TailoredResume(
        target_title="嵌入式软件工程师",
        contact=ContactInfo(name="冯天胤"),
        summary="大四在读，嵌入式软件方向。",
        core_skills=["STM32", "RT-Thread"],
        experiences=[],  # 应届生
        projects=[
            ResumeProject(
                name="基于 RT-Thread 的 WiFi 语音气象站",
                period="2025.03 - 2025.09",
                bullets=["主导 BSP 适配"],
                tech=["STM32", "RT-Thread"],
            )
        ],
        campus=[
            ResumeExperience(
                company="校学生资助管理部",
                title="部长",
                period="2024.03 - 2026.06",
                bullets=["统筹 20 余名成员分工"],
            )
        ],
        education=["郑州轻工业大学 计算机科学与技术 本科"],
        extras=["CET-4"],
    )
    md = resume_to_markdown(resume)

    assert "工作经历" not in md, "应届生简历不应出现空的工作经历小节"
    assert "## 校园经历" in md, "校园经历必须单独成节"
    assert "校学生资助管理部 — 部长" in md
    # 应届生版式：教育背景与项目经历都要排在核心技能之前
    assert md.index("## 教育背景") < md.index("## 核心技能")
    assert md.index("## 项目经历") < md.index("## 核心技能")
    assert md.index("## 校园经历") < md.index("## 核心技能")


@test
def test_experienced_resume_keeps_work_experience_first():
    """有工作经历时保持原顺序，且不出现空的校园经历小节。"""
    resume = TailoredResume(
        target_title="Python 后端工程师",
        contact=ContactInfo(name="李四"),
        summary="5 年经验。",
        core_skills=["Python"],
        experiences=[
            ResumeExperience(company="某公司", title="后端工程师", bullets=["做事"])
        ],
        education=["某大学 计算机 本科"],
    )
    md = resume_to_markdown(resume)

    assert "## 工作经历" in md
    assert "## 校园经历" not in md
    assert md.index("## 核心技能") < md.index("## 工作经历")
    assert md.index("## 工作经历") < md.index("## 教育背景")


@test
def test_campus_section_renders_in_docx():
    from docx import Document

    from job_agent.render import resume_to_docx

    resume = TailoredResume(
        target_title="嵌入式软件工程师",
        contact=ContactInfo(name="测试"),
        summary="大四在读。",
        projects=[ResumeProject(name="气象站项目", bullets=["做了驱动"])],
        campus=[
            ResumeExperience(
                company="校学生资助管理部", title="部长", bullets=["统筹 20 人"]
            )
        ],
        education=["某大学 计算机 本科"],
    )
    target = PROJECT_ROOT / "outputs" / "_test_campus.docx"
    resume_to_docx(resume, target)

    text = "\n".join(p.text for p in Document(str(target)).paragraphs)
    assert "校园经历" in text
    assert "校学生资助管理部 — 部长" in text
    assert "工作经历" not in text
    target.unlink()


@test
def test_degrades_gracefully_without_optional_deps():
    """屏蔽 rich / python-docx 后：核心渲染仍可用，Word 导出给出可读的安装提示。

    这条测试保证「只用 langchain-core + langchain-deepseek」这个约束是真的 ——
    docx / rich 必须是纯粹的增强项，缺了不能影响核心功能。
    """
    import json
    import subprocess
    import tempfile

    child = f'''
import json, sys
class Block:
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] in {{"rich", "docx"}}:
            raise ImportError("blocked for test: " + name)
        return None
sys.meta_path.insert(0, Block())
sys.path.insert(0, r"{SRC_DIR}")

from job_agent import ui
from job_agent.render import resume_to_docx, resume_to_markdown
from job_agent.schemas import ContactInfo, TailoredResume

r = TailoredResume(target_title="嵌入式软件工程师",
                   contact=ContactInfo(name="测试"), summary="简介。")
out = {{"has_rich": ui.HAS_RICH, "md_ok": resume_to_markdown(r).startswith("# 测试")}}

# 无 rich 时 ui 必须退化为朴素 print，不能抛异常
ui.info("plain fallback")
ui.warn("plain warn")
ui.step("plain step")

try:
    resume_to_docx(r, r"{PROJECT_ROOT}\\outputs\\_blocked.docx")
except ImportError as exc:
    out["docx"] = "ImportError"
    out["helpful"] = "python-docx" in str(exc) and "pip install" in str(exc)
else:
    out["docx"] = "unexpected-success"
    out["helpful"] = False

print("RESULT:" + json.dumps(out, ensure_ascii=False))
'''

    with tempfile.TemporaryDirectory() as tmp:
        script = Path(tmp) / "child.py"
        script.write_text(child, encoding="utf-8")
        proc = subprocess.run(
            [sys.executable, str(script)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

    assert proc.returncode == 0, f"子进程失败：\n{proc.stdout}\n{proc.stderr}"

    marker = [line for line in proc.stdout.splitlines() if line.startswith("RESULT:")]
    assert marker, f"拿不到子进程结果：\n{proc.stdout}\n{proc.stderr}"
    result = json.loads(marker[0][len("RESULT:") :])

    assert result["has_rich"] is False, "屏蔽 rich 后 HAS_RICH 应为 False"
    assert result["md_ok"] is True, "没有 docx/rich 时 Markdown 渲染仍须可用"
    assert result["docx"] == "ImportError", "缺 python-docx 时应抛 ImportError"
    assert result["helpful"] is True, "ImportError 里应包含安装指引"


@test
def test_prompt_builders_include_payload():
    assert "JD-TEXT" in prompts.jd_user_prompt("JD-TEXT")
    assert "底稿内容" in prompts.profile_user_prompt("底稿内容")
    combined = prompts.match_user_prompt('{"a":1}', '{"b":2}')
    assert '{"a":1}' in combined and '{"b":2}' in combined
    assert "反造假" in prompts.ANTI_FABRICATION or "禁止编造" in prompts.ANTI_FABRICATION


@test
def test_anti_fabrication_present_in_writer_prompts():
    for system in (prompts.RESUME_SYSTEM, prompts.COVER_LETTER_SYSTEM):
        assert "不得虚构" in system or "禁止编造" in system


@test
def test_sample_data_files_exist():
    assert (PROJECT_ROOT / "data" / "master_profile.md").is_file()
    assert (PROJECT_ROOT / "data" / "jds" / "sample_ai_backend.txt").is_file()


@test
def test_agent_tools_registered_and_documented():
    from job_agent.tools import AgentSession, build_tools

    tools = build_tools(AgentSession(settings=Settings(api_key="dummy")))
    names = [t.name for t in tools]
    for expected in (
        "load_job_description",
        "analyze_match",
        "generate_resume",
        "generate_cover_letter",
        "generate_interview_prep",
        "list_outputs",
    ):
        assert expected in names, f"缺少工具：{expected}"
    # 每个工具的 docstring 会成为模型看到的描述，不能为空
    for tool in tools:
        assert tool.description and len(tool.description) > 10, (
            f"工具 {tool.name} 缺少描述"
        )


@test
def test_tool_without_jd_gives_actionable_error():
    from job_agent.tools import AgentSession, build_tools

    session = AgentSession(settings=Settings(api_key="dummy"))
    analyze = next(t for t in build_tools(session) if t.name == "analyze_match")
    # ensure_jd 在没有 JD 时抛 ValueError，Agent 循环会把它转成文本回灌
    try:
        analyze.invoke({})
    except Exception as exc:
        assert "load_job_description" in str(exc)
        return
    raise AssertionError("没有载入 JD 时应当失败")


@test
def test_cli_global_flags_work_before_and_after_subcommand():
    import main as cli

    parser = cli.build_parser()

    before = parser.parse_args(["--verbose", "--model", "deepseek-v4-pro", "check"])
    after = parser.parse_args(["check", "--verbose", "--model", "deepseek-v4-pro"])

    assert before.verbose is True, "--verbose 放在子命令前应当生效"
    assert after.verbose is True, "--verbose 放在子命令后应当生效"
    assert before.model == after.model == "deepseek-v4-pro"


@test
def test_cli_defaults_and_subcommand_flags():
    import main as cli

    parser = cli.build_parser()

    plain = parser.parse_args(["check"])
    assert plain.verbose is False
    assert plain.model is None
    assert plain.no_cache is False

    tailor = parser.parse_args(["tailor", "sample_ai_backend", "--all", "--verbose"])
    assert tailor.jd == "sample_ai_backend"
    assert tailor.all is True
    assert tailor.verbose is True

    match = parser.parse_args(["match", "some_jd", "--refresh"])
    assert match.refresh is True
    assert match.jd == "some_jd"


@test
def test_cli_bare_invocation_guides_instead_of_erroring():
    """裸跑 `main.py` 不该报 argparse 错，而应打印引导并正常退出。"""
    import main as cli

    args = cli.build_parser().parse_args([])
    assert getattr(args, "command", None) is None, "无子命令时 command 应为 None"

    # 应当返回 0，而不是抛 SystemExit
    assert cli.main([]) == 0


@test
def test_cli_rejects_unknown_command():
    import main as cli

    parser = cli.build_parser()
    try:
        parser.parse_args(["nonexistent-command"])
    except SystemExit:
        return
    raise AssertionError("未知子命令应当报错退出")


@test
def test_session_context_tells_model_what_is_already_loaded():
    """预载 JD 后必须告诉模型，否则它会反复要求用户重贴 JD。"""
    from job_agent.agent import _session_context
    from job_agent.tools import AgentSession

    session = AgentSession(settings=Settings(api_key="dummy"))

    empty = _session_context(session)
    assert "尚未载入 JD" in empty
    assert "已经载入" not in empty

    session.jd = JDProfile(title="AI 后端工程师", summary="做 Agent 平台")
    loaded = _session_context(session)
    assert "AI 后端工程师" in loaded
    assert "不要再调用 load_job_description" in loaded
    assert "analyze_match" in loaded


@test
def test_runner_rebuilds_system_message_each_turn():
    """会话状态变化后，system prompt 必须跟着更新。"""
    from job_agent.agent import AgentRunner
    from job_agent.tools import AgentSession

    session = AgentSession(settings=Settings(api_key="dummy"))
    runner = AgentRunner(session=session)

    first = str(runner.history[0].content)
    assert "尚未载入 JD" in first

    session.jd = JDProfile(title="数据工程师", summary="做数仓")
    runner.reset()
    second = str(runner.history[0].content)
    assert "数据工程师" in second
    assert "尚未载入 JD" not in second


# ================================================================ 运行器


def _run_live() -> int:
    from job_agent.config import get_settings
    from job_agent.llm import check_connectivity

    print("\n=== 真实 API 调用 ===")
    ok, message = check_connectivity(get_settings())
    print(("  ✔ " if ok else "  ✘ ") + message)
    return 0 if ok else 1


def main() -> int:
    passed = 0
    failed: list[tuple[str, str]] = []

    for name, func in _TESTS:
        try:
            func()
        except Exception:  # noqa: BLE001
            failed.append((name, traceback.format_exc()))
            print(f"  ✘ {name}")
        else:
            passed += 1
            print(f"  ✔ {name}")

    print(f"\n通过 {passed}/{len(_TESTS)}")

    if failed:
        print("\n失败详情：")
        for name, tb in failed:
            print(f"\n--- {name} ---\n{tb}")

    exit_code = 1 if failed else 0

    if "--live" in sys.argv:
        exit_code |= _run_live()

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
