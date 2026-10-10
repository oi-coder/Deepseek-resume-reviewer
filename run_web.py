#!/usr/bin/env python
"""启动求职 Agent 的 Web 界面。

用法::

    python run_web.py                      # 默认 http://127.0.0.1:8000
    python run_web.py --port 8123
    python run_web.py --host 0.0.0.0       # 允许局域网访问（注意 API Key 风险）

首次使用建议先确认环境和 Key 没问题：

    python main.py check
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _preflight() -> None:
    """提前检查依赖，报错要说人话（和 main.py 保持一致的提示风格）。"""
    missing: str | None = None
    for module in ("langchain_core", "langchain_deepseek", "fastapi", "uvicorn"):
        try:
            __import__(module)
        except ModuleNotFoundError as exc:
            missing = exc.name or module
            break

    if missing is None:
        return

    interpreter = sys.executable
    env_python = r"D:\Project\Anaconda\envs\langchain_env\python.exe"
    print(
        f"""
✘ 缺少依赖：No module named '{missing}'

  你当前用的解释器是：
    {interpreter}

  本项目需要 conda 环境 langchain_env。请任选一种：

  1) 直接指定解释器：
       "{env_python}" run_web.py

  2) 先激活环境：
       conda activate langchain_env
       python run_web.py

  3) 在当前解释器里补装依赖：
       "{interpreter}" -m pip install -r requirements.txt

  PyCharm 用户：解释器请选 {env_python}
  ⚠ 不要用项目里的 .venv —— 那是空环境，只有 pip。
""",
        file=sys.stderr,
    )
    raise SystemExit(2)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="run_web.py", description="求职 Agent Web 界面"
    )
    parser.add_argument("--host", default="127.0.0.1", help="监听地址，默认 127.0.0.1")
    parser.add_argument("--port", type=int, default=8000, help="端口，默认 8000")
    parser.add_argument("--reload", action="store_true", help="改代码自动重载（开发用）")
    args = parser.parse_args(argv)

    _preflight()

    import uvicorn

    url = f"http://{args.host}:{args.port}"
    print("=" * 58)
    print(f"  求职 Agent Web 界面：{url}")
    print("  按 Ctrl+C 停止")
    print("=" * 58)

    uvicorn.run(
        "webapp.app:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
