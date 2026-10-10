"""终端输出辅助。

优先用 rich 渲染（表格、Markdown 高亮），没装 rich 时退化为朴素 print。
另外顺手把 Windows 控制台切成 UTF-8，避免中文输出变成乱码。
"""

from __future__ import annotations

import sys
from contextlib import contextmanager

# Windows 控制台默认 GBK，直接打印中文/emoji 容易乱码或抛 UnicodeEncodeError
for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except (AttributeError, ValueError):
        pass

try:
    from rich.console import Console
    from rich.markdown import Markdown
    from rich.panel import Panel
    from rich.table import Table

    _console = Console()
    HAS_RICH = True
except ImportError:  # pragma: no cover - 取决于环境
    _console = None
    HAS_RICH = False


# ---------------------------------------------------------------- 基础输出


def info(message: str) -> None:
    if HAS_RICH:
        _console.print(f"[cyan]ℹ[/cyan] {message}")
    else:
        print(f"[信息] {message}")


def success(message: str) -> None:
    if HAS_RICH:
        _console.print(f"[green]✔[/green] {message}")
    else:
        print(f"[成功] {message}")


def warn(message: str) -> None:
    if HAS_RICH:
        _console.print(f"[yellow]⚠[/yellow] {message}")
    else:
        print(f"[警告] {message}")


def error(message: str) -> None:
    if HAS_RICH:
        _console.print(f"[red]✘[/red] {message}")
    else:
        print(f"[错误] {message}", file=sys.stderr)


def step(message: str) -> None:
    """显示一个进行中的步骤。"""
    if HAS_RICH:
        _console.print(f"[bold blue]▸[/bold blue] {message}")
    else:
        print(f"==> {message}")


def rule(title: str = "") -> None:
    if HAS_RICH:
        _console.rule(f"[bold]{title}[/bold]" if title else "")
    else:
        print(f"\n{'=' * 8} {title} {'=' * 8}" if title else "=" * 40)


def panel(title: str, body: str) -> None:
    if HAS_RICH:
        _console.print(Panel(body, title=title, border_style="blue", expand=False))
    else:
        print(f"--- {title} ---\n{body}\n")


def markdown(text: str) -> None:
    """渲染 Markdown 文本。"""
    if HAS_RICH:
        _console.print(Markdown(text))
    else:
        print(text)


def raw(text: str) -> None:
    """原样打印，不做任何富文本解析。"""
    if HAS_RICH:
        _console.print(text, markup=False, highlight=False)
    else:
        print(text)


def table(title: str, headers: list[str], rows: list[list[str]]) -> None:
    if HAS_RICH:
        tbl = Table(title=title, show_lines=False, header_style="bold cyan")
        for header in headers:
            tbl.add_column(header, overflow="fold")
        for row in rows:
            tbl.add_row(*[str(cell) for cell in row])
        _console.print(tbl)
    else:
        print(f"\n{title}")
        print(" | ".join(headers))
        print("-" * 60)
        for row in rows:
            print(" | ".join(str(cell) for cell in row))


def prompt(message: str) -> str:
    """读取用户输入，终止符 Ctrl+C / EOF 由调用方处理。"""
    if HAS_RICH:
        return _console.input(f"[bold green]{message}[/bold green]")
    return input(message)


@contextmanager
def spinner(message: str):
    """转圈提示；没装 rich 时什么都不做。"""
    if HAS_RICH:
        with _console.status(f"[dim]{message}[/dim]"):
            yield
    else:
        print(f"... {message}")
        yield
