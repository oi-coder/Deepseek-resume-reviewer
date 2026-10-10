# 求职 Agent —— JD 解析 + 简历定制

一个基于 **LangChain + DeepSeek** 的求职助手 Agent。把你随手写的简历底稿和任意一份
招聘 JD 丢给它，它会告诉你「这个岗位你到底行不行」，并针对这份 JD 重写一版简历。

```
                ┌─────────────┐        ┌──────────────────┐
   简历底稿  ──▶ │ 结构化档案   │        │   JD 结构化画像   │ ◀── 招聘 JD
 master_profile │ CandidateProfile │   │   JDProfile      │
                └──────┬──────┘        └────────┬─────────┘
                       └────────┬───────────────┘
                                ▼
                       ┌─────────────────┐
                       │   匹配度分析     │  逐项比对 + 六维评分 + 诚实指出短板
                       │   MatchReport   │
                       └────────┬────────┘
                                ▼
              ┌─────────────────┼─────────────────┐
              ▼                 ▼                 ▼
        ┌──────────┐     ┌───────────┐    ┌────────────┐
        │ 定制简历  │     │  求职信    │    │ 面试预测题  │
        │ md+docx  │     │    md     │    │     md     │
        └──────────┘     └───────────┘    └────────────┘
```

---

## 目录

- [能做什么](#能做什么)
- [快速开始](#快速开始)
- [命令速查](#命令速查)
- [Web 图形界面](#web-图形界面)
- [分享给别人（隧道）](#分享给别人隧道)
- [Agent 模式](#agent-模式)
- [简历底稿怎么写](#简历底稿怎么写)
- [输出文件](#输出文件)
- [项目结构](#项目结构)
- [两个 DeepSeek 思考模型的坑](#两个-deepseek-思考模型的坑)
- [常见问题](#常见问题)
- [安全提醒](#安全提醒)
- [后续可以怎么扩展](#后续可以怎么扩展)

---

## 能做什么

| 能力           | 说明                                                                                      |
|--------------|-----------------------------------------------------------------------------------------|
| **JD 结构化解析** | 把一段口语化的 JD 拆成岗位职责、硬性要求、加分项、ATS 关键词，还会指出**没明说的隐含期待**（比如「从 0 到 1」= 要能独立开荒，「抗压能力强」= 可能加班多） |
| **匹配度分析**    | 逐条比对 JD 要求与你的真实经历，给出 0-100 综合分、六个维度得分、优势和**短板**（会诚实说，不粉饰），以及关键词覆盖率                      |
| **定制简历**     | 按 JD 重排内容顺序、用 JD 的原词提升 ATS 命中率，同时导出 Markdown 和 Word                                     |
| **求职信**      | 引用 JD 里的具体信息写，不是套模板                                                                     |
| **面试准备**     | 预判 8-12 道面试题，重点押「JD 要求了但你证据薄弱」的地方，并给出回答提纲                                               |
| **反造假约束**    | 所有生成环节都有硬性约束：**不得编造公司、项目、学历和任何数字**                                                      |

## 快速开始

### 1. 确认环境

本项目使用 conda 环境 `langchain_env`（Python 3.12）：

```powershell
conda activate langchain_env
python -m pip install -r requirements.txt
```

> 依赖很轻：核心只需要 `langchain-core` + `langchain-deepseek` + `pydantic`。
> `python-docx` 和 `rich` 是可选的，缺了会自动降级（只出 Markdown / 用朴素 print）——
> 这条降级行为有自动化测试保证，见 `tests/test_offline.py` 里的
> `test_degrades_gracefully_without_optional_deps`。

### 2. 配置 API Key

```powershell
Copy-Item .env.example .env
# 然后编辑 .env，填入你的 DEEPSEEK_API_KEY
```

### 3. 自检

```powershell
python main.py check
```

看到 `✔ 模型 deepseek-flash 连接正常` 就说明通了。

### 4. 填简历底稿

编辑 `data/master_profile.md`，把示例内容换成**你自己的真实经历**。
写法很随意，不用讲究排版，把事情写全就行 —— Agent 会帮你整理。

### 5. 跑起来

```powershell
python main.py tailor data/jds/sample_ai_backend.txt
```

产物会写到 `outputs/` 目录。

---

## 命令速查

```powershell
# 环境自检：Key / 模型 / 网络
python main.py check

# 只解析简历底稿，看看 Agent 把你的经历理解成了什么
python main.py profile
python main.py profile --json        # 输出原始 JSON，便于核对

# 只解析 JD
python main.py parse-jd sample_ai_backend
python main.py parse-jd sample_ai_backend --json

# 匹配度分析（不生成简历）
python main.py match sample_ai_backend

# 全流程：分析 + 生成简历
python main.py tailor sample_ai_backend

# 全流程 + 求职信 + 面试题
python main.py tailor sample_ai_backend --all

# 进入可多轮对话的 Agent
python main.py agent --jd sample_ai_backend

# 清理缓存（改了底稿但想强制重新解析时用）
python main.py clean
```

**JD 参数**支持三种写法：绝对路径、相对路径、或 `data/jds/` 下的文件名（可省略扩展名）。

**全局参数**（放在子命令前面或后面都可以）：

| 参数                                        | 作用                       |
|-------------------------------------------|--------------------------|
| `--model deepseek-flash\|deepseek-v4-pro` | 切换模型，默认 `deepseek-flash` |
| `--verbose` / `-v`                        | 打印详细日志和 token 用量         |
| `--no-cache`                              | 禁用缓存，强制重新调用模型            |
| `--refresh`                               | 单次忽略缓存（针对某个子命令）          |

```powershell
# 下面两种写法等价
python main.py --verbose tailor sample_ai_backend
python main.py tailor sample_ai_backend --verbose
```

---

## Web 图形界面

不想敲命令就用网页版。基于 FastAPI，依赖很轻（实测只新增 5 个包，
`pydantic`/`anyio`/`h11` 环境里本来就有）。

### 启动

```powershell
python run_web.py                    # 打开 http://127.0.0.1:8000
python run_web.py --port 8123        # 换端口
```

浏览器打开提示的地址即可。按 `Ctrl+C` 停止。

### 界面能做什么

```
┌──────────────────┬────────────────────────────────────┐
│ 🔑 API Key 填写框 │  匹配度评分（0-100 + 结论）          │
├──────────────────┤  六维评分表                          │
│ ① 你的底稿        │  优势 / 短板（左右对照）              │
│   状态 + 编辑/上传 │  待补足的差距（按重要性排序）         │
├──────────────────┤  ────────────────────              │
│ ② 目标 JD         │  产出文件（.docx 一键下载）           │
│   下拉选择        │  ────────────────────              │
│   或粘贴原文      │  完整报告 / 定制简历（可折叠预览）     │
│   □求职信 □面试题 │                                    │
├──────────────────┤                                    │
│ ③ 实时进度        │                                    │
└──────────────────┴────────────────────────────────────┘
```

- **API Key 填写框**：填自己的 DeepSeek Key，可勾选记住在本机浏览器
  （`localStorage`，不上传服务器）
- **底稿编辑 / 上传**：点「编辑 / 上传」打开弹窗，可以直接改文字，
  也可以拖一个 `.docx` / `.md` / `.txt` 进来自动提取
- JD 两种来源：从 `data/jds/` 下拉选择，或**直接粘贴 JD 原文**（粘贴优先）
- 进度实时刷新，不会卡住界面
- `.docx` 直接下载，`.md` 在浏览器里以纯文本查看

### 底稿编辑与上传

点「① 你的底稿 → 编辑 / 上传」：

- **直接编辑**：文本框里改，点「保存底稿」。保存前**自动备份**到 `.backups/`，
  最多保留 10 份；右侧列出历史版本，可以「查看」再决定是否「恢复」。
- **上传文件**：支持 `.docx`、`.md`、`.txt`。
  提取结果会**先填进文本框让你检查**，确认无误再保存 —— 因为
  Word 提取不可能 100% 完美。
- **防误覆盖**：如果新内容不足原来的 50%（比如 3000 字变 500 字），
  会被拦下并要求勾选「允许大幅缩短」，避免误粘贴把底稿清空。

**`.docx` 提取处理了四种内容位置**（详见 `src/job_agent/docx_reader.py`）：

| 位置 | 为什么需要专门处理 |
|---|---|
| 普通段落 | 常规情况 |
| **表格** | 两栏表格是中文简历最常见排版，只读 `doc.paragraphs` 会**几乎全丢** |
| **文本框** | 藏在 `w:txbxContent`，python-docx 的 API 读不到，要自己扫 XML |
| **页眉 / 页脚** | 在独立的 `word/header*.xml` 部件里，不在 `document.xml` |

另外会：按**文档顺序**输出（段落与表格交替，而不是「先所有段落再所有表格」）、
合并单元格去重、过滤纯页码页脚、嗅探文件头。

**不支持 `.doc` 和 `.pdf`** —— 前者是二进制格式 python-docx 读不了，
后者双栏还原经常错乱。上传这两种会得到明确提示，让你先另存为 `.docx`。

### API 一览

| 方法 | 路径 | 作用 |
|---|---|---|
| GET | `/` | 界面页面 |
| GET | `/api/config` | 运行模式（是否分享模式、需要哪个请求头） |
| GET | `/api/health` | 健康检查 + 当前模型 |
| GET | `/api/jds` | 列出 `data/jds/` 里的 JD |
| GET | `/api/profile` | 底稿状态（只读缓存，不调模型） |
| GET | `/api/profile/raw` | 底稿原文 + 备份列表 |
| POST | `/api/profile/raw` | 保存底稿（自动备份 + 防误覆盖） |
| POST | `/api/profile/restore` | 从备份恢复 |
| GET | `/api/profile/backup/{name}` | 查看某个备份的内容 |
| POST | `/api/profile/extract` | 上传 `.docx`/`.md`/`.txt` 并提取文本 |
| POST | `/api/run` | 提交分析任务，返回 `job_id`（Key 走请求头） |
| GET | `/api/jobs/{id}` | 轮询进度与结果 |
| GET | `/api/download/{name}` | 下载 `outputs/` 下的产物 |
| GET | `/api/docs` | 自动生成的交互式接口文档 |

### 六个设计要点

1. **后台线程执行 + 前端轮询**。单步 LLM 调用实测 14~48 秒，整条流水线
   1~3 分钟。直接同步执行会让页面假死，所以 `POST /api/run` 立刻返回
   `job_id`，真正的执行跑在守护线程里，前端每 0.9 秒轮询一次进度。
2. **同一时刻只允许一个作业**。重复提交返回 `409`，避免误连点重复烧 token。
3. **Web 层不 import `job_agent.ui`**。那个模块在导入时会 `reconfigure` stdout
   编码，对服务器进程是副作用。进度通过自定义回调传递 —— 因为
   `run_pipeline()` 本来就接受 `progress` 回调，**业务代码一行没改**。
   这条约束有测试守着（`test_webapp_does_not_import_ui`）。
4. **Markdown 用 `MarkdownIt("js-default")` 预设**。默认预设**不渲染表格**，
   而匹配报告大量用表格，否则会显示成一堆 `| 维度 | 得分 |` 原文。
   同时关掉了 `html`，JD 原文里的裸标签会被转义。
5. **API Key 按请求头携带，不落库**。`Settings` 本来就一路传进
   `run_pipeline`，所以只要给每次请求 `dataclasses.replace()` 出一个副本即可 ——
   **业务代码依然零改动，而且天然线程安全**（不会污染全局单例，
   有测试 `test_with_api_key_does_not_mutate_global_settings` 守着）。
6. **分享模式下产物按作业隔离**。下载接口要求带 `?job=<id>` 且校验该文件
   确实属于这个作业，否则任何访客都能猜到别人的简历文件名并下载。

### 安全说明

- 默认只监听 `127.0.0.1`，仅本机可访问。
- `--host 0.0.0.0` 或加隧道会开放到公网，**此时没有登录认证**。
  本机模式（不加 `--share`）下任何能访问的人都能消耗你的 API Key。
- 下载接口只允许取 `outputs/` 的**直接子文件**，目录穿越（`../.env`）返回 404，
  有测试覆盖。
- 服务端**不会**把 API Key 返回给前端，也不会写进日志。

### 跑 Web 层的测试

```powershell
python tests\test_webapp.py           # 17 个用例：接口形状、穿越防护、HTML 转义、前端接线
python tests\test_webapp_profile.py   # 25 个用例：底稿编辑/备份、上传提取、按请求 Key、分享模式
python tests\test_docx_reader.py      # 16 个用例：四种内容位置、合并单元格、格式嗅探
```

这三套都不消耗 token。`test_webapp_profile.py` 会把底稿路径重定向到临时目录，
**不会碰你的真实 `data/master_profile.md`**。

---

## 分享给别人（隧道）

### 先把两个问题说清楚

**1. 隧道 = 用你的电脑当服务器。** 代码、模型调用、文件读写全在你机器上跑，
隧道只负责把公网请求转发进来。所以**你的电脑必须一直开机、联网、服务不能关**，
关机链接就失效。

**2. 不能用 Netlify Drop。** Netlify 的 CDN [只提供静态文件，没有任何语言运行时](https://answers.netlify.com/t/support-guide-can-i-run-a-web-server-http-listener-and-or-database-at-netlify/3078)
（官方原话：no application server or language runtime, meaning no node.js, Ruby, PHP, **Python**），
跑不了 FastAPI；而且单次流水线实测 76~95 秒，远超 Serverless 函数的时限。
想分享就用隧道。

### 用 `--share` 启动

```powershell
python run_web.py --port 8000 --share
```

`--share` 做四件事：

| 行为 | 为什么 |
|---|---|
| **不读 `.env` 的 Key**，访客必须填自己的 | 否则所有访客都在花你的钱 |
| 未填 Key 的请求返回 `401` | 明确告诉访客要填 Key |
| **禁用解析缓存** | 访客的简历解析结果不会落在你的磁盘上 |
| **产物下载按作业隔离**（要求 `?job=<id>`） | 防止访客互相下载到别人的简历 |

访客打开页面会看到提示：

> ⚠ 这是他人分享的服务，你填写的 API Key 只用于你自己的请求、服务端不保存；
> 运行的 token 费用由你自己的 DeepSeek 账号承担。

**实测验证过的行为**：

```
无 Key 提交                    -> HTTP 401
访客自带 Key 提交              -> HTTP 200，76.2 秒跑完，78/100
裸下载（不带 job 参数）         -> HTTP 403
带 job 参数下载                -> HTTP 200，10252 字节
```

### 开隧道

**cloudflared**（免注册，最省事）：

```powershell
winget install --id Cloudflare.cloudflared
cloudflared tunnel --url http://127.0.0.1:8000
```

**ngrok**：

```powershell
winget install --id Ngrok.Ngrok
ngrok config add-authtoken <你的 token>
ngrok http 8000
```

> 本机实测 `cloudflared` 和 `ngrok` **都还没安装**，但 `winget` 和 `choco` 可用。

命令会打印一个 `https://xxx.trycloudflare.com` 之类的公网地址，发给别人即可。

### 分享前请务必知道

- **仍然没有登录认证**。任何拿到链接的人都能用*他自己的* Key 来跑，
  你的额度不会被动，但**你的机器在为他们做计算**，而且能看到你 `data/` 里的
  JD 列表和 `outputs/` 里累积的历史产物。
- **访客的简历会落在你的磁盘上**。`outputs/` 里的 `.docx` 是访客的简历，
  分享结束后建议清掉：
  ```powershell
  Remove-Item outputs\* -Force
  ```
- **Key 会经过隧道服务商**。虽然隧道是 HTTPS、服务端也不存储，
  但 traffic 确实穿过了 Cloudflare/ngrok 的服务器。敏感场景请勿使用。
- **想更保险就加一道共享口令**。目前没做，如果需要可以加
  （一个 `?token=xxx` 或登录 Cookie，约半天工作量）。

### 不想暴露本机？替代方案

| 方案 | 说明 |
|---|---|
| 部署到能跑 Python 的平台 | Render / Railway / Fly.io / Hugging Face Spaces —— 需要改成无状态（去掉文件系统依赖），工作量较大 |
| 纯静态 BYOK 版 | 实测 DeepSeek API **允许浏览器跨域直连**（CORS 会回显 Origin），理论上可以做一个纯前端版本拖到 Netlify Drop。但要**用 JS 重写整条流水线**（提示词、结构化输出重试、docx 导出），两套代码会漂移，不推荐 |
| 局域网分享 | `python run_web.py --host 0.0.0.0 --share`，同一 WiFi 下用 `http://你的内网IP:8000` 访问，不出公网 |

---

## Agent 模式

`tailor` 是固定流水线，省 token 且结果稳定。当你需要**多轮追问**时才用 Agent：

```powershell
python main.py agent
```

Agent 持有 9 个工具，会自己决定调用顺序：

|       作用        | 工具                        |
|:---------------:|---------------------------|
|    解析 JD 原文     | `load_job_description`    |
|    读取你的结构化档案    | `get_candidate_profile`   |
|     做匹配度分析      | `analyze_match`           |
| 生成简历（md + docx） | `generate_resume`         |
|      生成求职信      | `generate_cover_letter`   |
|      生成面试题      | `generate_interview_prep` |
|    列出已生成的文件     | `list_outputs`            |
|   读取某个产出文件的内容   | `read_output`             |
|     把结论存成文件     | `save_note`               |

典型对话：

```
你 > 帮我看下这份 JD 我合不合适：
     高级Python后端工程师（AI Agent方向）...（整段粘贴）...

AI > （自动调用 load_job_description → analyze_match，然后汇报结论）

你 > 那简历该怎么改？
AI > （调用 generate_resume，生成文件并说明改了哪些地方）

你 > 再帮我准备下面试
AI > （调用 generate_interview_prep）
```

内置命令：`/outputs` 看产物、`/reset` 清对话历史、`/quit` 退出。

---

## 简历底稿怎么写

`data/master_profile.md` 是**唯一事实来源**，写得越全，产出越好。

**要写的**：

- 基本信息：姓名、手机、邮箱、城市、GitHub
- 每段工作：公司、职位、起止时间、你具体做了什么
- 每个项目：项目名、你的角色、用了什么技术、解决了什么问题
- 教育背景、证书、开源贡献、获奖

**写作建议**：

- 有数字就写数字（"P95 延迟从 800ms 降到 120ms"），没数字就客观描述影响面，**不要编**
- 不用管排版和润色，Agent 会重写
- 不用怕写得太细，长一点没关系（解析结果会缓存，不会重复烧 token）
- 不要在底稿里写「精通 XX」这种自评 —— 写事实，让 Agent 判断

**为什么强调真实**：项目的每个生成环节都带有反造假约束，Agent 宁可少写也不会替你
编数字。如果你底稿里没有 K8s 经验，它不会给你变出来，而是会在匹配报告里告诉你
「这是你的短板」。

### 应届生 / 在校生怎么写

项目对**没有工作经历**的候选人有专门处理，不需要你特殊标注：

- 底稿里写「无工作经验」「大四在读」即可，`experiences` 会保持为空，
  **不会**硬把项目包装成工作经历；
- **校园职务**（学生会、班委、社团负责人、志愿活动）请写在底稿里 ——
  它会被归入独立字段 `campus_experience`，而不是混进「获奖」里；
- 生成的简历会**自动切换版式**：教育背景与项目经历前置，核心技能后移，
  并且**不出现空的工作经历小节**；校园经历单独成节，用来佐证沟通与执行力；
- 个人简介里会主动说明应届生身份、毕业时间与求职方向。

判断依据很简单：`experiences` 为空就走应届生版式，非空就走社招版式。
两种版式都有回归测试覆盖。

---

## 输出文件

所有产物都在 `outputs/`，文件名带时间戳，不会互相覆盖：

| 文件                          | 内容                                |
|-----------------------------|-----------------------------------|
| `match-<岗位>-<时间>.md`        | 匹配度分析报告                           |
| `resume-<岗位>-<时间>.md`       | 定制简历（Markdown 版）                  |
| `resume-<岗位>-<时间>.docx`     | 定制简历（Word 版，ATS 友好单栏排版，可直接投递）     |
| `cover-letter-<岗位>-<时间>.md` | 求职信（需 `--cover-letter` 或 `--all`） |
| `interview-<岗位>-<时间>.md`    | 面试准备包（需 `--interview` 或 `--all`）  |

缓存放在 `.cache/`（同一份 JD 或底稿不会重复调用模型，省钱）。两个目录都已加进
`.gitignore`。

---

## 项目结构

```
AI_agent/
├── main.py                     # CLI 入口（argparse，无第三方 CLI 依赖）
├── Langchain_ds.py             # 最小 hello world，用于快速自检环境
├── requirements.txt
├── .env / .env.example         # API Key（.env 已被 gitignore）
│
├── src/job_agent/
│   ├── config.py               # 配置与路径，支持环境变量覆盖
│   ├── schemas.py              # 全部 Pydantic 数据契约
│   ├── llm.py                  # ★ LLM 工厂 + 结构化输出封装（含 json_mode 变通）
│   ├── prompts.py              # 提示词集中管理
│   ├── storage.py              # 读写、缓存、文件名处理
│   ├── profile.py              # 底稿 → CandidateProfile
│   ├── jd.py                   # JD 文本 → JDProfile
│   ├── match.py                # 匹配度分析
│   ├── resume.py               # 简历 / 求职信 / 面试题生成
│   ├── render.py               # 渲染 Markdown 与 Word
│   ├── docx_reader.py          # ★ .docx 提取（段落+表格+文本框+页眉页脚）
│   ├── pipeline.py             # 确定性流水线
│   ├── tools.py                # Agent 工具集 + 会话状态
│   ├── agent.py                # ★ tool-calling 循环（手写，不依赖 langgraph）
│   └── ui.py                   # 终端输出（rich 可选，自动修 UTF-8）
│
├── data/
│   ├── master_profile.md       # ★ 你的简历底稿（请填成自己的真实经历）
│   └── jds/                    # 放 JD 文件的目录
│       ├── sample_ai_backend.txt        # 示例：社招 AI 后端
│       └── sample_embedded_campus.txt   # 示例：校招嵌入式软件
│
├── outputs/                    # 生成结果
├── webapp/
│   ├── app.py                  # ★ Web 后端：作业管理 + 底稿编辑 + 按请求 Key
│   └── static/index.html       # 单页前端（无 CDN，离线可用）
├── run_web.py                  # Web 界面启动器（--share 进分享模式）
├── tests/
│   ├── test_offline.py         # 核心逻辑自测（34 个用例）
│   ├── test_webapp.py          # Web 接口与安全（17 个用例）
│   ├── test_webapp_profile.py  # 底稿编辑/上传/按请求 Key（25 个用例）
│   └── test_docx_reader.py     # docx 提取（16 个用例）
├── .backups/                   # 底稿历史备份（最多 10 份）
└── .cache/                     # 解析缓存
```

**跑一遍离线自测**（不花 token，共 92 个用例）：

```powershell
python tests\test_offline.py          # 34 个用例
python tests\test_webapp.py           # 17 个用例
python tests\test_webapp_profile.py   # 25 个用例
python tests\test_docx_reader.py      # 16 个用例
python tests\test_offline.py --live   # 额外跑一次真实 API 调用
```

---

## 两个 DeepSeek 思考模型的坑

这两点踩过一次，记在这里省得你重复踩。

### 坑 1：模型名不是想当然的那个

`deepseek-flash` 和 `deepseek-v4-pro` 是**思考模型**，模型 id 必须和
`https://api.deepseek.com/models` 返回的一致。写成 `deepseek-v4-flash` 会直接 400。

查当前可用的模型 id：

```powershell
python -c "import os,json,urllib.request; from dotenv import load_dotenv; load_dotenv(); k=os.environ['DEEPSEEK_API_KEY']; print(json.dumps(json.load(urllib.request.urlopen(urllib.request.Request('https://api.deepseek.com/models', headers={'Authorization':'Bearer '+k}))), ensure_ascii=False, indent=2))"
```

### 坑 2：`with_structured_output()` 默认会失败

思考模式不支持强制 `tool_choice`，而 `with_structured_output()` 的默认实现正是靠
它，于是报错：

```
Error code: 400 - Thinking mode does not support this tool_choice
```

另外 `method="json_mode"` 还有个隐藏要求：**提示词里必须出现 `json` 字样**，否则报
`Prompt must contain the word 'json'`。

本项目的 `src/job_agent/llm.py` 里统一做了处理：

1. 改用 `method="json_mode"`；
2. 自动把 Pydantic 的 JSON Schema 注入 system prompt（顺带满足 `json` 字样的要求）；
3. 解析失败自动重试，并把失败原因回灌给模型；
4. 重试耗尽后退化为「原始文本 + 花括号配对抠 JSON」，尽量抢救结果。

所以**所有结构化抽取都必须走 `invoke_structured()`**，不要直接调
`llm.with_structured_output()`。

> 补充：`ChatPromptTemplate` 会把 prompt 里的 JSON 示例花括号当成模板变量并报
> `ValueError: Invalid format specifier in f-string template`。本项目一律用
> `SystemMessage` / `HumanMessage` 手工拼消息来绕开。

---

## 常见问题

**Q：报错 `ModuleNotFoundError: No module named 'langchain_core'`（或缺 `dotenv`）**

**解释器选错了**，这是最常见的坑。依赖装在 conda 环境 `langchain_env` 里，
但你的 `python` / PyCharm 用的是别的解释器。三种解法任选：

```powershell
# 1) 直接指定解释器，最省事
D:\Project\Anaconda\envs\langchain_env\python.exe main.py check

# 2) 先激活环境
conda activate langchain_env
python main.py check

# 3) 在当前解释器里补装依赖
python -m pip install -r requirements.txt
```

**PyCharm 用户**：`Settings → Project: AI_agent → Python Interpreter` 改成
`D:\Project\Anaconda\envs\langchain_env\python.exe`，
⚠️ **不要选项目里的 `.venv`** —— 那是 PyCharm 自动建的空环境，只有 pip，
一个依赖都没有。

> 现在遇到这种情况，程序会直接告诉你当前用的是哪个解释器、该怎么改，
> 不会再抛一大段 traceback。

**Q：直接运行 `main.py` 报 `the following arguments are required: command`**

不是 bug —— 必须告诉它要做什么。现在裸跑会打印引导菜单：

```powershell
python main.py            # 看引导
python main.py --help     # 看完整参数
python main.py check      # 第一次用建议先跑这个
```

**Q：报错「未找到 DEEPSEEK_API_KEY」**
把 `.env.example` 复制成 `.env` 并填 Key。注意文件名就是 `.env`，不是 `.env.txt`。

**Q：报错 401 / Authentication Fails**
Key 错了或已失效。到 <https://platform.deepseek.com/api_keys> 重新生成。

**Q：改了 `master_profile.md`，但结果没变**
解析结果被缓存了。用 `--refresh`，或直接 `python main.py clean`。

**Q：Word 导出被跳过**
没装 `python-docx`。跑 `python -m pip install python-docx` 即可。

**Q：终端里中文是乱码**
`ui.py` 已经会把 stdout 切成 UTF-8。如果仍然乱码，先执行
`chcp 65001`，或设置环境变量 `PYTHONIOENCODING=utf-8`。

**Q：匹配分很低，是不是没用**
不一定是坏事。这个 Agent 的价值就在于**在你投简历之前就告诉你不行**，
省下的是你反复被挂的时间。分数低时看 `gaps` 里的 `suggestion`，那是可执行的补足方向。

**Q：一次 tailor 大概花多少 token**
带 `--verbose` 会打印统计。因为有缓存，同一份 JD + 底稿重复跑几乎不花钱。

**Q：`.venv` 目录是干嘛的**
是 PyCharm 建的一个空虚拟环境，和本项目无关（本项目用的是 conda 的
`langchain_env`）。可以删掉，也可以在 PyCharm 里把解释器指到
`D:\Project\Anaconda\envs\langchain_env\python.exe`。

---

**Q：上传 `.docx` 后提取的顺序不对 / 有重复内容**

Word 里没有「阅读顺序」这个概念，只有 XML 结构。本项目的处理是：
按 body 顺序输出段落与表格、按行展平表格、合并单元格去重、文本框并进正文。
但**复杂排版（多栏、大量文本框、嵌套表格）仍可能不完美** ——
所以提取结果会先填进文本框让你检查，确认后再保存。

如果顺序实在乱，最省事的办法是：在 Word 里全选复制，直接粘到编辑框里手工整理一次。

**Q：编辑底稿保存后能撤销吗**

能。每次保存前都会自动备份到 `.backups/`，最多保留 10 份，
在编辑弹窗右侧能看到历史版本，点「查看」比对、点「恢复」回滚。
恢复操作本身也会先备份当前内容，所以不会「恢复错了就没救」。

**Q：分享给朋友后，他们会用我的 API Key 吗**

不会 —— 前提是你用 `--share` 启动。分享模式下服务端**不读** `.env` 的 Key，
访客必须填自己的，不填直接 `401`。详见[分享给别人（隧道）](#分享给别人隧道)。

**Q：`.backups/` 和 `.cache/` 能删吗**

能。`.cache/` 是解析缓存（删了下次重新解析，多花点 token）；
`.backups/` 是底稿历史版本（删了就失去撤销能力，但当前底稿不受影响）。
两者都已加进 `.gitignore`。

---

## 安全提醒

- `.env` 里有你的 API Key，**已被 `.gitignore` 排除**，不要提交到 Git。
- 分享项目截图或代码时注意别把 Key 一起发出去。
- 如果 Key 曾经泄露（比如贴进过聊天记录、提交过仓库），**立刻去控制台吊销并重新生成**。

---

## 后续可以怎么扩展

按性价比排序：

1. **批量匹配**：把 `data/jds/` 下所有 JD 都跑一遍，输出一张「岗位 × 匹配分」排序表，
   一次性决定优先投哪几家。（`run_pipeline` 已经是可复用的函数，写个循环就行）
2. **JD 截图识别**：`deepseek-flash` 支持图片输入，可以加个 `--image` 参数直接读
   招聘 App 的截图，省掉复制粘贴。
3. **PDF 导出**：装 `docx2pdf` 或 `pandoc`，把 docx 转成 PDF（投递更保险）。
4. **投递记录管理**：用一个 JSON 记录投了哪些公司、进展如何，Agent 可以提醒跟进。
5. **接入 LangGraph**：如果之后要加人工确认（human-in-the-loop）、断点续跑、
   多分支流程，把 `agent.py` 的手写循环换成 LangGraph 会更省事。
6. **做成网页**：装 `gradio` 或 `streamlit`，把 `run_pipeline` 包一层即可。

---

## 技术选型说明

- **只用 `langchain-core`，不装 `langchain` 元包**：元包会拖入大量无关依赖，
  而本项目需要的能力（`bind_tools`、`with_structured_output`、消息类型）核心包全都有。
- **不依赖 `langgraph`**：Agent 循环只有几十行，手写反而更好调试、报错更清楚。
  见 `src/job_agent/agent.py`。
- **不依赖 `typer`**：`argparse` 是标准库，够用且零依赖。
- **所有结构化抽取收口到一个函数**：`llm.invoke_structured()` 统一处理重试、修复和
  降级，避免每个模块各写一套容错逻辑。
