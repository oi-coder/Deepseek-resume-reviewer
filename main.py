#!/usr/bin/env python
"""求职 Agent 命令行入口。

用法速查（在项目根目录执行）::

    python main.py check                          # 验证 API Key / 模型 / 网络
    python main.py profile                        # 解析简历底稿为结构化档案
    python main.py parse-jd 字节AI后端             # 只解析 JD
    python main.py match 字节AI后端                # 解析 JD + 匹配度分析
    python main.py tailor 字节AI后端               # 全流程：分析 + 生成简历
    python main.py tailor 字节AI后端 --all         # 再加求职信 + 面试题
    python main.py agent                          # 进入可多轮对话的 Agent
    python main.py agent --jd 字节AI后端           # 预载 JD 后进入 Agent

JD 参数可以是：绝对路径、相对路径，或 data/jds 下的文件名（可省略扩展名）。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# 让脚本在未安装为包的情况下也能 import src.job_agent
PROJECT_ROOT = Path(__file__).resolve().parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

try:
    from job_agent import ui  # noqa: E402
    from job_agent.agent import create_runner  # noqa: E402
    from job_agent.config import (  # noqa: E402
        FLASH_MODEL,
        PRO_MODEL,
        Settings,
        get_settings,
    )
    from job_agent.llm import USAGE, check_connectivity  # noqa: E402
    from job_agent.pipeline import run_pipeline  # noqa: E402
    from job_agent.profile import build_candidate_profile  # noqa: E402
    from job_agent.jd import parse_jd_file  # noqa: E402
    from job_agent.storage import (  # noqa: E402
        clear_cache,
        dump_json,
        read_text,
        resolve_jd_path,
    )
    from job_agent.tools import AgentSession  # noqa: E402
except ModuleNotFoundError as exc:
    # 最常见的情况就是解释器选错了，原始 traceback 对新手很不友好，这里给人话
    _missing = exc.name or "未知模块"
    _interpreter = sys.executable
    _env_python = r"D:\Project\Anaconda\envs\langchain_env\python.exe"
    print(
        f"""
✘ 缺少依赖：No module named '{_missing}'

  你当前用的解释器是：
    {_interpreter}

  本项目需要 conda 环境 langchain_env（依赖装在它里面）。
  请从下面三种做法里挑一种：

  1) 直接指定解释器（最省事）：
       "{_env_python}" main.py check

  2) 先激活环境再运行：
       conda activate langchain_env
       python main.py check

  3) 在当前解释器里补装依赖：
       "{_interpreter}" -m pip install -r requirements.txt

  PyCharm 用户：Settings → Project: AI_agent → Python Interpreter
  改成 {_env_python}
  ⚠ 不要选项目里的 .venv —— 那是 PyCharm 建的空环境，只有 pip，什么依赖都没有。
""",
        file=sys.stderr,
    )
    raise SystemExit(2)


# ================================================================ 子命令


def cmd_check(args, settings: Settings) -> int:
    ui.step(f"检查连接（模型 {settings.model}）…")
    ok, message = check_connectivity(settings)
    if ok:
        ui.success(message)
    else:
        ui.error(message)
        ui.info("排查建议：① .env 里的 DEEPSEEK_API_KEY 是否正确；"
                "② 网络能否访问 api.deepseek.com；③ --model 是否是 "
                f"{FLASH_MODEL} 或 {PRO_MODEL}")
    return 0 if ok else 1


def cmd_profile(args, settings: Settings) -> int:
    ui.step("解析简历底稿…")
    profile = build_candidate_profile(settings=settings, refresh=args.refresh)

    if args.json:
        ui.raw(dump_json(profile))
        return 0

    contact = profile.contact
    ui.panel(
        "候选人档案",
        f"{contact.name or '（未填姓名）'} | {profile.headline or '（无定位）'}\n"
        f"经验：{profile.years_experience} 年 | 技能 {len(profile.skills)} 项 | "
        f"工作 {len(profile.experiences)} 段 | 项目 {len(profile.projects)} 个",
    )
    if profile.skills:
        ui.info("技能：" + "、".join(profile.skills))
    ui.info("档案已缓存到 .cache/candidate_profile.json")

    if settings.verbose:
        ui.raw(dump_json(profile))
    return 0


def cmd_parse_jd(args, settings: Settings) -> int:
    path = resolve_jd_path(args.jd)
    ui.step(f"解析 JD：{path.name}")
    jd = parse_jd_file(path, settings=settings, refresh=args.refresh)

    if args.json:
        ui.raw(dump_json(jd))
        return 0

    ui.panel(
        f"{jd.title}",
        f"公司：{jd.company} | 职级：{jd.seniority} | 地点：{jd.location}\n"
        f"领域：{jd.domain} | 用工性质：{jd.employment_type}\n\n{jd.summary}",
    )

    if jd.must_have:
        ui.table(
            "硬性要求",
            ["技能", "要求等级", "分类"],
            [[s.name, s.level, s.category] for s in jd.must_have],
        )
    if jd.nice_to_have:
        ui.info("加分项：" + "；".join(jd.nice_to_have))
    if jd.keywords:
        ui.info("ATS 关键词：" + "、".join(jd.keywords))
    if jd.hidden_expectations:
        ui.warn("隐含期待 / 风险：")
        for item in jd.hidden_expectations:
            ui.raw(f"  • {item}")
    return 0


def cmd_match(args, settings: Settings) -> int:
    result = run_pipeline(
        jd_path=args.jd,
        with_resume=False,
        refresh=args.refresh,
        settings=settings,
        progress=ui.step,
    )
    ui.rule("匹配度分析")
    ui.markdown(result.match_markdown)
    for path in result.artifacts:
        ui.success(f"报告已保存：{path}")
    return 0


def cmd_tailor(args, settings: Settings) -> int:
    result = run_pipeline(
        jd_path=args.jd,
        with_resume=True,
        with_cover_letter=args.all or args.cover_letter,
        with_interview=args.all or args.interview,
        refresh=args.refresh,
        settings=settings,
        progress=ui.step,
    )

    ui.rule("匹配度分析")
    ui.markdown(result.match_markdown)

    if result.resume:
        ui.rule("定制简历预览")
        ui.markdown(result.resume_markdown)
        if result.resume.change_notes:
            ui.rule("相对底稿的改动")
            for note in result.resume.change_notes:
                ui.raw(f"  • {note}")

    if result.cover_letter:
        ui.rule("求职信")
        ui.raw(result.cover_letter.greeting + "\n")
        for paragraph in result.cover_letter.body:
            ui.raw(paragraph + "\n")

    if result.interview:
        ui.rule("面试准备")
        for index, item in enumerate(result.interview.questions, 1):
            ui.raw(f"{index}. [{item.category}] {item.question}")
            ui.raw(f"   考察点：{item.intent}")

    ui.rule("产出文件")
    for path in result.artifacts:
        ui.success(str(path))

    return 0


def cmd_agent(args, settings: Settings) -> int:
    session = AgentSession(settings=settings)
    runner = create_runner(session, settings=settings, verbose=settings.verbose)

    preloaded = False
    if args.jd:
        path = resolve_jd_path(args.jd)
        # 走缓存：同一份 JD 不必每次启动都重新解析一遍
        session.ensure_jd(read_text(path))
        preloaded = True
        ui.success(f"已预载 JD：{session.jd.title}（{session.jd.company}）")

    ui.rule("求职 Agent")
    ui.info("直接用中文提需求即可，例如：「分析我和这个岗位的匹配度」")
    ui.info("内置命令：/outputs  /reset  /quit")
    if not preloaded:
        ui.info("还没有 JD —— 直接把 JD 原文整段粘贴进来，我会自动解析。")

    while True:
        try:
            message = ui.prompt("\n你 > ").strip()
        except (EOFError, KeyboardInterrupt):
            ui.raw("")
            break

        if not message:
            continue

        lowered = message.lower()
        if lowered in {"/quit", "/exit", "/q"}:
            break
        if lowered == "/reset":
            runner.reset()
            ui.success("对话历史已清空（已解析的 JD / 简历仍在会话中）")
            continue
        if lowered == "/outputs":
            from job_agent.tools import build_tools

            listing = next(
                t for t in build_tools(session) if t.name == "list_outputs"
            ).invoke({})
            ui.raw(str(listing))
            continue

        try:
            with ui.spinner("思考中…"):
                reply = runner.chat(message)
        except KeyboardInterrupt:
            ui.warn("已中断本次回答")
            continue
        except Exception as exc:  # noqa: BLE001 - 单轮失败不该退出整个会话
            ui.error(f"{type(exc).__name__}: {exc}")
            continue

        ui.raw("")
        ui.markdown(reply)

    if session.artifacts:
        ui.rule("本次会话生成的文件")
        for path in dict.fromkeys(session.artifacts):
            ui.success(str(path))
    ui.info(f"用量统计：{USAGE.summary()}")
    return 0


def cmd_clean(args, settings: Settings) -> int:
    count = clear_cache()
    ui.success(f"已清理 {count} 个缓存文件")
    return 0


# ================================================================ 参数解析


def _add_global_options(parser: argparse.ArgumentParser, *, suppress: bool = False) -> None:
    """给解析器挂上全局参数。

    suppress=True 用于子解析器的副本：默认值设为 SUPPRESS，
    这样用户没写这些参数时就不会覆盖主解析器已经解析出来的值，
    从而让 `--verbose` 放在子命令前面或后面都能生效。
    """
    default = argparse.SUPPRESS if suppress else None
    parser.add_argument(
        "--model",
        default=default,
        choices=[FLASH_MODEL, PRO_MODEL],
        help=f"使用的模型，默认 {FLASH_MODEL}",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        default=(argparse.SUPPRESS if suppress else False),
        help="输出详细日志",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        default=(argparse.SUPPRESS if suppress else False),
        help="禁用结果缓存",
    )


def build_parser() -> argparse.ArgumentParser:
    # 主解析器：全局参数带真实默认值
    global_parent = argparse.ArgumentParser(add_help=False)
    _add_global_options(global_parent)

    # 子解析器副本：默认值 SUPPRESS，避免把主解析器的结果冲掉
    sub_global = argparse.ArgumentParser(add_help=False)
    _add_global_options(sub_global, suppress=True)

    parser = argparse.ArgumentParser(
        prog="main.py",
        description="招聘 JD 解析 + 简历定制 Agent（LangChain + DeepSeek）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
        parents=[global_parent],
    )

    sub = parser.add_subparsers(dest="command", required=False)

    sub.add_parser(
        "check",
        parents=[sub_global],
        help="检查 API Key / 模型 / 网络是否可用",
    ).set_defaults(func=cmd_check)

    p_profile = sub.add_parser(
        "profile", parents=[sub_global], help="解析简历底稿为结构化档案"
    )
    p_profile.add_argument("--refresh", action="store_true", help="忽略缓存重新解析")
    p_profile.add_argument("--json", action="store_true", help="输出原始 JSON")
    p_profile.set_defaults(func=cmd_profile)

    p_jd = sub.add_parser("parse-jd", parents=[sub_global], help="解析一份 JD")
    p_jd.add_argument("jd", help="JD 文件路径或 data/jds 下的文件名")
    p_jd.add_argument("--refresh", action="store_true", help="忽略缓存重新解析")
    p_jd.add_argument("--json", action="store_true", help="输出原始 JSON")
    p_jd.set_defaults(func=cmd_parse_jd)

    p_match = sub.add_parser(
        "match", parents=[sub_global], help="JD 与候选人的匹配度分析"
    )
    p_match.add_argument("jd", help="JD 文件路径或文件名")
    p_match.add_argument("--refresh", action="store_true", help="忽略缓存")
    p_match.set_defaults(func=cmd_match)

    p_tailor = sub.add_parser(
        "tailor", parents=[sub_global], help="全流程：分析匹配度并生成定制简历"
    )
    p_tailor.add_argument("jd", help="JD 文件路径或文件名")
    p_tailor.add_argument("--refresh", action="store_true", help="忽略缓存")
    p_tailor.add_argument("--cover-letter", action="store_true", help="额外生成求职信")
    p_tailor.add_argument("--interview", action="store_true", help="额外生成面试题")
    p_tailor.add_argument("--all", action="store_true", help="生成求职信 + 面试题")
    p_tailor.set_defaults(func=cmd_tailor)

    p_agent = sub.add_parser(
        "agent", parents=[sub_global], help="进入可多轮对话的 Agent"
    )
    p_agent.add_argument("--jd", default=None, help="可选：启动时预载的 JD")
    p_agent.set_defaults(func=cmd_agent)

    sub.add_parser(
        "clean", parents=[sub_global], help="清理解析缓存"
    ).set_defaults(func=cmd_clean)

    return parser


def _print_quickstart() -> None:
    """没带子命令时给友好引导，而不是甩一段 argparse 报错。"""
    ui.rule("求职 Agent")
    ui.info("你没告诉我要做什么。第一次用，建议按这个顺序来：")
    ui.raw(
        "\n"
        "  1. python main.py check\n"
        "       先确认 API Key / 模型 / 网络是否通\n"
        "\n"
        "  2. python main.py profile\n"
        "       看看 Agent 把你的简历底稿理解成了什么\n"
        "\n"
        "  3. python main.py tailor sample_embedded_campus --all\n"
        "       全流程：匹配分析 + 定制简历 + 求职信 + 面试题\n"
        "\n"
        "其他命令：\n"
        "  parse-jd <JD>    只解析 JD\n"
        "  match    <JD>    只做匹配度分析\n"
        "  agent  [--jd X]  进入可多轮对话的 Agent\n"
        "  clean            清理解析缓存\n"
    )
    ui.info("JD 参数可以是文件路径，也可以是 data/jds 下的文件名（可省略扩展名）")
    ui.info("查看全部参数：python main.py --help")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    # 裸跑 `python main.py` 时给出引导，而不是报 "arguments are required"
    if not getattr(args, "command", None):
        _print_quickstart()
        return 0

    settings = get_settings()
    # 全局参数可能写在子命令前面或后面，两种位置都要认
    if getattr(args, "model", None):
        settings.model = args.model
    if getattr(args, "verbose", False):
        settings.verbose = True
    if getattr(args, "no_cache", False):
        settings.use_cache = False

    try:
        return int(args.func(args, settings) or 0)
    except FileNotFoundError as exc:
        ui.error(str(exc))
        return 2
    except KeyboardInterrupt:
        ui.warn("已取消")
        return 130
    except Exception as exc:  # noqa: BLE001 - CLI 顶层兜底，给可读报错
        ui.error(f"{type(exc).__name__}: {exc}")
        if settings.verbose:
            import traceback

            traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
