"""FastAPI Web 界面（方案 A）。

设计要点：
1. **不 import `job_agent.ui`** —— 它在导入时会 reconfigure stdout，
   对服务器进程是副作用。进度改用自定义回调传递。
2. **后台线程跑流水线** —— 单步 LLM 调用实测 14~48 秒，
   直接在请求里同步执行会让界面假死。
3. **同一时刻只允许一个作业** —— 避免误连点导致重复烧 token。
4. **Markdown 用 `js-default` 预设** —— 默认预设不渲染表格，
   而匹配报告大量用表格。
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

from fastapi import FastAPI, HTTPException
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
    FLASH_MODEL,
    JD_DIR,
    MASTER_PROFILE_MD,
    OUTPUT_DIR,
    VALID_MODELS,
)
from job_agent.pipeline import PipelineResult, run_pipeline  # noqa: E402
from job_agent.profile import load_cached_profile  # noqa: E402
from job_agent.storage import read_text  # noqa: E402

STATIC_DIR = Path(__file__).resolve().parent / "static"

# html=False：JD 原文里的裸 HTML 会被转义，避免注入
_MD = MarkdownIt("js-default", {"html": False})

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


def _artifact(path: Path) -> dict[str, Any]:
    return {
        "name": path.name,
        "size": path.stat().st_size,
        "ext": path.suffix.lstrip("."),
        # 产物名含中文，必须 percent-encode，否则非浏览器客户端无法请求
        "url": f"/api/download/{quote(path.name)}",
    }


def _serialize(result: PipelineResult) -> dict[str, Any]:
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
        "artifacts": [_artifact(p) for p in result.artifacts if p.is_file()],
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
) -> None:
    job = _JOBS[job_id]

    def progress(message: str) -> None:
        with _LOCK:
            job.steps.append(message)

    try:
        with _LOCK:
            job.status = "running"

        result = run_pipeline(
            jd_text=jd_text,
            jd_path=jd_name,
            with_resume=True,
            with_cover_letter=with_cover_letter,
            with_interview=with_interview,
            refresh=refresh,
            progress=progress,
        )
        payload = _serialize(result)

        with _LOCK:
            job.result = payload
            job.status = "done"
            job.steps.append("完成")
    except Exception as exc:  # noqa: BLE001 - 任何失败都要如实回报给前端
        with _LOCK:
            job.error = f"{type(exc).__name__}: {exc}"
            job.status = "error"
    finally:
        with _LOCK:
            job.finished_at = time.time()


# ================================================================ API 模型


class RunRequest(BaseModel):
    jd_name: str | None = Field(default=None, description="data/jds 下的文件名")
    jd_text: str | None = Field(default=None, description="直接粘贴的 JD 原文")
    with_cover_letter: bool = False
    with_interview: bool = False
    refresh: bool = False


# ================================================================ 应用


app = FastAPI(title="求职 Agent", docs_url="/api/docs", openapi_url="/api/openapi.json")


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    page = STATIC_DIR / "index.html"
    if not page.is_file():
        raise HTTPException(500, "找不到 static/index.html")
    return HTMLResponse(page.read_text(encoding="utf-8"))


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


@app.post("/api/run")
def start_run(request: RunRequest) -> dict[str, Any]:
    jd_text = (request.jd_text or "").strip()
    if not jd_text and not request.jd_name:
        raise HTTPException(400, "请选择一份 JD，或把 JD 原文粘贴进来")

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
        _prune_jobs()

    threading.Thread(
        target=_execute,
        args=(job.id,),
        kwargs={
            "jd_text": jd_text or None,
            "jd_name": None if jd_text else request.jd_name,
            "with_cover_letter": request.with_cover_letter,
            "with_interview": request.with_interview,
            "refresh": request.refresh,
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
def download(name: str) -> FileResponse:
    """下载 outputs 目录下的产物。只允许直接子文件，防止目录穿越。"""
    if not name or Path(name).name != name:
        raise HTTPException(400, "非法文件名")

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
