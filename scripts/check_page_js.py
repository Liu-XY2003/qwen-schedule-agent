#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""校验 app.py 里内嵌的那段页面 JS 的语法。

页面 JS 藏在 Python 字符串里, 平时没人检查; 一个逗号写错就整页白屏,
而且只有在浏览器里打开才看得见。这个脚本把 <script> 段抽出来交给 `node --check`。
"""
import pathlib
import subprocess
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace") if hasattr(sys.stdout, "reconfigure") else None

APP = pathlib.Path(__file__).resolve().parent.parent / "bridge" / "app.py"
src = APP.read_text(encoding="utf-8")

start = src.index("<script>", src.index("</style></head>")) + len("<script>")
end = src.index("</script>", start)
js = src[start:end]

with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as f:
    f.write(js)
    path = f.name

print(f"页面 JS: {len(js)} 字符")
r = subprocess.run(["node", "--check", path], capture_output=True, text=True,
                   encoding="utf-8", errors="replace")
pathlib.Path(path).unlink(missing_ok=True)

if r.returncode == 0:
    print("语法 OK")
    sys.exit(0)
print("语法错误:")
print((r.stderr or "")[:2000])
sys.exit(1)
