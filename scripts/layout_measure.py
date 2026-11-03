#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按简历真实排版（A4 / 小四 / 2cm 页边距）排一份，量它到底占多少版面。

为什么不用 pandoc 默认样式量：
    pandoc 的默认 docx 是 Letter 纸、1 英寸页边距、段落间距 10pt，
    渲染出来占 72.8% 的页高 —— 但那是模板的问题，不是内容的体积。
    用户要的是"小四字号下不超过 1/3 张 A4"，就得按那个版式来量。

用法:
    python layout_measure.py docs/career/resume-project.md
"""
from __future__ import annotations

import re
import sys

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Cm, Pt

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

OUT = r"D:\Projects\qwen-local-tool-agent\docs\career\_layout_check.docx"


def set_font(run, size_pt=12, bold=False):
    run.font.size = Pt(size_pt)          # 小四 = 12pt
    run.font.bold = bold
    run.font.name = "宋体"
    run._element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")


def build(md_text: str) -> Document:
    doc = Document()
    sec = doc.sections[0]
    sec.page_width, sec.page_height = Cm(21.0), Cm(29.7)   # A4
    sec.top_margin = sec.bottom_margin = Cm(2.0)
    sec.left_margin = sec.right_margin = Cm(2.0)
    sec.header_distance = sec.footer_distance = Cm(1.0)

    # 正文默认样式
    st = doc.styles["Normal"]
    st.font.size = Pt(12)
    st.font.name = "宋体"
    st.element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")
    st.paragraph_format.space_before = Pt(0)
    st.paragraph_format.space_after = Pt(0)
    st.paragraph_format.line_spacing = 1.0

    for raw in md_text.split("\n"):
        line = raw.rstrip()
        if not line.strip():
            continue
        # 标题行（## 开头）：加粗、稍大
        if line.startswith("## "):
            p = doc.add_paragraph()
            p.paragraph_format.space_before = Pt(0)
            p.paragraph_format.space_after = Pt(0)
            set_font(p.add_run(line[3:].strip()), 12, bold=True)
            continue
        # 去掉行首的 - 列表符，但保留层级
        line = re.sub(r"^-\s+", "· ", line)
        p = doc.add_paragraph()
        p.paragraph_format.space_before = Pt(0)
        p.paragraph_format.space_after = Pt(0)
        p.paragraph_format.line_spacing = 1.0
        # 解析 **粗体**
        for i, seg in enumerate(re.split(r"\*\*(.+?)\*\*", line)):
            if not seg:
                continue
            set_font(p.add_run(seg), 12, bold=(i % 2 == 1))
    doc.save(OUT)
    return doc


def main():
    md = open(sys.argv[1], encoding="utf-8").read() if len(sys.argv) > 1 else ""
    if not md:
        print("需要 md 文件路径")
        return 1
    build(md)
    print(f"已生成 {OUT}（A4 / 小四 / 2cm 页边距）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
