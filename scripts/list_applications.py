import json
import sqlite3
from pathlib import Path

db = Path("job_bot.db")
print("=== DB applications ===")
if db.exists():
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT status, title, company, url, applied_at, error FROM applications ORDER BY applied_at"
    ).fetchall()
    print("count", len(rows))
    for r in rows:
        err = (r["error"] or "")[:60]
        title = (r["title"] or "")[:70]
        company = (r["company"] or "")[:40]
        print(f"{r['status']:10} | {title} | {company} | {err}")
else:
    print("no db")

print()
print("=== Results files: applied lists ===")
files = sorted(Path("results").glob("jobs_*.json")) if Path("results").exists() else []
for f in files:
    data = json.loads(f.read_text(encoding="utf-8"))
    applied = data.get("applied") or []
    print(f.name, "total_applied=", data.get("total_applied"), "list=", len(applied))
    for j in applied:
        print("  APPLIED:", j.get("title"), "@", j.get("company"))
