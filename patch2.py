import re
with open('routers/dashboard.py', 'r', encoding='utf-8') as f:
    content = f.read()

pattern1 = r'grand_metrics=None,\n        grand_trend_perc=None\n    \)'
replacement1 = '''grand_metrics=None,
        grand_trend_perc=None
    )
    import traceback
    try:
        with open("debug_daily.txt", "w", encoding="utf-8") as f:
            f.write(f"USER: {current_user.username} | DATE: {date} | ROWS: {len(rows)} | BRANCHES RET: {len(branches)}\n")
    except Exception as e:
        pass'''

content = re.sub(pattern1, replacement1, content, count=1)

pattern2 = r'grand_metrics=grand_metrics,\n        grand_trend_perc=None\n    \)'
replacement2 = '''grand_metrics=grand_metrics,
        grand_trend_perc=None
    )
    import traceback
    try:
        with open("debug_monthly.txt", "w", encoding="utf-8") as f:
            f.write(f"USER: {current_user.username} | DATES: {len(req.dates)} | ROWS: {len(rows)} | BRANCHES RET: {len(branches)}\n")
    except Exception as e:
        pass'''

content = re.sub(pattern2, replacement2, content, count=1)

with open('routers/dashboard.py', 'w', encoding='utf-8') as f:
    f.write(content)
