"""文件读写、缓存、文件名处理等通用工具。"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import CACHE_DIR, JD_DIR, OUTPUT_DIR, ensure_dirs

# ---------------------------------------------------------------- 文本读写


def decode_bytes(data: bytes) -> str:
    """把字节按 utf-8 / gbk 依次尝试解码，并统一换行符为 ``\\n``。

    统一换行很关键：Windows 上写文件默认会把 ``\\n`` 变成 ``\\r\\n``，
    如果读回来不还原，字符数就对不上、底稿往返比较永远不相等、
    按文本哈希做的缓存也会莫名失效。
    """
    text: str | None = None
    for encoding in ("utf-8-sig", "utf-8", "gbk"):
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        text = data.decode("utf-8", errors="ignore")
    return text.replace("\r\n", "\n").replace("\r", "\n")


def read_text(path: str | Path) -> str:
    """读取文本文件，自动尝试 utf-8 / gbk（国内 JD 常见编码）。"""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"文件不存在：{path}")
    return decode_bytes(path.read_bytes())


def _write(path: Path, content: str) -> None:
    """统一以 utf-8 + LF 写出，保证与 read_text 精确往返。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(content)


def write_text(path: str | Path, content: str) -> Path:
    path = Path(path)
    _write(path, content)
    return path


def write_text_atomic(path: str | Path, content: str) -> Path:
    """原子写入：先写临时文件再替换，避免中途失败留下半个文件。

    底稿是唯一事实来源，半截文件比写入失败更糟。
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    _write(tmp, content)
    os.replace(tmp, path)  # Windows 上也是原子的
    return path


# ---------------------------------------------------------------- 备份


def backup_file(
    path: str | Path,
    *,
    backup_dir: str | Path | None = None,
    keep: int | None = None,
) -> Path | None:
    """把文件复制一份到备份目录，返回备份路径（源文件不存在则返回 None）。

    备份名形如 ``master_profile-20261010-181500.md``，按时间倒序保留 keep 份。
    """
    from .config import BACKUP_DIR, BACKUP_KEEP

    source = Path(path)
    if not source.is_file():
        return None

    directory = Path(backup_dir) if backup_dir else Path(BACKUP_DIR)
    directory.mkdir(parents=True, exist_ok=True)
    keep = BACKUP_KEEP if keep is None else keep

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")[:-3]
    target = directory / f"{source.stem}-{stamp}{source.suffix or '.md'}"
    shutil.copy2(source, target)

    # 只留最近 keep 份
    existing = sorted(
        (p for p in directory.iterdir() if p.is_file() and p.stem.startswith(source.stem)),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for old in existing[keep:]:
        try:
            old.unlink()
        except OSError:
            pass

    return target


def list_backups(
    path: str | Path, *, backup_dir: str | Path | None = None
) -> list[dict[str, Any]]:
    """列出某个文件的备份，按时间倒序。"""
    from .config import BACKUP_DIR

    source = Path(path)
    directory = Path(backup_dir) if backup_dir else Path(BACKUP_DIR)
    if not directory.is_dir():
        return []

    items = []
    for item in directory.iterdir():
        if not item.is_file() or not item.stem.startswith(source.stem):
            continue
        stat = item.stat()
        items.append(
            {
                "name": item.name,
                "size": stat.st_size,
                "mtime": stat.st_mtime,
                "time": datetime.fromtimestamp(stat.st_mtime).strftime(
                    "%Y-%m-%d %H:%M:%S"
                ),
            }
        )
    items.sort(key=lambda x: x["mtime"], reverse=True)
    return items


def restore_backup(
    backup_name: str,
    target: str | Path,
    *,
    backup_dir: str | Path | None = None,
    keep_current: bool = True,
) -> Path:
    """从备份恢复。恢复前先把当前内容另存一份，避免「恢复错了就没救了」。"""
    from .config import BACKUP_DIR

    directory = Path(backup_dir) if backup_dir else Path(BACKUP_DIR)
    source = (directory / Path(backup_name).name).resolve()

    # 只允许恢复备份目录下的直接子文件
    if source.parent != directory.resolve() or not source.is_file():
        raise FileNotFoundError(f"找不到备份：{backup_name}")

    destination = Path(target)
    if keep_current and destination.is_file():
        backup_file(destination, backup_dir=directory)

    write_text_atomic(destination, source.read_text(encoding="utf-8"))
    return destination


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
