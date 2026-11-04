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
MD = ROOT / "docs" / "career" / "interview-pack.md"
DOCX = ROOT / "docs" / "career" / "_ip.docx"
PDF = ROOT / "docs" / "career" / "_ip.pdf"

t = MD.read_text(encoding="utf-8")
hanzi = sum(1 for c in t if "\u4e00" <= c <= "\u9fff")
punct = sum(1 for c in t if c in "，。；：、（）「」【】—“”‘’！？·①②③④｜/")
words = len(re.findall(r"[A-Za-z0-9][A-Za-z0-9._/+#%=-]*", t))
print(f"字数: 汉字 {hanzi} + 标点 {punct} + 英文 {words} = {hanzi+punct+words}")

DPY = rf"{_UP}\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe"
NODE = rf"{_UP}\AppData\Local\Programs\DeepSeek Harness\resources\runtime\primary-runtime\dependencies\node\bin\node.exe"
CLI = rf"{_UP}\AppData\Local\Programs\DeepSeek Harness\resources\app.asar.unpacked\dsh\node_modules\@deepseek-ai\libreoffice-kit\lib\cli.js"

# 用简历同款版式（A4/小四/2cm/单倍行距）量，比 pandoc 默认更贴近真实阅读
subprocess.run([DPY, str(ROOT / "scripts" / "layout_measure.py"), str(MD)], capture_output=True)
if DOCX.exists():
    DOCX.unlink()
(ROOT / "docs" / "career" / "_layout_check.docx").replace(DOCX)

for p in (PDF,):
    if p.exists():
        p.unlink()
subprocess.run([NODE, CLI, "convert", "--input", str(DOCX), "--output", str(PDF)],
               capture_output=True)

r = PdfReader(str(PDF))
W, H = float(r.pages[0].mediabox.width), float(r.pages[0].mediabox.height)
total_cm = 0.0
for pg in r.pages:
    ys = []
    pg.extract_text(visitor_text=lambda tx, cm, tm, fd, fs:
                    ys.append(round(tm[5], 1)) if tx and tx.strip() else None)
    if ys:
        total_cm += (max(ys) - min(ys)) / 72 * 2.54

print(f"页数 {len(r.pages)}  页面 {W/72*2.54:.1f} x {H/72*2.54:.1f} cm")
print(f"正文总高 {total_cm:.1f} cm = {total_cm/(H/72*2.54):.2f} 页 A4")
print("=> " + ("OK 未超 5 页" if len(r.pages) <= 5 else f"超限 {len(r.pages)-5} 页，需精简"))
