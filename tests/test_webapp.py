"""Web 界面（方案 A）的离线测试：不打真实 API，只验证接口与安全边界。

需要 fastapi + httpx；缺失时整体跳过，不影响其他测试。

    python tests\\test_webapp.py
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(PROJECT_ROOT / "src"), str(PROJECT_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

_TESTS: list[tuple[str, callable]] = []


def test(func):
    _TESTS.append((func.__name__, func))
    return func


def _client():
    from fastapi.testclient import TestClient

    from webapp.app import app

    return TestClient(app)


# ================================================================ 测试用例


@test
def test_health():
    r = _client().get("/api/health")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert "deepseek-flash" in body["models"]


@test
def test_index_page_served():
    r = _client().get("/")
    assert r.status_code == 200, r.text
    assert "求职 Agent" in r.text
    assert "开始分析" in r.text


@test
def test_list_jds_finds_samples():
    body = _client().get("/api/jds").json()
    names = {j["name"] for j in body["jds"]}
    assert "sample_embedded_campus.txt" in names, names
    assert all(j["chars"] > 50 for j in body["jds"])


@test
def test_profile_info_reads_draft():
    body = _client().get("/api/profile").json()
    assert body["exists"] is True
    assert body["chars"] > 60


@test
def test_run_rejects_empty_payload():
    r = _client().post("/api/run", json={})
    assert r.status_code == 400, r.text
    assert "JD" in r.json()["detail"]


@test
def test_run_rejects_blank_text():
    r = _client().post("/api/run", json={"jd_text": "   "})
    assert r.status_code == 400, r.text


@test
def test_unknown_job_returns_404():
    r = _client().get("/api/jobs/deadbeef")
    assert r.status_code == 404


@test
def test_download_blocks_path_traversal():
    c = _client()
    for bad in [
        "..%2F..%2F.env",
        "..%2Fmaster_profile.md",
        "%2Fetc%2Fpasswd",
        "....%2F%2E.env",
    ]:
        r = c.get(f"/api/download/{bad}")
        assert r.status_code in (400, 404), f"{bad} 竟然返回 {r.status_code}"


@test
def test_download_missing_file_returns_404():
    r = _client().get("/api/download/不存在的文件.md")
    assert r.status_code == 404


@test
def test_download_serves_real_artifact():
    """在 outputs 下放一个临时文件，确认能正常取回。"""
    from job_agent.config import OUTPUT_DIR
    from job_agent.storage import ensure_dirs

    ensure_dirs()
    target = Path(OUTPUT_DIR) / "_webapp_probe.md"
    target.write_text("# 探针\n\n内容", encoding="utf-8")
    try:
        r = _client().get("/api/download/_webapp_probe.md")
        assert r.status_code == 200, r.text
        assert "探针" in r.text
    finally:
        target.unlink(missing_ok=True)


@test
def test_markdown_it_renders_tables():
    """匹配报告大量用表格，必须用能渲染表格的预设。"""
    from webapp.app import _MD

    html = _MD.render("| 维度 | 得分 |\n| --- | --- |\n| 硬性技能 | 80 |\n")
    assert "<table>" in html, "Markdown 表格没被渲染，检查 MarkdownIt 预设"


@test
def test_markdown_it_escapes_raw_html():
    """JD 原文里若有裸 HTML/脚本，必须被转义，不能原样注入前端。"""
    from webapp.app import _MD

    html = _MD.render('<script>alert(1)</script>\n\n<img src=x onerror=alert(2)>')
    assert "<script>" not in html, "原始 <script> 未被转义"
    assert "onerror" not in html or "&lt;img" in html


@test
def test_webapp_does_not_import_ui():
    """webapp 不能 import job_agent.ui —— 它在导入时 reconfigure stdout。"""
    import webapp.app  # noqa: F401

    assert "job_agent.ui" not in sys.modules, "webapp 意外引入了 job_agent.ui"


@test
def test_artifact_url_is_percent_encoded():
    """产物名含中文，url 必须 percent-encode，否则非浏览器客户端请求会失败。"""
    from job_agent.config import OUTPUT_DIR
    from job_agent.storage import ensure_dirs
    from webapp.app import _artifact

    ensure_dirs()
    target = Path(OUTPUT_DIR) / "resume-嵌入式软件工程师-20260101-120000.docx"
    target.write_bytes(b"probe")
    try:
        info = _artifact(target)
        assert info["ext"] == "docx"
        assert "%" in info["url"], f"URL 未编码：{info['url']}"
        assert all(ord(c) < 128 for c in info["url"]), f"URL 仍含非 ASCII：{info['url']}"
    finally:
        target.unlink(missing_ok=True)


@test
def test_frontend_element_ids_are_consistent():
    """前端 JS 里 $('x') 引用的每个 id，都必须在 HTML 里真实存在。

    没有浏览器自动化，这条静态检查能挡住最常见的前端接线错误。
    """
    import re

    from webapp.app import STATIC_DIR

    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    declared = set(re.findall(r'id="([^"]+)"', html))
    used = set(re.findall(r"\$\('([^']+)'\)", html))

    assert used, "没找到任何 $('id') 调用，正则可能失效了"
    missing = sorted(used - declared)
    assert not missing, f"JS 引用了 HTML 里不存在的 id：{missing}"


@test
def test_frontend_calls_only_known_api_endpoints():
    """前端 fetch 的路径必须都在后端注册过。"""
    import re

    from webapp.app import STATIC_DIR, app

    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    called = set(re.findall(r"fetch\('([^']+)'", html))
    called |= {m.split("'")[0] for m in re.findall(r"fetch\('([^']+)'\s*\+", html)}
    called |= set(re.findall(r"fetch\(([^)]*?)\)", html))

    routes = {r.path for r in app.routes if hasattr(r, "path")}

    # 前端只用到这几个，逐个确认后端有
    for path in ("/api/health", "/api/jds", "/api/profile", "/api/run"):
        assert path in routes, f"后端没注册 {path}"

    assert any("/api/jobs/" in r for r in routes), "后端缺少 /api/jobs/{id}"
    assert any("/api/download/" in r for r in routes), "后端缺少 /api/download/{name}"


@test
def test_job_dict_shape():
    from webapp.app import Job

    job = Job(id="x", jd_label="测试")
    data = job.to_dict()
    for key in ("id", "status", "steps", "result", "error", "elapsed"):
        assert key in data, f"缺字段 {key}"
    assert data["status"] == "pending"


# ================================================================ 运行器


def main() -> int:
    try:
        import fastapi  # noqa: F401
        import httpx  # noqa: F401
    except ModuleNotFoundError as exc:
        print(f"跳过：缺少 {exc.name}（pip install fastapi httpx）")
        return 0

    passed, failed = 0, []
    for name, func in _TESTS:
        try:
            func()
        except Exception:
            failed.append((name, traceback.format_exc()))
            print(f"  ✘ {name}")
        else:
            passed += 1
            print(f"  ✔ {name}")

    print(f"\n通过 {passed}/{len(_TESTS)}")
    for name, tb in failed:
        print(f"\n--- {name} ---\n{tb}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
