"""FastAPI Web 界面（方案 A）。

设计要点
--------
1. **不 import ``job_agent.ui``** —— 它在导入时会 reconfigure stdout，
   对服务器进程是副作用。进度改用自定义回调传递。
2. **后台线程跑流水线** —— 单步 LLM 调用实测 14~48 秒，
   直接在请求里同步执行会让界面假死。
3. **同一时刻只允许一个作业** —— 避免误连点导致重复烧 token。
4. **Markdown 用 ``js-default`` 预设** —— 默认预设不渲染表格，
   而匹配报告大量用表格。
5. **API Key 按请求携带**（``X-DeepSeek-Key`` 请求头）——
   服务端不保存访客的 Key。分享模式下**禁用 .env 回退**，
   访客必须用自己的 Key 才能使用，因此不会消耗站长的额度。
6. **分享模式下产物按作业隔离** —— 下载接口要求带 ``?job=<id>``，
   防止访客互相下载到别人的简历。
"""

from __future__ import annotations

import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import FastAPI, File, Header, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from markdown_it import MarkdownIt
from pydantic import BaseModel, Field

# ---- 让 webapp 能 import 到 src/job_agent
PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from job_agent.config import (  # noqa: E402
    API_KEY_HEADER,
    BACKUP_DIR,
    FLASH_MODEL,
    JD_DIR,
    MASTER_PROFILE_MD,
    OUTPUT_DIR,
    VALID_MODELS,
    get_settings,
    with_api_key,
)
from job_agent.docx_reader import MAX_BYTES, extract_docx  # noqa: E402
from job_agent.pipeline import PipelineResult, run_pipeline  # noqa: E402
from job_agent.profile import load_cached_profile  # noqa: E402
from job_agent.storage import (  # noqa: E402
    backup_file,
    decode_bytes,
    list_backups,
    read_text,
    restore_backup,
    write_text_atomic,
)

STATIC_DIR = Path(__file__).resolve().parent / "static"

# html=False：JD 原文里的裸 HTML 会被转义，避免注入
_MD = MarkdownIt("js-default", {"html": False})

#: 底稿至少要有这么多字符才允许保存
MIN_PROFILE_CHARS = 60

#: 上传时可接受的扩展名
TEXT_EXTS = {".md", ".markdown", ".txt"}
DOCX_EXTS = {".docx"}

# ---------------------------------------------------------------- 运行模式

#: True 时进入「分享模式」：不读 .env 的 Key，访客必须自带；
#: 并且产物下载必须带 job 参数，避免访客互相看到内容。
SHARE_MODE = False

#: 分享模式下禁用缓存，避免把访客的简历解析结果留在站长磁盘上
SHARE_MODE_DISABLE_CACHE = True


def configure(*, share_mode: bool) -> None:
    """由 run_web.py 在启动时调用。"""
    global SHARE_MODE
    SHARE_MODE = bool(share_mode)


# ================================================================ 作业管理


@dataclass
class Job:
    """一次流水线执行的状态。"""

    id: str
    jd_label: str
    status: str = "pending"  # pending | running | done | error
    steps: list[str] = field(default_factory=list)
    result: dict[str, Any] | None = None
    error: str | None = None
    #: 该作业产出的文件名，分享模式下用于校验下载权限
    artifacts: list[str] = field(default_factory=list)
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None

    def elapsed(self) -> float:
        return (self.finished_at or time.time()) - self.started_at

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "jd_label": self.jd_label,
            "status": self.status,
            "steps": self.steps,
            "result": self.result,
            "error": self.error,
            "elapsed": round(self.elapsed(), 1),
        }


_JOBS: dict[str, Job] = {}
_LOCK = threading.Lock()
_MAX_JOBS = 40


def _running_job() -> Job | None:
    return next((j for j in _JOBS.values() if j.status in {"pending", "running"}), None)


def _prune_jobs() -> None:
    """只保留最近若干个作业，防止内存无限增长。"""
    if len(_JOBS) <= _MAX_JOBS:
        return
    done = sorted(
        (j for j in _JOBS.values() if j.status in {"done", "error"}),
        key=lambda j: j.started_at,
    )
    for job in done[: len(_JOBS) - _MAX_JOBS]:
        _JOBS.pop(job.id, None)


# ================================================================ 序列化


def _artifact(path: Path, job_id: str | None = None) -> dict[str, Any]:
    url = f"/api/download/{quote(path.name)}"
    if job_id:
        url += f"?job={quote(job_id)}"
    return {
        "name": path.name,
        "size": path.stat().st_size,
        "ext": path.suffix.lstrip("."),
        # 产物名含中文，必须 percent-encode，否则非浏览器客户端无法请求
        "url": url,
    }


def _serialize(result: PipelineResult, job_id: str | None = None) -> dict[str, Any]:
    """把 PipelineResult 转成前端要的 JSON。"""
    report = result.match
    return {
        "jd": {
            "title": result.jd.title,
            "company": result.jd.company,
            "seniority": result.jd.seniority,
            "location": result.jd.location,
            "domain": result.jd.domain,
        },
        "score": report.overall_score,
        "verdict": report.verdict,
        "dimensions": [d.model_dump() for d in report.dimensions],
        "strengths": report.strengths,
        "weaknesses": report.weaknesses,
        "keyword_coverage": report.keyword_coverage,
        "matched_count": len(report.matched_skills),
        "gap_count": len(report.gaps),
        "gaps": [
            {
                "skill": g.skill,
                "required_level": g.required_level,
                "candidate_level": g.candidate_level,
                "suggestion": g.suggestion,
            }
            for g in report.gaps
        ],
        "match_html": _MD.render(result.match_markdown),
        "resume_html": _MD.render(result.resume_markdown) if result.resume else "",
        "artifacts": [
            _artifact(p, job_id) for p in result.artifacts if p.is_file()
        ],
    }


# ================================================================ 后台执行


def _execute(
    job_id: str,
    *,
    jd_text: str | None,
    jd_name: str | None,
    with_cover_letter: bool,
    with_interview: bool,
    refresh: bool,
    use_cache: bool,
) -> None:
    job = _JOBS[job_id]

    def progress(message: str) -> None:
        with _LOCK:
            job.steps.append(message)

    try:
        with _LOCK:
            job.status = "running"

        # 每次请求用独立的 Settings 副本：访客的 Key 只作用于这一次执行，
        # 不写全局单例，因此不会串到别人的请求上。
        settings = with_api_key(get_settings(), _key_for_job(job_id))
        if not use_cache:
            settings.use_cache = False

        result = run_pipeline(
            jd_text=jd_text,
            jd_path=jd_name,
            with_resume=True,
            with_cover_letter=with_cover_letter,
            with_interview=with_interview,
            refresh=refresh,
            settings=settings,
            progress=progress,
        )
        payload = _serialize(result, job_id)
        names = [p.name for p in result.artifacts if p.is_file()]

        with _LOCK:
            job.result = payload
            job.artifacts = names
            job.status = "done"
            job.steps.append("完成")
    except Exception as exc:  # noqa: BLE001 - 任何失败都要如实回报给前端
        with _LOCK:
            job.error = f"{type(exc).__name__}: {exc}"
            job.status = "error"
    finally:
        with _LOCK:
            job.finished_at = time.time()


#: job_id -> 访客自带的 Key。只存在于内存，作业结束即删。
_JOB_KEYS: dict[str, str] = {}


def _key_for_job(job_id: str) -> str:
    with _LOCK:
        return _JOB_KEYS.get(job_id, "")


def _resolve_key(header_key: str | None) -> str:
    """决定这次请求用哪个 Key。

    - 访客带了 Key → 用访客的
    - 没带：分享模式下直接拒绝（不能花站长的钱）；本机模式回退到 .env
    """
    user_key = (header_key or "").strip()
    if user_key:
        return user_key
    if SHARE_MODE:
        raise HTTPException(
            401,
            "这是他人分享的服务，请先填入你自己的 DeepSeek API Key 再使用"
            "（Key 只用于本次请求，服务端不会保存）",
        )
    return get_settings().api_key


# ================================================================ API 模型


class RunRequest(BaseModel):
    jd_name: str | None = Field(default=None, description="data/jds 下的文件名")
    jd_text: str | None = Field(default=None, description="直接粘贴的 JD 原文")
    with_cover_letter: bool = False
    with_interview: bool = False
    refresh: bool = False


class ProfileSaveRequest(BaseModel):
    text: str
    #: 内容大幅缩短时需要显式确认，防止误覆盖
    allow_shrink: bool = False


class RestoreRequest(BaseModel):
    name: str


# ================================================================ 应用


app = FastAPI(title="求职 Agent", docs_url="/api/docs", openapi_url="/api/openapi.json")


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    page = STATIC_DIR / "index.html"
    if not page.is_file():
        raise HTTPException(500, "找不到 static/index.html")
    return HTMLResponse(page.read_text(encoding="utf-8"))


@app.get("/api/config")
def client_config() -> dict[str, Any]:
    """前端启动时读取的运行模式。"""
    settings = get_settings()
    return {
        "share_mode": SHARE_MODE,
        "server_has_key": bool(settings.api_key),
        "api_key_header": API_KEY_HEADER,
        "models": list(VALID_MODELS),
        "default_model": FLASH_MODEL,
        "max_upload_mb": MAX_BYTES // 1024 // 1024,
        "text_exts": sorted(TEXT_EXTS),
        "docx_exts": sorted(DOCX_EXTS),
        "min_profile_chars": MIN_PROFILE_CHARS,
    }


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"ok": True, "models": list(VALID_MODELS), "default_model": FLASH_MODEL}


@app.get("/api/jds")
def list_jds() -> dict[str, Any]:
    """列出 data/jds 下可选的 JD 文件。"""
    directory = Path(JD_DIR)
    if not directory.is_dir():
        return {"jds": []}

    items = []
    for path in sorted(directory.iterdir()):
        if not path.is_file() or path.suffix.lower() not in {".txt", ".md"}:
            continue
        text = read_text(path)
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        items.append(
            {
                "name": path.name,
                "stem": path.stem,
                "title": (lines[0] if lines else path.stem)[:90],
                "chars": len(text),
            }
        )
    return {"jds": items}


# ---------------------------------------------------------------- 底稿


@app.get("/api/profile")
def profile_info() -> dict[str, Any]:
    """底稿状态。只读缓存，不触发模型调用。"""
    path = Path(MASTER_PROFILE_MD)
    cached = load_cached_profile()
    return {
        "exists": path.is_file(),
        "chars": len(read_text(path)) if path.is_file() else 0,
        "name": cached.contact.name if cached else None,
        "headline": cached.headline if cached else None,
        "skills": len(cached.skills) if cached else 0,
        "projects": len(cached.projects) if cached else 0,
        "experiences": len(cached.experiences) if cached else 0,
        "campus": len(cached.campus_experience) if cached else 0,
        "cached": cached is not None,
    }


@app.get("/api/profile/raw")
def get_profile_raw() -> dict[str, Any]:
    """底稿原文 + 备份列表，供网页编辑器使用。"""
    path = Path(MASTER_PROFILE_MD)
    text = read_text(path) if path.is_file() else ""
    return {
        "text": text,
        "chars": len(text),
        "exists": path.is_file(),
        "mtime": path.stat().st_mtime if path.is_file() else None,
        "backups": list_backups(path, backup_dir=BACKUP_DIR),
        "min_chars": MIN_PROFILE_CHARS,
    }


@app.post("/api/profile/raw")
def save_profile_raw(request: ProfileSaveRequest) -> dict[str, Any]:
    """保存底稿。保存前自动备份，并在内容大幅缩短时要求确认。

    注意：返回的 ``chars`` 与 ``GET /api/profile/raw`` 口径一致，
    都用 ``len(text)``（不 strip），否则前后端显示的字符数会对不上。
    阈值判断才用 strip 后的长度，避免被首尾空白干扰。
    """
    text = request.text
    stripped = len(text.strip())

    if stripped < MIN_PROFILE_CHARS:
        raise HTTPException(
            400, f"底稿太短（{stripped} 字符），至少需要 {MIN_PROFILE_CHARS} 字符。"
        )

    path = Path(MASTER_PROFILE_MD)
    previous_text = read_text(path) if path.is_file() else ""
    previous_stripped = len(previous_text.strip())

    # 从 3000 字变 500 字，多半是误粘贴覆盖
    if (
        previous_stripped
        and stripped < previous_stripped * 0.5
        and not request.allow_shrink
    ):
        raise HTTPException(
            409,
            f"新内容只有原来的 {stripped / previous_stripped:.0%}"
            f"（{previous_stripped} → {stripped} 字符），可能是误覆盖。"
            "确认要替换请勾选「允许大幅缩短」。",
        )

    backup = backup_file(path, backup_dir=BACKUP_DIR) if path.is_file() else None
    write_text_atomic(path, text)

    return {
        "ok": True,
        "chars": len(text),
        "previous_chars": len(previous_text),
        "backup": backup.name if backup else None,
        "backups": list_backups(path, backup_dir=BACKUP_DIR),
    }


@app.post("/api/profile/restore")
def restore_profile(request: RestoreRequest) -> dict[str, Any]:
    """从备份恢复底稿（恢复前也会先备份当前内容）。"""
    path = Path(MASTER_PROFILE_MD)
    try:
        restore_backup(request.name, path, backup_dir=BACKUP_DIR)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    text = read_text(path)
    return {
        "ok": True,
        "chars": len(text),
        "text": text,
        "backups": list_backups(path, backup_dir=BACKUP_DIR),
    }


@app.get("/api/profile/backup/{name}")
def read_backup(name: str) -> dict[str, Any]:
    """查看某个备份的内容（用于比对后再决定是否恢复）。"""
    if not name or Path(name).name != name:
        raise HTTPException(400, "非法备份名")
    root = Path(BACKUP_DIR).resolve()
    target = (root / name).resolve()
    if target.parent != root or not target.is_file():
        raise HTTPException(404, "备份不存在")
    text = read_text(target)
    return {"name": name, "text": text, "chars": len(text)}


@app.post("/api/profile/extract")
async def extract_profile_file(
    file: UploadFile = File(..., description=".docx / .md / .txt"),
) -> dict[str, Any]:
    """上传简历文件并提取纯文本。docx 走完整提取器。"""
    name = Path(file.filename or "upload").name
    ext = Path(name).suffix.lower()
    data = await file.read()

    if not data:
        raise HTTPException(400, "文件是空的")
    if len(data) > MAX_BYTES:
        raise HTTPException(
            413, f"文件太大（{len(data) / 1024 / 1024:.1f} MB），上限 {MAX_BYTES // 1024 // 1024} MB"
        )

    if ext in TEXT_EXTS:
        text = decode_bytes(data)
        return {
            "text": text,
            "filename": name,
            "chars": len(text),
            "summary": f"已读取纯文本 {len(text)} 字符",
            "warnings": [],
            "stats": {},
        }

    if ext in DOCX_EXTS:
        try:
            result = extract_docx(data, filename=name)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except Exception as exc:  # noqa: BLE001 - 损坏的 docx 可能抛各种异常
            raise HTTPException(400, f"解析 .docx 失败：{exc}") from exc

        return {
            "text": result.text,
            "filename": name,
            "chars": result.chars,
            "summary": result.summary(),
            "warnings": result.warnings,
            "stats": {
                "paragraphs": result.paragraphs,
                "tables": result.tables,
                "table_rows": result.table_rows,
                "textboxes": result.textboxes,
                "headers": result.headers,
                "footers": result.footers,
                "images": result.images,
            },
        }

    raise HTTPException(
        400,
        f"不支持的文件类型 {ext or '（无扩展名）'}。"
        f"请上传 {'/'.join(sorted(DOCX_EXTS | TEXT_EXTS))}。"
        "老版 .doc 和 .pdf 请先用 Word 另存为 .docx。",
    )


# ---------------------------------------------------------------- 流水线


@app.post("/api/run")
def start_run(
    request: RunRequest,
    x_deepseek_key: str | None = Header(default=None, alias=API_KEY_HEADER),
) -> dict[str, Any]:
    jd_text = (request.jd_text or "").strip()
    if not jd_text and not request.jd_name:
        raise HTTPException(400, "请选择一份 JD，或把 JD 原文粘贴进来")

    key = _resolve_key(x_deepseek_key)

    with _LOCK:
        busy = _running_job()
        if busy is not None:
            raise HTTPException(
                409, f"已有作业在运行（{busy.jd_label}），请等它跑完再提交"
            )

        job = Job(
            id=uuid.uuid4().hex[:12],
            jd_label=(request.jd_name or f"粘贴的 JD（{len(jd_text)} 字）"),
        )
        _JOBS[job.id] = job
        _JOB_KEYS[job.id] = key
        _prune_jobs()

        use_cache = not (SHARE_MODE and SHARE_MODE_DISABLE_CACHE)

    threading.Thread(
        target=_execute,
        args=(job.id,),
        kwargs={
            "jd_text": jd_text or None,
            "jd_name": None if jd_text else request.jd_name,
            "with_cover_letter": request.with_cover_letter,
            "with_interview": request.with_interview,
            "refresh": request.refresh,
            "use_cache": use_cache,
        },
        daemon=True,
        name=f"pipeline-{job.id}",
    ).start()

    return {"job_id": job.id}


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str) -> dict[str, Any]:
    with _LOCK:
        job = _JOBS.get(job_id)
        if job is None:
            raise HTTPException(404, "作业不存在或已过期")
        return job.to_dict()


@app.get("/api/download/{name}")
def download(name: str, job: str | None = Query(default=None)) -> FileResponse:
    """下载 outputs 目录下的产物。

    只允许直接子文件（防目录穿越）。分享模式下还要求带 ``?job=<id>``
    且该文件确实属于这个作业，避免访客互相下载到别人的简历。
    """
    if not name or Path(name).name != name:
        raise HTTPException(400, "非法文件名")

    if SHARE_MODE:
        if not job:
            raise HTTPException(403, "分享模式下必须带 job 参数才能下载")
        with _LOCK:
            owner = _JOBS.get(job)
            allowed = list(owner.artifacts) if owner else []
        if name not in allowed:
            raise HTTPException(403, "该文件不属于这个作业")

    root = Path(OUTPUT_DIR).resolve()
    target = (root / name).resolve()
    if target.parent != root or not target.is_file():
        raise HTTPException(404, "文件不存在")

    if target.suffix.lower() == ".docx":
        return FileResponse(
            target,
            media_type=(
                "application/vnd.openxmlformats-officedocument"
                ".wordprocessingml.document"
            ),
            filename=name,
        )
    # Markdown 直接在浏览器里以纯文本查看
    return FileResponse(target, media_type="text/plain; charset=utf-8")


if STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
