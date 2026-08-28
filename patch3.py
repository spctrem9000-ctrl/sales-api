import re
with open('routers/cleanup.py', 'r', encoding='utf-8') as f:
    content = f.read()

pattern = r'def debug8\(\):[\s\S]*?return \{"log": "No file"\}'
replacement = '''def debug8():
    import os
    res = {}
    if os.path.exists("debug_daily.txt"):
        with open("debug_daily.txt", "r", encoding="utf-8") as f:
            res["daily"] = f.read()
    if os.path.exists("debug_monthly.txt"):
        with open("debug_monthly.txt", "r", encoding="utf-8") as f:
            res["monthly"] = f.read()
    return res'''

content = re.sub(pattern, replacement, content, count=1)

with open('routers/cleanup.py', 'w', encoding='utf-8') as f:
    f.write(content)
