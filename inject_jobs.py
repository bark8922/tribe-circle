"""
inject_jobs.py
Merges per-(recruiter, job_id, week) breakdown into circle_data.json.

Source of truth: `project_dashboard.rows` inside the same Keboola-published
dashboard_data_snowflake.json that build_circle_data.py already reads.

Verified (2026-05-18) that summing project_dashboard.rows by (client, ta, week)
matches wbr_actuals totals exactly for all 5 pilots across W19 + W20.

Runs AFTER build_circle_data.py. For each pilot/period in circle_data.json,
filters project_dashboard.rows to the recruiter and week, aggregates by job,
drops jobs with all zeros, sorts by contacted descending, and stores under
`data[period]._jobs`.
"""

import json
import sys
from pathlib import Path

# email → (canonical display client, project_dashboard.client variants, project_dashboard.ta)
PILOTS = {
    'adelya@tribe.xyz': {"ta": 'Adelya Khakimova', "client_display": 'Wolt North, Baltics & Benelux', "pd_clients": ['Wolt']},
    'adis@tribe.xyz': {"ta": 'Adis Prepoljac', "client_display": 'Nexi', "pd_clients": ['Nexi']},
    'asingh@tribe.xyz': {"ta": 'Akash Singh', "client_display": 'DoorDash', "pd_clients": ['Doordash']},
    'aleksandra@tribe.xyz': {"ta": 'Aleksandra Vistac', "client_display": 'Enam', "pd_clients": ['Enam']},
    'alexandra.richiteanu@tribe.xyz': {"ta": 'Alexandra Richiteanu', "client_display": 'Aviv', "pd_clients": ['AVIV']},
    'alisa@tribe.xyz': {"ta": 'Alisa Liddell', "client_display": 'Eucalyptus', "pd_clients": ['Eucalyptus']},
    'andrea@tribe.xyz': {"ta": 'Andrea Akovic', "client_display": 'Fever', "pd_clients": ['Fever']},
    'annatyulpanova@tribe.xyz': {"ta": 'Anna Tyulpanova', "client_display": 'Aviv', "pd_clients": ['AVIV']},
    'chene@tribe.xyz': {"ta": 'Chené Elliot', "client_display": 'Glovo', "pd_clients": ['Glovo']},
    'danish@tribe.xyz': {"ta": 'Danish Shams', "client_display": 'DoorDash', "pd_clients": ['Doordash']},
    'dushan@tribe.xyz': {"ta": 'Dušan Špica', "client_display": 'Eucalyptus', "pd_clients": ['Eucalyptus']},
    'eduardo@tribe.xyz': {"ta": 'Eduardo Moral', "client_display": 'Grover', "pd_clients": ['Grover']},
    'ejla@tribe.xyz': {"ta": 'Ejla Suljcic', "client_display": 'Wolt Tech', "pd_clients": ['Wolt']},
    'ekaterina@tribe.xyz': {"ta": 'Ekaterina Boyprav', "client_display": 'Scorewarrior', "pd_clients": ['Scorewarrior']},
    'elenapetrovska@tribe.xyz': {"ta": 'Elena Petrovska', "client_display": 'Wolt HQ', "pd_clients": ['Wolt']},
    'filip@tribe.xyz': {"ta": 'Filip Nogowski', "client_display": 'Parloa', "pd_clients": ['Parloa']},
    'fuad@tribe.xyz': {"ta": 'Fuad Safarov', "client_display": 'Aiven', "pd_clients": ['Aiven']},
    'jandokulil@tribe.xyz': {"ta": 'Jan Dokulil', "client_display": 'Wolt Market', "pd_clients": ['Wolt']},
    'jelenalacmanovic@tribe.xyz': {"ta": 'Jelena Lacmanovic', "client_display": 'Wolt North, Baltics & Benelux', "pd_clients": ['Wolt']},
    'jonaed@tribe.xyz': {"ta": 'Jonaed Iqbal', "client_display": 'Parloa', "pd_clients": ['Parloa']},
    'jovana@tribe.xyz': {"ta": 'Jovana Drakula', "client_display": 'Aviv', "pd_clients": ['AVIV']},
    'kristinaxnikolic@gmail.com': {"ta": 'Kristina Colovic', "client_display": 'Aviv', "pd_clients": ['AVIV']},
    'lejla@tribe.xyz': {"ta": 'Lejla Silva', "client_display": 'Aviv', "pd_clients": ['AVIV']},
    'lisa@tribe.xyz': {"ta": 'Lisa Gargulinska', "client_display": 'Wolt Germany', "pd_clients": ['Wolt']},
    'maria.gerbore@tribe.xyz': {"ta": 'Maria Desiree Gerbore', "client_display": 'Nexi', "pd_clients": ['Nexi']},
    'marinanikolic@tribe.xyz': {"ta": 'Marina Nikolic', "client_display": 'Taxfix', "pd_clients": ['Taxfix']},
    'mateja@tribe.xyz': {"ta": 'Mateja Jokovic', "client_display": 'PhantomBuster', "pd_clients": ['PhantomBuster']},
    'meho@tribe.xyz': {"ta": 'Meho Saracevic', "client_display": 'Eucalyptus', "pd_clients": ['Eucalyptus']},
    'milicaveselinovic@tribe.xyz': {"ta": 'Milica Veselinovic', "client_display": 'Wolt HQ', "pd_clients": ['Wolt']},
    'nenad@tribe.xyz': {"ta": 'Nenad Skoko', "client_display": 'Wolt HQ', "pd_clients": ['Wolt']},
    'nidhi@tribe.xyz': {"ta": 'Nidhi Raina', "client_display": 'DoorDash', "pd_clients": ['Doordash']},
    'niki@tribe.xyz': {"ta": 'Niki Vokalkova', "client_display": 'Wolt Central & South', "pd_clients": ['Wolt']},
    'rodrigo@tribe.xyz': {"ta": 'Rodrigo Gomez', "client_display": 'Grover', "pd_clients": ['Grover']},
    'samanthanel@tribe.xyz': {"ta": 'Samantha Nel', "client_display": 'Glovo', "pd_clients": ['Glovo']},
    'tinaaramouni@tribe.xyz': {"ta": 'Tina Aramouni', "client_display": 'Wolt North, Baltics & Benelux', "pd_clients": ['Wolt']},
    'vladimir@tribe.xyz': {"ta": 'Vladimir Stankovic', "client_display": 'Aiven', "pd_clients": ['Aiven']},
    'wladyslaw@tribe.xyz': {"ta": 'Wladyslaw Gadomski', "client_display": 'Aviv', "pd_clients": ['AVIV']},
    'zelimir@tribe.xyz': {"ta": 'Zelimir Stajcic', "client_display": 'SevenRooms', "pd_clients": ['SevenRooms']},
}

METRIC_FIELDS = ("contacted", "actual_screens", "ats", "offered", "hired")


def find_source_json() -> Path:
    """Locate the freshest dashboard_data_snowflake.json the GH Action / local run can see."""
    here = Path(__file__).resolve().parent
    for p in [
        Path("/tmp/sf.json"),
        here / "dashboard_data_snowflake.json",
        here.parent / "dashboard_data_snowflake.json",
    ]:
        if p.exists():
            return p
    print("ERROR: dashboard_data_snowflake.json not found", file=sys.stderr)
    sys.exit(1)


def aggregate_jobs(rows: list, ta: str, pd_clients: list[str], iso_week: int, iso_year: int = 2026) -> list[dict]:
    """Aggregate project_dashboard.rows by job_id for the given (ta, client, week)."""
    pd_clients_norm = {c.strip().lower() for c in pd_clients}
    bucket: dict[str, dict] = {}
    for r in rows:
        if r.get("iso_year") != iso_year or r.get("iso_week") != iso_week:
            continue
        if r.get("ta") != ta:
            continue
        if (r.get("client") or "").strip().lower() not in pd_clients_norm:
            continue
        job_id = r.get("job_id")
        if not job_id:
            continue
        b = bucket.setdefault(job_id, {
            "job_id":    job_id,
            "job_title": (r.get("job_title") or "").strip(),
            "contacted": 0, "actual_screens": 0, "ats": 0, "offered": 0, "hired": 0,
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
        print("ERROR: project_dashboard.rows missing or empty in source JSON", file=sys.stderr)
        sys.exit(1)
    print(f"project_dashboard.rows: {len(rows)} total")

    injected = 0
    for email, member in circle.get("members", {}).items():
        cfg = PILOTS.get(email)
        if not cfg:
            continue
        for period_key in ("this_week", "last_week"):
            iso_week = circle["periods"][period_key]["iso_week"]
            jobs = aggregate_jobs(rows, cfg["ta"], cfg["pd_clients"], iso_week)
            member.setdefault("data", {}).setdefault(period_key, {})["_jobs"] = jobs
            if jobs:
                injected += 1

    with circle_path.open("w") as f:
        json.dump(circle, f, indent=2, ensure_ascii=False)
    print(f"Injected job breakdown into {injected} (member, period) slots")


if __name__ == "__main__":
    main()
