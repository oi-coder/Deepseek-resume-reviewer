"""Web 层新功能测试：底稿编辑/备份、上传提取、按请求携带 API Key、分享模式。

安全约定：所有涉及底稿的用例都把 MASTER_PROFILE_MD 和 BACKUP_DIR
重定向到临时目录，**绝不碰用户真实的 data/master_profile.md**。

    python tests\\test_webapp_profile.py
"""

from __future__ import annotations

import io
import sys
import traceback
from contextlib import contextmanager
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


@contextmanager
def temp_profile(initial: str | None = None):
    """把底稿与备份目录指向临时位置。

    用 patch 模块全局而不是改 config，因为 app.py 里是
    ``from job_agent.config import MASTER_PROFILE_MD`` 的绑定。
    """
    import tempfile

    from webapp import app as webapp_app

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        old_md = webapp_app.MASTER_PROFILE_MD
        old_bk = webapp_app.BACKUP_DIR
        webapp_app.MASTER_PROFILE_MD = root / "master_profile.md"
        webapp_app.BACKUP_DIR = root / "backups"
        webapp_app.BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        if initial is not None:
            webapp_app.MASTER_PROFILE_MD.write_text(initial, encoding="utf-8")
        try:
            yield webapp_app
        finally:
            webapp_app.MASTER_PROFILE_MD = old_md
            webapp_app.BACKUP_DIR = old_bk


@contextmanager
def share_mode(enabled: bool):
    from webapp import app as webapp_app

    old = webapp_app.SHARE_MODE
    webapp_app.SHARE_MODE = enabled
    try:
        yield
    finally:
        webapp_app.SHARE_MODE = old


DRAFT = "# 底稿\n" + "这是用于测试的简历内容。" * 20  # > MIN_PROFILE_CHARS


# ================================================================ 配置


@test
def test_config_exposes_mode_and_header():
    body = _client().get("/api/config").json()
    assert "share_mode" in body
    assert body["api_key_header"] == "X-DeepSeek-Key"
    assert body["max_upload_mb"] > 0
    assert ".docx" in body["docx_exts"]
    assert ".md" in body["text_exts"]
    assert body["min_profile_chars"] > 0


# ================================================================ 底稿编辑


@test
def test_get_profile_raw_returns_text_and_backups():
    with temp_profile(DRAFT):
        body = _client().get("/api/profile/raw").json()
        assert body["exists"] is True
        assert body["chars"] == len(DRAFT)
        assert body["text"] == DRAFT
        assert body["backups"] == []


@test
def test_save_profile_creates_backup():
    with temp_profile(DRAFT):
        c = _client()
        new = DRAFT + "\n新增一段经历。"
        r = c.post("/api/profile/raw", json={"text": new})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert body["previous_chars"] == len(DRAFT)
        assert body["backup"], "保存时必须生成备份"
        assert len(body["backups"]) == 1

        # 磁盘上确实更新了
        assert c.get("/api/profile/raw").json()["text"] == new


@test
def test_save_rejects_too_short():
    with temp_profile(DRAFT):
        r = _client().post("/api/profile/raw", json={"text": "太短"})
        assert r.status_code == 400, r.text
        assert "太短" in r.json()["detail"]


@test
def test_save_rejects_big_shrink_without_flag():
    """3000 字变 200 字多半是误覆盖，必须二次确认。"""
    with temp_profile(DRAFT):
        # 80 字符：过了 MIN_PROFILE_CHARS，但不足原文的 50%
        small = "确认缩短后的内容。" * 8  # 72 字符
        assert len(small) >= 60, len(small)
        assert len(small) < len(DRAFT) * 0.5, len(small)
        r = _client().post("/api/profile/raw", json={"text": small})
        assert r.status_code == 409, r.text
        assert "误覆盖" in r.json()["detail"]


@test
def test_save_allows_shrink_with_flag():
    with temp_profile(DRAFT):
        small = "确认缩短后的内容。" * 8
        r = _client().post(
            "/api/profile/raw", json={"text": small, "allow_shrink": True}
        )
        assert r.status_code == 200, r.text
        assert r.json()["chars"] == len(small.strip())


@test
def test_get_and_post_report_same_char_count():
    """GET 与 POST 的 chars 口径必须一致，否则前后端显示会对不上。"""
    with temp_profile(DRAFT):
        c = _client()
        original = c.get("/api/profile/raw").json()

        r = c.post("/api/profile/raw", json={"text": original["text"]})
        assert r.status_code == 200, r.text
        assert r.json()["chars"] == original["chars"], (
            f"POST 返回 {r.json()['chars']}，GET 返回 {original['chars']}"
        )

        after = c.get("/api/profile/raw").json()
        assert after["text"] == original["text"], "内容往返必须完全一致"
        assert after["chars"] == original["chars"]


@test
def test_newline_round_trip_is_exact():
    """Windows 会把 \\n 写成 \\r\\n，读取时必须还原，否则往返不相等。"""
    with temp_profile(DRAFT):
        c = _client()
        text = "第一行\n第二行\n\n第四行\n" + "填充内容" * 80  # 长于 DRAFT，不触发缩短保护
        assert len(text) >= len(DRAFT), (len(text), len(DRAFT))

        r = c.post("/api/profile/raw", json={"text": text})
        assert r.status_code == 200, r.text

        back = c.get("/api/profile/raw").json()["text"]
        assert "\r" not in back, "读取结果里不该出现 \\r"
        assert back == text


@test
def test_restore_backup_brings_back_previous():
    with temp_profile(DRAFT):
        c = _client()
        new = DRAFT + "\n第二版内容。"
        c.post("/api/profile/raw", json={"text": new})
        backup_name = c.get("/api/profile/raw").json()["backups"][0]["name"]

        r = c.post("/api/profile/restore", json={"name": backup_name})
        assert r.status_code == 200, r.text
        assert r.json()["text"] == DRAFT, "恢复后应当是备份里的原始内容"


@test
def test_read_backup_content():
    with temp_profile(DRAFT):
        c = _client()
        c.post("/api/profile/raw", json={"text": DRAFT + "\n改动。"})
        name = c.get("/api/profile/raw").json()["backups"][0]["name"]

        r = c.get(f"/api/profile/backup/{name}")
        assert r.status_code == 200, r.text
        assert r.json()["text"] == DRAFT


@test
def test_backup_endpoint_blocks_traversal():
    with temp_profile(DRAFT):
        c = _client()
        for bad in ["..%2F..%2F.env", "..%2Fmaster_profile.md"]:
            r = c.get(f"/api/profile/backup/{bad}")
            assert r.status_code in (400, 404), f"{bad} -> {r.status_code}"


@test
def test_restore_unknown_backup_returns_404():
    with temp_profile(DRAFT):
        r = _client().post("/api/profile/restore", json={"name": "不存在.md"})
        assert r.status_code == 404


# ================================================================ 上传提取


@test
def test_extract_plain_text_upload():
    with temp_profile(DRAFT):
        files = {"file": ("my.md", "纯文本简历内容".encode("utf-8"), "text/markdown")}
        r = _client().post("/api/profile/extract", files=files)
        assert r.status_code == 200, r.text
        assert "纯文本简历内容" in r.json()["text"]


@test
def test_extract_gbk_text_upload():
    """国内简历常见 gbk 编码，必须能读。"""
    with temp_profile(DRAFT):
        data = "中文简历内容".encode("gbk")
        files = {"file": ("a.txt", data, "text/plain")}
        r = _client().post("/api/profile/extract", files=files)
        assert r.status_code == 200, r.text
        assert "中文简历内容" in r.json()["text"]


@test
def test_extract_docx_with_table_layout():
    """端到端：表格式排版简历上传后，表格内容必须全部提取到。"""
    from docx import Document

    doc = Document()
    doc.add_paragraph("张伟 138-0000-0000")
    table = doc.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "技能"
    table.cell(0, 1).text = "经历"
    table.cell(1, 0).text = "Python / FastAPI"
    table.cell(1, 1).text = "2022 某科技 高级后端"
    buf = io.BytesIO()
    doc.save(buf)

    with temp_profile(DRAFT):
        files = {
            "file": (
                "resume.docx",
                buf.getvalue(),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        }
        r = _client().post("/api/profile/extract", files=files)
        assert r.status_code == 200, r.text
        body = r.json()
        for expected in ("张伟", "Python / FastAPI", "2022 某科技 高级后端"):
            assert expected in body["text"], f"表格内容丢失：{expected}"
        assert body["stats"]["tables"] == 1
        assert body["warnings"], "有表格时应当给出提示"


@test
def test_extract_old_doc_rejected_with_hint():
    with temp_profile(DRAFT):
        fake = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 100
        files = {"file": ("old.doc", fake, "application/msword")}
        r = _client().post("/api/profile/extract", files=files)
        assert r.status_code == 400, r.text
        detail = r.json()["detail"]
        assert "doc" in detail.lower()
        assert "另存为" in detail


@test
def test_extract_unsupported_extension_rejected():
    with temp_profile(DRAFT):
        files = {"file": ("x.pdf", b"%PDF-1.7\n", "application/pdf")}
        r = _client().post("/api/profile/extract", files=files)
        assert r.status_code == 400, r.text
        assert "不支持" in r.json()["detail"]


@test
def test_extract_empty_file_rejected():
    with temp_profile(DRAFT):
        files = {"file": ("empty.md", b"", "text/markdown")}
        r = _client().post("/api/profile/extract", files=files)
        assert r.status_code == 400


# ================================================================ API Key


@test
def test_with_api_key_does_not_mutate_global_settings():
    """按请求派生 Settings 不能污染全局单例，否则并发会串 Key。"""
    from job_agent.config import get_settings, with_api_key

    before = get_settings().api_key
    derived = with_api_key(get_settings(), "sk-visitor-key")

    assert derived.api_key == "sk-visitor-key"
    assert get_settings().api_key == before, "全局 Settings 被改动了！"
    assert derived is not get_settings()


@test
def test_resolve_key_prefers_visitor_key():
    from webapp.app import _resolve_key

    assert _resolve_key("sk-visitor") == "sk-visitor"
    assert _resolve_key("  sk-spaced  ") == "sk-spaced"


@test
def test_share_mode_requires_visitor_key():
    from fastapi import HTTPException

    from webapp.app import _resolve_key

    with share_mode(True):
        try:
            _resolve_key(None)
        except HTTPException as exc:
            assert exc.status_code == 401, exc.status_code
            assert "你自己的" in exc.detail
        else:
            raise AssertionError("分享模式下没有 Key 应当拒绝")


@test
def test_local_mode_falls_back_to_env_key():
    from job_agent.config import get_settings

    from webapp.app import _resolve_key

    with share_mode(False):
        assert _resolve_key(None) == get_settings().api_key


@test
def test_run_endpoint_rejects_without_key_in_share_mode():
    with temp_profile(DRAFT), share_mode(True):
        r = _client().post("/api/run", json={"jd_text": "测试 JD " * 20})
        assert r.status_code == 401, r.text


@test
def test_share_mode_download_requires_job_param():
    """分享模式下不能裸下载，否则访客能拿到别人的简历。"""
    from job_agent.config import OUTPUT_DIR

    with temp_profile(DRAFT), share_mode(True):
        probe = Path(OUTPUT_DIR) / "_share_probe.md"
        probe.write_text("他人简历", encoding="utf-8")
        try:
            c = _client()
            r = c.get("/api/download/_share_probe.md")
            assert r.status_code == 403, f"应当拒绝裸下载，实际 {r.status_code}"

            r2 = c.get("/api/download/_share_probe.md?job=nonexistent")
            assert r2.status_code == 403, "作业不存在时也应拒绝"
        finally:
            probe.unlink(missing_ok=True)


@test
def test_local_mode_download_needs_no_job_param():
    from job_agent.config import OUTPUT_DIR

    probe = Path(OUTPUT_DIR) / "_local_probe.md"
    probe.write_text("本机内容", encoding="utf-8")
    try:
        with share_mode(False):
            r = _client().get("/api/download/_local_probe.md")
            assert r.status_code == 200, r.text
    finally:
        probe.unlink(missing_ok=True)


# ================================================================ 运行器


def main() -> int:
    try:
        import fastapi  # noqa: F401
        import httpx  # noqa: F401
    except ModuleNotFoundError as exc:
        print(f"跳过：缺少 {exc.name}")
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
