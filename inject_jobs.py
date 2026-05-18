"""
inject_jobs.py
Merges per-(recruiter, job_id, week) breakdown from /tmp/circle_jobs.csv into circle_data.json.

Runs AFTER build_circle_data.py. Adds a `_jobs` array inside each member's
data[period] block, listing the jobs that contributed to that period's totals.
Jobs with all-zero values are filtered out (per Blake's request).
"""

import csv
import json
from pathlib import Path

PILOTS_BY_TA = {
    "Lejla Silva":           "lejla@tribe.xyz",
    "Maria Desiree Gerbore": "maria.gerbore@tribe.xyz",
    "Jan Dokulil":           "jandokulil@tribe.xyz",
    "Chené Elliot":          "chene@tribe.xyz",
    "Samantha Nel":          "samanthanel@tribe.xyz",
}


def load_jobs_csv(path: Path) -> dict:
    """Returns {(email, iso_week): [job_row, ...]}"""
    result = {}
    with path.open(newline="") as f:
        for row in csv.DictReader(f):
            email = PILOTS_BY_TA.get(row["TA"].strip())
            if not email:
                continue
            iso_week = int(row["ISO_WEEK"])
            key = (email, iso_week)
            contacted = int(row["CONTACTED"])
            screens   = int(row["ACTUAL_SCREENS"])
            ats       = int(row["ATS"])
            offered   = int(row.get("OFFERED", 0) or 0)
            hired     = int(row.get("HIRED", 0)   or 0)
            if contacted == 0 and screens == 0 and ats == 0 and offered == 0 and hired == 0:
                continue
            result.setdefault(key, []).append({
                "job_id":         row["JOB_ID"],
                "job_title":      row["JOB_TITLE"].strip(),
                "contacted":      contacted,
                "actual_screens": screens,
                "ats":            ats,
                "offered":        offered,
                "hired":          hired,
            })
    for jobs in result.values():
        jobs.sort(key=lambda j: -j["contacted"])
    return result


def main():
    here = Path(__file__).resolve().parent
    circle_path = here / "circle_data.json"
    jobs_path = Path("/tmp/circle_jobs.csv")
    if not jobs_path.exists():
        print(f"No /tmp/circle_jobs.csv found, skipping job injection.")
        return

    print(f"Loading {circle_path}")
    with circle_path.open() as f:
        d = json.load(f)

    jobs = load_jobs_csv(jobs_path)
    print(f"Loaded {sum(len(v) for v in jobs.values())} job rows for {len(jobs)} (email, week) pairs")

    injected = 0
    for email, member in d.get("members", {}).items():
        for period_key in ("this_week", "last_week"):
            iso_week = d["periods"][period_key]["iso_week"]
            rows = jobs.get((email, iso_week), [])
            member.setdefault("data", {}).setdefault(period_key, {})["_jobs"] = rows
            if rows:
                injected += 1

    with circle_path.open("w") as f:
        json.dump(d, f, indent=2, ensure_ascii=False)

    print(f"Injected job breakdown into {injected} (member, period) slots")


if __name__ == "__main__":
    main()
           