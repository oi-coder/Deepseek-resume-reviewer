"""文件读写、缓存、文件名处理等通用工具。"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import CACHE_DIR, JD_DIR, OUTPUT_DIR, ensure_dirs

# ---------------------------------------------------------------- 文本读写


def read_text(path: str | Path) -> str:
    """读取文本文件，自动尝试 utf-8 / gbk（国内 JD 常见编码）。"""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"文件不存在：{path}")

    for encoding in ("utf-8", "utf-8-sig", "gbk"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    # 最后兜底，忽略无法解码的字节
    return path.read_text(encoding="utf-8", errors="ignore")


def write_text(path: str | Path, content: str) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def dump_json(data: Any, *, indent: int = 2) -> str:
    """把 Pydantic 模型或普通对象序列化成可读 JSON。"""
    if hasattr(data, "model_dump"):
        data = data.model_dump(mode="json")
    return json.dumps(data, ensure_ascii=False, indent=indent, default=str)


# ---------------------------------------------------------------- 文件名


_SLUG_KEEP = re.compile(r"[^\w\u4e00-\u9fff]+", re.UNICODE)


def slugify(text: str, *, fallback: str = "untitled", max_length: int = 60) -> str:
    """生成安全的文件名片段：保留中英文、数字、下划线，其余替换成连字符。"""
    slug = _SLUG_KEEP.sub("-", (text or "").strip()).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    if not slug:
        slug = fallback
    return slug[:max_length].strip("-") or fallback


def timestamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def output_path(stem: str, suffix: str, *, subdir: str | None = None) -> Path:
    """在 outputs/ 下拼一个带时间戳的输出路径。"""
    ensure_dirs()
    base = OUTPUT_DIR / subdir if subdir else OUTPUT_DIR
    base.mkdir(parents=True, exist_ok=True)
    return base / f"{slugify(stem)}-{timestamp()}{suffix}"


def resolve_jd_path(name: str) -> Path:
    """把用户给的 JD 参数解析成真实文件路径。

    支持：绝对路径、相对当前目录的路径、data/jds 下的文件名（可省略扩展名）。
    """
    candidate = Path(name)
    if candidate.is_file():
        return candidate

    jd_dir = Path(JD_DIR)
    if jd_dir.is_dir():
        direct = jd_dir / name
        if direct.is_file():
            return direct
        # 允许省略扩展名
        for suffix in (".txt", ".md", ".json"):
            if (jd_dir / f"{name}{suffix}").is_file():
                return jd_dir / f"{name}{suffix}"

    raise FileNotFoundError(
        f"找不到 JD 文件：{name}\n"
        f"可以传绝对路径，或把 JD 放到 {jd_dir} 目录下再传文件名。"
    )


# ---------------------------------------------------------------- 缓存


def _cache_file(kind: str, key: str) -> Path:
    ensure_dirs()
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:20]
    directory = Path(CACHE_DIR) / kind
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"{digest}.json"


def load_cache(kind: str, key: str) -> dict | None:
    path = _cache_file(kind, key)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def save_cache(kind: str, key: str, data: Any) -> Path:
    path = _cache_file(kind, key)
    if hasattr(data, "model_dump"):
        data = data.model_dump(mode="json")
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    return path


def clear_cache() -> int:
    """清空缓存目录，返回删除的文件数。"""
    if not Path(CACHE_DIR).is_dir():
        return 0
    count = 0
    for file in Path(CACHE_DIR).rglob("*.json"):
        try:
            file.unlink()
            count += 1
        except OSError:
            pass
    return count
