"""LLM 工厂 + 结构化输出封装。

这个模块集中处理了 DeepSeek「思考模型」的一个关键坑：

    ChatDeepSeek 的 with_structured_output() 默认走 function calling 的
    tool_choice="required"，而思考模式不支持强制 tool_choice，会直接返回::

        Error code: 400 - Thinking mode does not support this tool_choice

所以本模块统一改用 method="json_mode"，并做三件事保证成功率：

1. 把 Pydantic 的 JSON Schema 注入 system prompt（同时也满足 json_mode
   要求「提示词中必须出现 json 字样」的硬性条件）；
2. 解析失败时自动重试，并把失败原因回灌给模型；
3. 重试耗尽后退化为「原始文本 + 手工提取 JSON」，尽最大努力抢救结果。

另外注意：ChatPromptTemplate 会把 prompt 里的 JSON 示例花括号当成模板变量，
所以这里一律用 SystemMessage / HumanMessage 手工拼消息，绕开转义问题。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, TypeVar

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
)
from langchain_deepseek import ChatDeepSeek
from pydantic import BaseModel

from .config import FLASH_MODEL, Settings, get_settings

SchemaT = TypeVar("SchemaT", bound=BaseModel)


# ---------------------------------------------------------------- 用量统计


@dataclass
class Usage:
    """进程内累计的 token 用量，方便估算花费。"""

    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    failures: int = 0

    def add_message(self, message: BaseMessage | None) -> None:
        if message is None:
            return
        meta = getattr(message, "usage_metadata", None) or {}
        self.calls += 1
        self.input_tokens += int(meta.get("input_tokens") or 0)
        self.output_tokens += int(meta.get("output_tokens") or 0)

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def summary(self) -> str:
        return (
            f"调用 {self.calls} 次 | 输入 {self.input_tokens} tok | "
            f"输出 {self.output_tokens} tok | 合计 {self.total_tokens} tok"
            + (f" | 解析失败重试 {self.failures} 次" if self.failures else "")
        )


USAGE = Usage()


# ---------------------------------------------------------------- LLM 工厂


def get_llm(
    *,
    settings: Settings | None = None,
    model: str | None = None,
    temperature: float | None = None,
    effort: str | None = None,
    max_tokens: int | None = None,
    streaming: bool = False,
) -> ChatDeepSeek:
    """构造一个 ChatDeepSeek 实例。

    effort 会映射到 API 的 reasoning_effort，思考模型支持 low / high / max。
    """
    settings = settings or get_settings()
    kwargs: dict[str, Any] = {
        "model": model or settings.model or FLASH_MODEL,
        "api_key": settings.require_api_key(),
        "temperature": settings.temperature if temperature is None else temperature,
        "timeout": settings.timeout,
        "max_retries": settings.max_retries,
        "streaming": streaming,
    }
    if effort:
        kwargs["reasoning_effort"] = effort
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens
    return ChatDeepSeek(**kwargs)


# ---------------------------------------------------------------- JSON 抢救


_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)


def extract_json(text: str) -> Any:
    """从模型输出里尽最大努力抠出一个 JSON 对象。

    依次尝试：直接解析 -> 去 markdown 代码围栏 -> 花括号配对扫描。
    """
    if not text:
        raise ValueError("空输出")

    candidates: list[str] = [text.strip()]

    for match in _FENCE_RE.finditer(text):
        candidates.append(match.group(1).strip())

    # 花括号配对扫描，能找到第一个完整的 JSON 对象
    depth = 0
    start = -1
    for index, char in enumerate(text):
        if char == "{":
            if depth == 0:
                start = index
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0 and start >= 0:
                candidates.append(text[start : index + 1])
                start = -1

    errors: list[str] = []
    for candidate in candidates:
        if not candidate:
            continue
        try:
            return json.loads(candidate)
        except json.JSONDecodeError as exc:
            errors.append(str(exc))

    raise ValueError(f"无法从模型输出中解析 JSON：{errors[:2]}")


def _schema_text(schema: type[BaseModel]) -> str:
    return json.dumps(schema.model_json_schema(), ensure_ascii=False, indent=2)


def _build_system(system: str, schema: type[BaseModel]) -> str:
    """把 JSON Schema 追加进 system prompt，并保证出现 'json' 字样。"""
    parts = [system.strip()]
    if "json" not in system.lower():
        parts.append("你只能输出一个 json 对象，不要输出解释、客套话或 markdown 代码块。")
    parts.append(
        "输出必须严格符合下面的 JSON Schema"
        "（字段名、枚举值、类型都要对得上，不要增删字段）：\n"
        f"{_schema_text(schema)}"
    )
    return "\n\n".join(parts)


# ---------------------------------------------------------------- 结构化调用


def invoke_structured(
    schema: type[SchemaT],
    system: str,
    user: str,
    *,
    settings: Settings | None = None,
    llm: ChatDeepSeek | None = None,
    effort: str | None = None,
    temperature: float | None = None,
    retries: int = 2,
    extra_messages: list[BaseMessage] | None = None,
) -> SchemaT:
    """调用模型并返回校验过的 Pydantic 对象。

    这是整个项目所有结构化抽取的统一入口。
    """
    settings = settings or get_settings()
    llm = llm or get_llm(
        settings=settings, effort=effort, temperature=temperature
    )

    system_prompt = _build_system(system, schema)
    messages: list[BaseMessage] = [SystemMessage(system_prompt)]
    if extra_messages:
        messages.extend(extra_messages)
    messages.append(HumanMessage(user))

    structured = llm.with_structured_output(schema, method="json_mode", include_raw=True)

    last_error: Exception | None = None

    for attempt in range(retries + 1):
        try:
            result = structured.invoke(messages)
        except Exception as exc:  # noqa: BLE001 - 网络/API 异常统一走重试
            last_error = exc
            USAGE.failures += 1
            if attempt >= retries:
                break
            continue

        # include_raw=True 时返回 {"raw":..., "parsed":..., "parsing_error":...}
        raw = result.get("raw") if isinstance(result, dict) else None
        parsed = result.get("parsed") if isinstance(result, dict) else result
        parsing_error = result.get("parsing_error") if isinstance(result, dict) else None

        USAGE.add_message(raw)

        if parsed is not None and parsing_error is None:
            return parsed  # type: ignore[return-value]

        last_error = parsing_error or ValueError("模型未返回可解析的结构化结果")
        USAGE.failures += 1

        if attempt < retries:
            raw_text = getattr(raw, "content", "") or ""
            messages.append(AIMessage(raw_text[:2000]))
            messages.append(
                HumanMessage(
                    "上一次输出无法通过校验，错误是："
                    f"{str(last_error)[:600]}\n"
                    "请重新输出一个**完整且合法**的 json 对象，"
                    "只输出 json，不要任何多余文字。"
                )
            )

    # ---------- 兜底：退化成纯文本，手工抠 JSON ----------
    try:
        raw_message = llm.invoke(messages[:1] + [HumanMessage(user)])
        USAGE.add_message(raw_message)
        data = extract_json(str(raw_message.content))
        return schema.model_validate(data)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            f"结构化输出失败（schema={schema.__name__}）：{last_error or exc}"
        ) from (last_error or exc)


def invoke_text(
    system: str,
    user: str,
    *,
    settings: Settings | None = None,
    llm: ChatDeepSeek | None = None,
    effort: str | None = None,
    temperature: float | None = None,
) -> str:
    """普通文本调用，返回字符串内容。"""
    settings = settings or get_settings()
    llm = llm or get_llm(settings=settings, effort=effort, temperature=temperature)
    message = llm.invoke([SystemMessage(system), HumanMessage(user)])
    USAGE.add_message(message)
    return str(message.content)


def stream_text(
    system: str,
    user: str,
    *,
    settings: Settings | None = None,
    effort: str | None = None,
    temperature: float | None = None,
):
    """流式文本生成，逐块 yield 字符串。"""
    settings = settings or get_settings()
    llm = get_llm(
        settings=settings,
        effort=effort,
        temperature=temperature,
        streaming=True,
    )
    for chunk in llm.stream([SystemMessage(system), HumanMessage(user)]):
        text = chunk.content
        if text:
            yield str(text)


def check_connectivity(settings: Settings | None = None) -> tuple[bool, str]:
    """跑一次最小请求，验证 key / 模型名 / 网络是否都通。"""
    settings = settings or get_settings()
    try:
        llm = get_llm(settings=settings, temperature=0.0, effort="low")
        reply = llm.invoke("回复两个字：正常")
        USAGE.add_message(reply)
        return True, f"模型 {settings.model} 连接正常，返回：{reply.content!r}"
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"
