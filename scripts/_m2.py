import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from pypdf import PdfReader

r = PdfReader(r"D:\Projects\qwen-local-tool-agent\docs\career\_layout_check.pdf")
pg = r.pages[0]
W, H = float(pg.mediabox.width), float(pg.mediabox.height)
items = []


def visit(text, cm, tm, font_dict, font_size):
    if text and text.strip():
        items.append((round(tm[5], 1), round(tm[4], 1), text.strip()))


pg.extract_text(visitor_text=visit)
ys = sorted({y for y, x, t in items}, reverse=True)
span = ys[0] - ys[-1]
gaps = sorted(ys[i] - ys[i + 1] for i in range(len(ys) - 1) if ys[i] - ys[i + 1] > 1)
print(f"页面 {W/72*2.54:.1f} x {H/72*2.54:.1f} cm (A4)")
print(f"行数 {len(ys)} | 行距中位 {gaps[len(gaps)//2]:.1f} pt | 页数 {len(r.pages)}")
print(f"正文跨度 {span/72*2.54:.1f} cm = 页高 {span/H*100:.1f}%")
print("=> " + ("OK 在 1/3 页(33.3%)内" if span / H <= 1 / 3
               else f"仍超 {(span/H-1/3)*100:.1f} 个百分点，需再省 {(span/H-1/3)*H/72*2.54:.1f} cm"))
