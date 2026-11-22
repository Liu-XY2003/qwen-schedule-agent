#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""markdown -> PDF（A4 / 小四 / 2cm 边距 / 紧凑行距），并报告实际页数。

为什么要两步走：
    · pandoc 负责 **Markdown 保真**（表格、代码块、引用、列表都能正确转）
    · python-docx 负责 **版式**（A4 纸、小四字号、页边距、段落间距）
    自己解析 Markdown 再排版那条路走不通 —— 表格和代码块会被当普通段落，
    页数会被严重低估（实测同一份文档：简易解析 2.8 页 vs 正式渲染 6 页）。

用法:
    python md_to_pdf.py <input.md> [output.pdf]
"""
from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path

# 本机用户目录。不写死用户名 —— 否则公开仓库里就暴露了。
_UP = str(Path.home())

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from docx import Document  # noqa: E402
from docx.oxml.ns import qn  # noqa: E402
from docx.shared import Cm, Pt  # noqa: E402

PANDOC = r"C:\Program Files\Pandoc\pandoc.exe"
NODE = (rf"{_UP}\AppData\Local\Programs\DeepSeek Harness\resources"
        r"\runtime\primary-runtime\dependencies\node\bin\node.exe")
CLI = (rf"{_UP}\AppData\Local\Programs\DeepSeek Harness\resources"
       r"\app.asar.unpacked\dsh\node_modules\@deepseek-ai\libreoffice-kit\lib\cli.js")

BODY_PT = 12          # 小四
TABLE_PT = 10.5       # 五号
CODE_PT = 10


def style_docx(path: Path, body_pt: float = BODY_PT, table_pt: float = TABLE_PT) -> None:
    d = Document(str(path))
    for sec in d.sections:
        sec.page_width, sec.page_height = Cm(21.0), Cm(29.7)
        sec.top_margin = sec.bottom_margin = Cm(2.0)
        sec.left_margin = sec.right_margin = Cm(2.0)

    # markdown 的软换行会被 pandoc 渲染成"独立的空格 run"，于是中文段落里出现
    # "排周计划 要一次处理"这种词间空格。
    # 处理办法：遇到纯空白的 run，看它前后的字符 —— 两侧都是中文就删掉这个空格；
    # 只要有一侧是英文/数字就保留（"一个 4B"少了空格会连成一片）。
    CPUNCT = "，。、；：！？）】」』》"

    def is_cjk(ch: str) -> bool:
        return ("\u4e00" <= ch <= "\u9fff") or (ch in CPUNCT) or (ch in "（【「『《")

    def drop_soft_break_spaces(runs):
        for i, r in enumerate(runs):
            if r.text and r.text.strip() == "":
                prev = next((x.text for x in reversed(runs[:i]) if x.text.strip()), "")
                nxt = next((x.text for x in runs[i + 1:] if x.text.strip()), "")
                if prev and nxt and is_cjk(prev[-1]) and is_cjk(nxt[0]):
                    r.text = ""

    def fix_run(r, size, mono=False):
        r.font.size = Pt(size)
        if mono:
            # 代码块必须等宽，否则缩进和伪代码对不齐
            r.font.name = "Consolas"
            if r._element.rPr is not None and r._element.rPr.rFonts is not None:
                r._element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")
            return
        r.font.name = "宋体"
        if r._element.rPr is not None and r._element.rPr.rFonts is not None:
            r._element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")

    for p in d.paragraphs:
        is_code = "Source" in p.style.name or "Code" in p.style.name
        pf = p.paragraph_format
        pf.space_before = Pt(0)
        pf.space_after = Pt(2)
        pf.line_spacing = 1.0
        if not is_code:
            drop_soft_break_spaces(p.runs)
        for r in p.runs:
            fix_run(r, body_pt - 0.5 if is_code else body_pt, mono=is_code)

    for tb in d.tables:
        for row in tb.rows:
            # 禁止行内跨页拆分：否则一行会被切成"页底半行 + 页顶半行"，很难看
            trPr = row._tr.get_or_add_trPr()
            if trPr.find(qn("w:cantSplit")) is None:
                from docx.oxml import OxmlElement
                trPr.append(OxmlElement("w:cantSplit"))
            for cell in row.cells:
                for p in cell.paragraphs:
                    p.paragraph_format.space_before = Pt(0)
                    p.paragraph_format.space_after = Pt(0)
                    p.paragraph_format.line_spacing = 1.0
                    for r in p.runs:
                        fix_run(r, table_pt)
    d.save(str(path))


def to_pdf(docx: Path, pdf: Path) -> None:
    if pdf.exists():
        pdf.unlink()
    subprocess.run([NODE, CLI, "convert", "--input", str(docx), "--output", str(pdf)],
                   capture_output=True)


def main() -> int:
    if len(sys.argv) < 2:
        print("用法: python md_to_pdf.py <input.md> [output.pdf] [正文字号pt]")
        return 2
    md = Path(sys.argv[1])
    pdf = Path(sys.argv[2]) if len(sys.argv) > 2 else md.with_suffix(".pdf")
    body_pt = float(sys.argv[3]) if len(sys.argv) > 3 else BODY_PT
    table_pt = max(8.0, body_pt - 1.5)

    with tempfile.TemporaryDirectory() as td:
        docx = Path(td) / "doc.docx"
        r = subprocess.run([PANDOC, str(md), "-o", str(docx), "-V", "lang=zh-CN"],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace")
        if r.returncode != 0:
            print("pandoc 失败:", r.stderr[:500])
            return 1
        style_docx(docx, body_pt, table_pt)
        to_pdf(docx, pdf)

    from pypdf import PdfReader
    rd = PdfReader(str(pdf))
    H = float(rd.pages[0].mediabox.height)
    total = 0.0
    for pg in rd.pages:
        ys = []
        pg.extract_text(visitor_text=lambda tx, cm, tm, fd, fs:
                        ys.append(round(tm[5], 1)) if tx and tx.strip() else None)
        if ys:
            total += (max(ys) - min(ys)) / 72 * 2.54
    pages = total / (H / 72 * 2.54)
    print(f"{pdf}")
    print(f"  页数 {len(rd.pages)}  正文 {total:.1f} cm ≈ {pages:.2f} 页 A4")
    return 0


if __name__ == "__main__":
    sys.exit(main())
