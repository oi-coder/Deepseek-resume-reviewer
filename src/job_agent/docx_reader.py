"""把 .docx 简历提取成纯文本。

为什么不能只调 ``doc.paragraphs``
--------------------------------
实测（见 tests/test_docx_reader.py）：一份用**两栏表格**排版的中文简历，
只读 ``doc.paragraphs`` 只能拿到 1 段，正文几乎全丢 —— 因为内容都在表格里。
而两栏表格恰恰是中文简历最常见的排版方式。

所以本模块按**文档顺序**遍历 body，同时处理四处内容所在：

1. 正常段落            ``doc.paragraphs``
2. 表格                ``doc.tables``（且要处理合并单元格造成的重复）
3. 文本框 Text Box     藏在 ``w:txbxContent`` 里，python-docx 的 API 读不到
4. 页眉 / 页脚         在独立的 ``word/header*.xml`` 部件里

另外会先嗅探文件头，对 .doc / .pdf 给出明确提示而不是抛一个费解的异常。
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------- 文件头嗅探

_MAGIC = (
    (b"PK\x03\x04", "zip"),
    (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", "ole2"),
    (b"%PDF", "pdf"),
)

_EXT_HINT = {
    "zip": (
        "这个文件不包含 Word 文档结构（可能是 .odt、.zip，或改过扩展名）。"
        "请在 Word 里「另存为 → Word 文档 (*.docx)」后重试。"
    ),
    "ole2": (
        "这是旧版二进制 .doc 格式，python-docx 无法读取。"
        "请在 Word 里「另存为 → Word 文档 (*.docx)」后重试。"
    ),
    "pdf": (
        "不支持 PDF。请把简历导出为 .docx，或直接粘贴 / 上传 .md、.txt。"
    ),
    "unknown": (
        "无法识别的文件格式。支持 .docx、.md、.txt；"
        "如果是从其他工具导出的，请先另存为 .docx。"
    ),
}

#: 单个文件最大字节数，防止误传大文件把内存吃满
MAX_BYTES = 20 * 1024 * 1024


def sniff(data: bytes) -> str:
    """返回 'zip' / 'ole2' / 'pdf' / 'unknown'。"""
    for magic, kind in _MAGIC:
        if data.startswith(magic):
            return kind
    return "unknown"


# ---------------------------------------------------------------- 结果对象


@dataclass
class DocxExtraction:
    """提取结果：文本 + 统计 + 给用户看的提示。"""

    text: str = ""
    filename: str = ""
    paragraphs: int = 0
    tables: int = 0
    table_rows: int = 0
    textboxes: int = 0
    headers: int = 0
    footers: int = 0
    images: int = 0
    warnings: list[str] = field(default_factory=list)

    @property
    def chars(self) -> int:
        return len(self.text)

    def summary(self) -> str:
        """一句话说明提取到了什么，用于前端提示。"""
        bits = [f"{self.chars} 字符", f"{self.paragraphs} 段落"]
        if self.tables:
            bits.append(f"{self.tables} 表格/{self.table_rows} 行")
        if self.textboxes:
            bits.append(f"{self.textboxes} 文本框")
        if self.headers or self.footers:
            bits.append(f"{self.headers + self.footers} 页眉页脚")
        if self.images:
            bits.append(f"{self.images} 图片")
        return "已提取：" + "、".join(bits)


# ---------------------------------------------------------------- 工具


def _require_docx():
    try:
        import docx  # noqa: F401
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "解析 .docx 需要 python-docx，请先安装：\n"
            r"  python -m pip install python-docx"
        ) from exc
    return docx


def _clean(text: str) -> str:
    """压缩空白，去掉不可见字符。"""
    text = text.replace("\u00a0", " ").replace("\u3000", " ")
    return re.sub(r"[ \t]+", " ", text).strip()


#: 形如「第 1 页」「1 / 3」「- 2 -」的纯页码行，页脚里很常见，属于噪音
_PAGE_NUMBER_RE = re.compile(r"^(?:第\s*\d+\s*页(?:\s*[,/共]\s*\d+\s*页?)?|\d+\s*/\s*\d+|-+\s*\d+\s*-+)$")


def _is_noise(line: str) -> bool:
    return bool(_PAGE_NUMBER_RE.match(line.strip()))


def _iter_block_items(parent):
    """按**文档顺序**产出 Paragraph / Table。

    python-docx 的 ``doc.paragraphs`` 和 ``doc.tables`` 是两个独立列表，
    拿不到相对顺序；这里直接遍历 body 的子元素来保序。
    """
    from docx.document import Document as _Document
    from docx.oxml.table import CT_Tbl
    from docx.oxml.text.paragraph import CT_P
    from docx.table import Table, _Cell
    from docx.text.paragraph import Paragraph

    if isinstance(parent, _Document):
        element = parent.element.body
    elif isinstance(parent, _Cell):
        element = parent._tc
    else:  # pragma: no cover
        raise TypeError(f"不支持的类型：{type(parent)!r}")

    for child in element.iterchildren():
        if isinstance(child, CT_P):
            yield Paragraph(child, parent)
        elif isinstance(child, CT_Tbl):
            yield Table(child, parent)


def _textbox_texts(element) -> list[str]:
    """从任意 XML 元素里抠出所有文本框（w:txbxContent）的文字。

    python-docx 的 paragraph.text / table 都不会进入文本框，
    必须自己扫 XML。
    """
    from docx.oxml.ns import qn

    found: list[str] = []
    for box in element.iter(qn("w:txbxContent")):
        parts = [node.text for node in box.iter(qn("w:t")) if node.text]
        text = _clean("".join(parts))
        if text:
            found.append(text)
    return found


def _table_lines(table) -> list[str]:
    """把表格压成若干「a | b | c」行。

    合并单元格（gridSpan / vMerge）会让同一段文字被返回多次，
    这里按行内文本去重，避免简历里出现重复内容。
    """
    lines: list[str] = []
    for row in table.rows:
        seen_in_row: set[str] = set()
        cells: list[str] = []
        for cell in row.cells:
            text = _clean(cell.text.replace("\n", " "))
            if not text or text in seen_in_row:
                continue
            seen_in_row.add(text)
            cells.append(text)
        if cells:
            lines.append(" | ".join(cells))
    return lines


def _part_lines(part) -> list[str]:
    """页眉/页脚部件里的段落与表格。"""
    lines: list[str] = []
    for paragraph in part.paragraphs:
        text = _clean(paragraph.text)
        if text and not _is_noise(text):
            lines.append(text)
    for table in getattr(part, "tables", []):
        lines.extend(_table_lines(table))
    return lines


# ---------------------------------------------------------------- 主函数


def _open_document(data: bytes):
    """校验文件头并打开。.docx 本质是 zip，所以还要确认里面真有 word/document.xml。"""
    import zipfile

    from docx import Document

    kind = sniff(data)
    if kind != "zip":
        raise ValueError(_EXT_HINT[kind])

    try:
        names = zipfile.ZipFile(io.BytesIO(data)).namelist()
    except zipfile.BadZipFile as exc:
        raise ValueError("文件看起来已损坏，不是有效的 .docx。") from exc

    if "word/document.xml" not in names:
        raise ValueError(_EXT_HINT["zip"])

    return Document(io.BytesIO(data))


def extract_docx(
    source: bytes | bytearray | str | Path, *, filename: str = ""
) -> DocxExtraction:
    """从 .docx 提取纯文本。source 可以是字节流或文件路径。"""
    _require_docx()

    if isinstance(source, (bytes, bytearray)):
        data = bytes(source)
    else:
        path = Path(source)
        data = path.read_bytes()
        filename = filename or path.name

    if len(data) > MAX_BYTES:
        raise ValueError(
            f"文件太大（{len(data) / 1024 / 1024:.1f} MB），"
            f"上限 {MAX_BYTES // 1024 // 1024} MB。"
        )

    document = _open_document(data)

    result = DocxExtraction(filename=filename)

    # ---- 页眉（常放姓名/联系方式），放在最前面
    seen: set[str] = set()
    for section in document.sections:
        for part, counter in ((section.header, "headers"), (section.footer, "footers")):
            lines = _part_lines(part)
            if lines:
                setattr(result, counter, getattr(result, counter) + 1)
            for line in lines:
                if line not in seen:
                    seen.add(line)
                    if counter == "headers":
                        result.text += line + "\n"

    # ---- 正文：按文档顺序走段落与表格
    body_lines: list[str] = []
    textboxes_seen: set[str] = set()

    for block in _iter_block_items(document):
        name = type(block).__name__

        if name == "Paragraph":
            paragraph_text = _clean(block.text)
            if paragraph_text:
                result.paragraphs += 1
                body_lines.append(paragraph_text)
            # 段落里可能嵌着文本框
            for box_text in _textbox_texts(block._p):
                if box_text not in textboxes_seen:
                    textboxes_seen.add(box_text)
                    result.textboxes += 1
                    body_lines.append(box_text)

        elif name == "Table":
            result.tables += 1
            lines = _table_lines(block)
            result.table_rows += len(lines)
            body_lines.extend(lines)
            for box_text in _textbox_texts(block._tbl):
                if box_text not in textboxes_seen:
                    textboxes_seen.add(box_text)
                    result.textboxes += 1
                    body_lines.append(box_text)

    # ---- 兜底：body 里还有没被上面覆盖到的文本框
    for box_text in _textbox_texts(document.element.body):
        if box_text not in textboxes_seen:
            textboxes_seen.add(box_text)
            result.textboxes += 1
            body_lines.append(box_text)

    # ---- 正文去重（保持顺序），再接页脚
    final: list[str] = []
    for line in body_lines:
        if line and line not in seen:
            seen.add(line)
            final.append(line)

    try:
        result.images = len(document.inline_shapes)
    except Exception:  # noqa: BLE001 - 某些文档结构会取不到
        result.images = 0

    for section in document.sections:
        for line in _part_lines(section.footer):
            if line not in seen:
                seen.add(line)
                final.append(line)

    result.text = (result.text + "\n".join(final)).strip()

    # ---- 给用户看的提示
    if result.tables:
        result.warnings.append(
            f"检测到 {result.tables} 个表格，已按行展平为「单元格 | 单元格」的形式"
            "（表格排版常见于两栏简历，请检查顺序是否符合预期）"
        )
    if result.textboxes:
        result.warnings.append(
            f"检测到 {result.textboxes} 处文本框，已并入正文（文本框在 Word 里常放联系方式）"
        )
    if not result.text:
        result.warnings.append("没有提取到任何文字，可能是扫描件或纯图片简历")
    if result.images and result.chars < 200:
        result.warnings.append(
            f"文档含 {result.images} 张图片但文字很少，可能是图片版简历，无法提取"
        )

    return result
