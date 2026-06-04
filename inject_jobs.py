"""
inject_jobs.py
Adds per-(member, period, job) breakdown into circle_data.json.

Source: project_dashboard.rows in dashboard_data_snowflake.json.
- TA members: filter by ta == name AND client == pd_client (matches WBR roster).
- TS members: filter by ts == name (no client filter — TS work spans clients).

Runs AFTER build_circle_data.py. Reads circle_data.json, augments with _jobs
arrays, writes back. Same source as build_circle_data.py uses for ring totals,
so ring totals and job sums reconcile exactly.
"""

import json
import sys
from pathlib import Path


METRIC_FIELDS = ("contacted", "screens", "actual_screens", "ats", "offered", "hired")


def find_source_json():
    for p in [Path("/tmp/sf.json"),
              Path(__file__).resolve().parent / "dashboard_data_snowflake.json"]:
        if p.exists():
            return p
    print("ERROR: dashboard_data_snowflake.json not found", file=sys.stderr)
    sys.exit(1)


def aggregate_jobs(rows, name, role, iso_week, pd_client=None, iso_year=2026):
    bucket = {}
    pdc_norm = (pd_client or "").strip().lower()
    for r in rows:
        if r.get("iso_year") != iso_year or r.get("iso_week") != iso_week:
            continue
        if role == "TA":
            if r.get("ta") != name:
                continue
            if pdc_norm and (r.get("client") or "").strip().lower() != pdc_norm:
                continue
        else:
            if r.get("ts") != name:
                continue
        job_id = r.get("job_id")
        if not job_id:
            continue
        b = bucket.setdefault(job_id, {
            "job_id": job_id,
            "job_title": (r.get("job_title") or "").strip(),
            "contacted": 0, "screens": 0, "actual_screens": 0, "ats": 0, "offered": 0, "hired": 0,
        })
        for f in METRIC_FIELDS:
            b[f] += int(r.get(f, 0) or 0)
    jobs = [j for j in bucket.values() if any(j[f] for f in METRIC_FIELDS)]
    jobs.sort(key=lambda j: (-j["contacted"], -j["actual_screens"], -j["ats"]))
    return jobs


def main():
    here = Path(__file__).resolve().parent
    circle_path = here / "circle_data.json"
    src_path = find_source_json()
    print(f"Reading source: {src_path}")
    print(f"Reading circle: {circle_path}")

    with src_path.open() as f:
        src = json.load(f)
    with circle_path.open() as f:
        circle = json.load(f)

    rows = src.get("project_dashboard", {}).get("rows", [])
    if not rows:
        print("ERROR: project_dashboard.rows missing or empty", file=sys.stderr)
        sys.exit(1)
    print(f"project_dashboard.rows: {len(rows)} total")

    injected = 0
    for email, member in circle.get("members", {}).items():
        role = member.get("role", "TA")
        name = member.get("name", "")
        pd_client = member.get("pd_client") or None
        for pk in ("this_week", "last_week"):
            iso = circle["periods"][pk]["iso_week"]
            jobs = aggregate_jobs(rows, name, role, iso, pd_client=pd_client)
            member.setdefault("data", {}).setdefault(pk, {})["_jobs"] = jobs
            if jobs:
                injected += 1

    with circle_path.open("w") as f:
        json.dump(circle, f, indent=2, ensure_ascii=False)
    print(f"Injected job breakdown into {injected} (member, period) slots")


if __name__ == "__main__":
    main()
