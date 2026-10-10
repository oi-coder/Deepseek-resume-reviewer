"""Agent 主循环：bind_tools + 手工执行 tool_calls。

因为环境里没有 langgraph，这里用最朴素但完全等价的方式实现 ReAct 循环：

    模型输出 -> 若有 tool_calls 就执行并回灌 ToolMessage -> 再问模型 -> 直到没有工具调用

好处是零额外依赖，行为可预测、好调试。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.tools import BaseTool

from .config import EFFORT_WRITE, Settings, get_settings
from .llm import USAGE, get_llm
from .prompts import AGENT_SYSTEM
from .tools import AgentSession, build_tools

#: 单轮对话最多允许的工具调用步数，防止死循环烧 token
DEFAULT_MAX_STEPS = 12


def _session_context(session: AgentSession) -> str:
    """把会话里已有的状态渲染成一段说明，喂给模型。

    没有这段说明，模型不知道 JD 已经被预载，会反复要求用户重贴 JD。
    """
    lines = ["【当前会话已知信息】"]

    if session.jd is not None:
        lines.append(
            f"- 已载入 JD：{session.jd.title}（{session.jd.company}），"
            f"硬性要求 {len(session.jd.must_have)} 条。"
            "**不要再调用 load_job_description**，可以直接调用 analyze_match。"
        )
    else:
        lines.append(
            "- 尚未载入 JD。如果用户提供了 JD 原文，先调用 load_job_description。"
        )

    if session.candidate is not None:
        lines.append(
            f"- 已载入候选人档案：{len(session.candidate.skills)} 项技能、"
            f"{len(session.candidate.experiences)} 段工作经历。"
        )
    else:
        lines.append(
            "- 候选人档案尚未载入；首次需要时会自动解析 data/master_profile.md。"
        )

    if session.match is not None:
        lines.append(
            f"- 已生成匹配报告（{session.match.overall_score} 分 / "
            f"{session.match.verdict}），可直接引用。"
        )
    if session.resume is not None:
        lines.append("- 已生成定制简历。")

    return "\n".join(lines)


@dataclass
class AgentRunner:
    """带记忆的一轮会话。"""

    session: AgentSession = field(default_factory=AgentSession)
    max_steps: int = DEFAULT_MAX_STEPS
    verbose: bool = False
    history: list[BaseMessage] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.settings: Settings = self.session.settings
        self.tools: list[BaseTool] = build_tools(self.session)
        self.tool_map = {t.name: t for t in self.tools}
        self.llm = get_llm(
            settings=self.settings, effort=EFFORT_WRITE, temperature=0.3
        ).bind_tools(self.tools)
        self.history = [self._system_message()]

    # ------------------------------------------------------------ 内部

    def _system_message(self) -> SystemMessage:
        """system prompt + 实时会话状态，每轮都重建以反映最新进展。"""
        return SystemMessage(f"{AGENT_SYSTEM}\n\n{_session_context(self.session)}")

    def _trim_history(self, keep: int = 24) -> None:
        """只保留 system + 最近若干条消息，避免上下文无限膨胀。"""
        if len(self.history) <= keep + 1:
            return
        head = self.history[:1]
        tail = self.history[-(keep):]
        # 截断点若落在 ToolMessage 上会破坏 tool_call 配对，向前对齐
        while tail and isinstance(tail[0], ToolMessage):
            tail = tail[1:]
        self.history = head + tail

    def _execute(self, call: dict) -> str:
        name = call.get("name", "")
        args = call.get("args") or {}
        tool = self.tool_map.get(name)
        if tool is None:
            return f"错误：不存在名为 {name} 的工具。可用工具：{', '.join(self.tool_map)}"
        try:
            result = tool.invoke(args)
            return str(result)
        except Exception as exc:  # noqa: BLE001 - 工具异常要如实回灌给模型
            return f"工具 {name} 执行失败：{type(exc).__name__}: {exc}"

    # ------------------------------------------------------------ 对外

    def chat(self, message: str) -> str:
        """处理一条用户输入，返回最终回复文本。"""
        # 每轮刷新 system prompt，让模型看到最新的会话状态
        if self.history and isinstance(self.history[0], SystemMessage):
            self.history[0] = self._system_message()
        self.history.append(HumanMessage(message))

        for step in range(self.max_steps):
            response: AIMessage = self.llm.invoke(self.history)
            USAGE.add_message(response)
            self.history.append(response)

            tool_calls = getattr(response, "tool_calls", None) or []
            if not tool_calls:
                self._trim_history()
                return str(response.content).strip() or "（模型没有返回内容）"

            for call in tool_calls:
                name = call.get("name", "")
                if self.verbose:
                    print(f"  [tool {step + 1}] {name}({call.get('args')})")
                output = self._execute(call)
                if self.verbose:
                    preview = output[:200].replace("\n", " ")
                    print(f"  [tool {step + 1}] -> {preview}...")
                self.history.append(
                    ToolMessage(content=output, tool_call_id=call.get("id", ""))
                )

        self._trim_history()
        return (
            f"⚠️ 已达到单轮最大工具调用步数（{self.max_steps}），提前停止。"
            "请把需求拆得更具体一些，或直接说「用一句话总结当前结论」。"
        )

    def reset(self) -> None:
        """清空对话历史，但保留已解析的 JD / 简历等会话状态。"""
        self.history = [self._system_message()]


def create_runner(
    session: AgentSession | None = None,
    *,
    settings: Settings | None = None,
    verbose: bool = False,
) -> AgentRunner:
    """便捷构造函数。"""
    settings = settings or get_settings()
    session = session or AgentSession(settings=settings)
    return AgentRunner(session=session, verbose=verbose or settings.verbose)
