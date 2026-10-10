"""最小可运行示例：验证 DeepSeek + LangChain 是否接通。

这是项目最初的 hello world，保留下来作为「环境是否正常」的快速自检。
完整的求职 Agent 请运行 `python main.py --help`。

运行：
    D:\\Project\\Anaconda\\envs\\langchain_env\\python.exe Langchain_ds.py

注意两个容易踩的坑：
1. 模型名必须是 API 返回的 id。写成 "deepseek-v4-flash" 会直接 400，
   正确的 id 是 "deepseek-flash"。
2. 该模型是思考模型，with_structured_output() 的默认实现会失败
   （思考模式不支持强制 tool_choice）。本项目在 src/job_agent/llm.py 里
   统一改用 json_mode 绕开，详见那里的注释。
"""

import os
from pathlib import Path

from dotenv import load_dotenv
from langchain_deepseek import ChatDeepSeek

# 1. 加载环境变量（按脚本所在目录定位 .env，避免受工作目录影响）
load_dotenv(Path(__file__).resolve().parent / ".env")

if not os.getenv("DEEPSEEK_API_KEY"):
    raise SystemExit(
        "未找到 DEEPSEEK_API_KEY。请把 .env.example 复制为 .env 并填入你的 Key。"
    )

# 2. 初始化 LLM（模型名必须是 deepseek-flash 或 deepseek-v4-pro）
llm = ChatDeepSeek(
    model="deepseek-flash",
    temperature=0.7,
)

# 3. 构建消息列表 (Messages)
messages = [
    ("system", "你是一位幽默风趣的AI助手，回答尽量简明扼要。"),
    ("human", "用一句话解释什么是 LangChain？"),
]

# 4. 调用模型并打印结果
response = llm.invoke(messages)
print("AI 回复:", response.content)

# 5. 顺便打印 token 用量，方便估算成本
usage = getattr(response, "usage_metadata", None) or {}
if usage:
    print(
        f"用量: 输入 {usage.get('input_tokens', 0)} tok, "
        f"输出 {usage.get('output_tokens', 0)} tok"
    )
