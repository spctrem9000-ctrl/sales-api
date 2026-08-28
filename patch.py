import re
with open('routers/dashboard.py', 'r', encoding='utf-8') as f:
    content = f.read()

pattern = r'return DashboardResponse\([\s\S]*?grand_trend_perc=None\n    \)'
replacement = '''resp = DashboardResponse(
        grand_gross_total=grand_gross,
        grand_disc=grand_disc,
        grand_disc_lines=grand_disc_l,
        grand_net_total=grand_net,
        grand_visa_total=grand_visa,
        grand_takeaway_count=grand_takeaway_count,
        grand_takeaway_total=grand_takeaway_total,
        grand_delivery_count=grand_delivery_count,
        grand_delivery_total=grand_delivery_total,
        grand_dlv_service_total=grand_dlv_service_total,
        total_orders=total_orders,
        branches=branches,
        business_date="¬Œ— Ê—œÌ… („»«‘—)",
        updated_at=datetime.now(timezone.utc).replace(tzinfo=None),
        grand_metrics=grand_metrics,
        grand_trend_perc=None
    )
    try:
        with open("dashboard_debug_response.txt", "w", encoding="utf-8") as f:
            f.write(resp.model_dump_json())
    except Exception:
        pass
    return resp'''

content = re.sub(pattern, replacement, content, count=1)

with open('routers/dashboard.py', 'w', encoding='utf-8') as f:
    f.write(content)
