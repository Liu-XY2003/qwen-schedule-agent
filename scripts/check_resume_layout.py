from pathlib import Path

# 本机用户目录。不写死用户名 —— 否则公开仓库里就暴露了。
_UP = str(Path.home())

import pathlib
import re
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from pypdf import PdfReader

ROOT = pathlib.Path(r"D:\Projects\qwen-local-tool-agent")
MD = ROOT / "docs" / "career" / "resume-project.md"
DOCX = ROOT / "docs" / "career" / "_layout_check.docx"
PDF = ROOT / "docs" / "career" / "_layout_check.pdf"

t = MD.read_text(encoding="utf-8")
hanzi = sum(1 for c in t if "\u4e00" <= c <= "\u9fff")
punct = sum(1 for c in t if c in "，。；：、（）「」【】—“”‘’！？·①②③④｜/")
words = len(re.findall(r"[A-Za-z0-9][A-Za-z0-9._/+#%=-]*", t))
total = hanzi + punct + words
print(f"字数: 汉字 {hanzi} + 标点 {punct} + 英文 {words} = {total}"
      f"  {'OK(500-600)' if 500 <= total <= 600 else '超出/偏少'}")

DPY = rf"{_UP}\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe"
NODE = rf"{_UP}\AppData\Local\Programs\DeepSeek Harness\resources\runtime\primary-runtime\dependencies\node\bin\node.exe"
CLI = rf"{_UP}\AppData\Local\Programs\DeepSeek Harness\resources\app.asar.unpacked\dsh\node_modules\@deepseek-ai\libreoffice-kit\lib\cli.js"

subprocess.run([DPY, str(ROOT / "scripts" / "layout_measure.py"), str(MD)],
               capture_output=True)
if PDF.exists():
    PDF.unlink()
subprocess.run([NODE, CLI, "convert", "--input", str(DOCX), "--output", str(PDF)],
               capture_output=True)

r = PdfReader(str(PDF))
pg = r.pages[0]
W, H = float(pg.mediabox.width), float(pg.mediabox.height)
items = []


def visit(text, cm, tm, fd, fs):
    if text and text.strip():
        items.append(round(tm[5], 1))


pg.extract_text(visitor_text=visit)
ys = sorted(set(items), reverse=True)
span = ys[0] - ys[-1]
pct = span / H * 100
print(f"版面: {len(ys)} 行, {span/72*2.54:.1f} cm, 占 A4 页高 {pct:.1f}%")
print("=> " + ("OK 在 1/3 页(33.3%)内" if pct <= 100 / 3
               else f"超 {pct-100/3:.1f} 个百分点 (需再省 {(span-H/3)/72*2.54:.1f} cm)"))
