"""
build_circle_data.py
Generates circle_data.json from dashboard_data_snowflake.json.

Covers both TAs (Talent Acquisition Partners) and TSes (Talent Sourcers).
Pilots derived dynamically from the source JSON + Mikhail's Circle KPI sheet
(name->email map at /tmp/circle_kpi.csv).

TA: targets from `targets` array, actuals from `wbr_actuals[client|ta][wNN]`,
    per-job breakdown via project_dashboard.rows filtered by ta+pd_client.
TS: roster from latest populated week of `ts_weekly`; actuals also sourced
    from `project_dashboard.rows` (filter by ts==name) so ring totals
    reconcile exactly with the per-job breakdown. Targets per Blake
    2026-04-29: contacted = ts_weekly.contacted_target (default 100),
    actual_screens = 7, ats = 4.

For dual-role people (in both TA targets AND TS roster), TS view wins.

Tribe weeks: Mon-Sun, ISO-aligned. 2026W20 = Mon May 11 - Sun May 17.
"""

import base64
import csv
import io
import json
import os
import urllib.request
import sys
from datetime import date, datetime, timedelta
from pathlib import Path


TS_REC_SCREENS_TARGET = 10
TS_ACTUAL_SCREENS_TARGET = 7
TS_ATS_TARGET = 4
TS_RECRUITER_SCREEN_TARGET = 10  # weekly target per Andrea 2026-06-04
TS_CONTACTED_TARGET_DEFAULT = 100


def iso_week_bounds(d):
    monday = d - timedelta(days=d.weekday())
    sunday = monday + timedelta(days=6)
    return monday, sunday, monday.isocalendar()[1]


def fmt_range(start, end):
    if start.month == end.month:
        return f"{start.strftime('%b %-d')}-{end.day}"
    return f"{start.strftime('%b %-d')}-{end.strftime('%b %-d')}"


def build_periods(today=None):
    today = today or date.today()
    this_start, this_end, this_iso = iso_week_bounds(today)
    last_start = this_start - timedelta(days=7)
    last_end = this_end - timedelta(days=7)
    last_iso = last_start.isocalendar()[1]
    elapsed_days = max(1, min(7, (today - this_start).days + 1))
    return {
        "this_week": {
            "label": "This week",
            "iso_label": f"W{this_iso}, {fmt_range(this_start, this_end)}",
            "start": this_start.isoformat(),
            "end": this_end.isoformat(),
            "iso_week": this_iso,
            "elapsed_pct": round(elapsed_days / 7.0, 3),
        },
        "last_week": {
            "label": "Last week",
            "iso_label": f"W{last_iso}, {fmt_range(last_start, last_end)}",
            "start": last_start.isoformat(),
            "end": last_end.isoformat(),
            "iso_week": last_iso,
            "elapsed_pct": 1.0,
        },
    }


KPI_SHEET_URL = (
    "https://docs.google.com/spreadsheets/d/"
    "1nGxKctROF9Li3KLz1OD7b7koUs64ke3W_-dwwVjHv8Y/export?format=csv&gid=0"
)


def load_email_map_from_bamboo():
    """name -> workEmail from BambooHR directory. Returns None if env vars
    are missing or the call fails (caller falls back to the KPI sheet)."""
    api_key = os.environ.get("BAMBOOHR_API_KEY")
    subdomain = os.environ.get("BAMBOOHR_SUBDOMAIN", "tribe")
    if not api_key:
        return None
    import base64 as _b64
    url = f"https://api.bamboohr.com/api/gateway.php/{subdomain}/v1/employees/directory"
    auth = _b64.b64encode(f"{api_key}:x".encode()).decode()
    req = urllib.request.Request(url, headers={
        "Authorization": "Basic " + auth,
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read())
    except Exception as exc:
        print(f"[email-map] Bamboo fetch failed: {exc}; falling back", flush=True)
        return None
    emails = {}
    for emp in data.get("employees", []):
        first = (emp.get("firstName") or "").strip()
        last = (emp.get("lastName") or "").strip()
        email = (emp.get("workEmail") or "").strip()
        if not email or not (first or last):
            continue
        full = f"{first} {last}".strip()
        emails[full] = email
    # Common name variants observed in the WBR Target sheet
    if "Rodrigo Gomes" in emails:
        emails.setdefault("Rodrigo Gomez", emails["Rodrigo Gomes"])
    print(f"[email-map] BambooHR: {len(emails)} active employees", flush=True)
    return emails


def load_email_map_from_kpi_sheet():
    """Legacy fallback — Mikhail's Circle KPI sheet."""
    emails = {}
    p = Path("/tmp/circle_kpi.csv")
    if p.exists():
        text = p.read_text()
    else:
        print(f"[email-map] fetching from KPI sheet {KPI_SHEET_URL}", flush=True)
        with urllib.request.urlopen(KPI_SHEET_URL, timeout=15) as resp:
            text = resp.read().decode("utf-8")
    for row in csv.DictReader(io.StringIO(text)):
        n = row["Full name"].strip()
        e = row["Email"].strip()
        if n and e:
            emails[n] = e
    if "Rodrigo Gomes" in emails:
        emails.setdefault("Rodrigo Gomez", emails["Rodrigo Gomes"])
    print(f"[email-map] KPI sheet: {len(emails)} entries", flush=True)
    return emails


def _fold_name(s):
    """Casefold + strip diacritics, for matching names across data sources.
    Bamboo often stores 'Želimir Stajčić'; the WBR sheet has 'Zelimir Stajcic'.
    Without folding, the lookup misses them."""
    import unicodedata
    if not s:
        return ""
    nfd = unicodedata.normalize("NFD", s)
    no_diacritics = "".join(c for c in nfd if unicodedata.category(c) != "Mn")
    return no_diacritics.casefold().strip()


class _EmailMap:
    """Dict-like with diacritic-folded fallback lookup."""
    def __init__(self, raw):
        self._raw = dict(raw)
        self._folded = {_fold_name(k): v for k, v in raw.items()}
    def get(self, key, default=None):
        if key in self._raw:
            return self._raw[key]
        return self._folded.get(_fold_name(key), default)
    def __getitem__(self, key):
        v = self.get(key)
        if v is None: raise KeyError(key)
        return v
    def __contains__(self, key):
        return self.get(key) is not None
    def __len__(self):
        return len(self._raw)
    def setdefault(self, key, value):
        if key in self._raw:
            return self._raw[key]
        self._raw[key] = value
        self._folded[_fold_name(key)] = value
        return value


def load_email_map():
    """name -> email. Primary source: BambooHR (canonical, single source of
    truth for active employees). Falls back to Mikhail's KPI Google Sheet if
    BAMBOOHR_API_KEY isn't set or the API call fails — preserves local-dev
    workflows that don't have Bamboo credentials.
    Lookups are diacritic-folded so 'Zelimir Stajcic' (WBR) matches
    'Želimir Stajčić' (Bamboo)."""
    emails = load_email_map_from_bamboo()
    if not emails:
        emails = load_email_map_from_kpi_sheet()
    return _EmailMap(emails)


def wbr_to_pd_client(client):
    if client.startswith("Wolt"):
        return "Wolt"
    return {"Aviv": "AVIV", "DoorDash": "Doordash"}.get(client, client)


def build_pilots(dash, emails):
    by_wk = {}
    for t in dash.get("ts_weekly", []):
        by_wk.setdefault(t["week"], []).append(t)
    latest_ts_wk = max(by_wk.keys()) if by_wk else None
    ts_pilots = []
    ts_emails = set()
    if latest_ts_wk is not None:
        for t in sorted(by_wk[latest_ts_wk], key=lambda x: x["ts"]):
            email = emails.get(t["ts"])
            if not email:
                continue
            ts_pilots.append({"role": "TS", "email": email, "name": t["ts"]})
            ts_emails.add(email)
    seen = set()
    ta_pilots = []
    for t in dash.get("targets", []):
        ta = (t.get("ta") or "").strip()
        cl = (t.get("client") or "").strip()
        # team_group dropped from the include filter 2026-06-04: it was excluding
        # active TAs whose WBR target rows lack a team assignment (Iryna Dyda,
        # Joanna Bober, etc.). Email presence in the KPI sheet is enough to
        # qualify someone for Circle.
        if not ta or not cl or (ta, cl) in seen:
            continue
        seen.add((ta, cl))
        email = emails.get(ta, "")
        if not email or email in ts_emails:
            continue
        ta_pilots.append({
            "role": "TA", "email": email, "name": ta,
            "client": cl, "pd_client": wbr_to_pd_client(cl),
        })
    return ta_pilots + ts_pilots, latest_ts_wk


def first_name(full):
    return full.split()[0] if full else ""


def ta_actuals(dash, client, ta, iso_week):
    wbr = dash.get("wbr_actuals", {}).get(f"{client}|{ta}", {})
    return wbr.get(f"w{iso_week}", {}) or {}


def ta_targets(dash, client, ta):
    for t in dash.get("targets", []):
        if (t.get("client") or "").strip() == client and (t.get("ta") or "").strip() == ta:
            return t
    return {}


def ts_actuals_from_pd(dash, ts_name, iso_week):
    sums = {"contacted": 0, "screens": 0, "actual_screens": 0, "ats": 0, "offered": 0, "hired": 0}
    for r in dash.get("project_dashboard", {}).get("rows", []):
        if r.get("iso_year") != 2026 or r.get("iso_week") != iso_week:
            continue
        if r.get("ts") != ts_name:
            continue
        for k in sums:
            sums[k] += int(r.get(k, 0) or 0)
    return sums


def ts_contacted_target(dash, ts_name, iso_week):
    cands = []
    for r in dash.get("ts_weekly", []):
        if r.get("ts") != ts_name:
            continue
        ct = r.get("contacted_target")
        if ct is None:
            continue
        if r.get("week", 0) <= iso_week:
            cands.append((r["week"], ct))
    if not cands:
        return TS_CONTACTED_TARGET_DEFAULT
    cands.sort()
    return float(cands[-1][1])


def drops_for_ts(dash, ts_name, iso_week, iso_year=2026):
    """Drop rows for one sourcer in one ISO week.
    Schema each row: {job_id, job_title, client, reason, drops}.
    """
    out = []
    for r in dash.get("drops_by_sourcer", []):
        if r.get("ts") != ts_name:
            continue
        if r.get("iso_year") != iso_year or r.get("iso_week") != iso_week:
            continue
        out.append({
            "job_id": r.get("job_id"),
            "job_title": (r.get("job_title") or "").strip(),
            "client": r.get("client"),
            "reason": r.get("reason"),
            "drops": int(r.get("drops") or 0),
        })
    return out


def build_member(dash, pilot, periods):
    out = {
        "name": pilot["name"],
        "first_name": first_name(pilot["name"]),
        "role": pilot["role"],
        "client": pilot.get("client", ""),
        "pd_client": pilot.get("pd_client", ""),
        "data": {},
    }
    for pk in ("this_week", "last_week"):
        iso = periods[pk]["iso_week"]
        if pilot["role"] == "TA":
            a = ta_actuals(dash, pilot["client"], pilot["name"], iso)
            t = ta_targets(dash, pilot["client"], pilot["name"])
            out["data"][pk] = {
                "Outreach Contacted": {"actual": int(a.get("contacted", 0) or 0),      "target": float(t.get("contacted", 0) or 0)},
                "Actual Screens":     {"actual": int(a.get("actual_screens", 0) or 0), "target": float(t.get("actual_screens", 0) or 0)},
                "Moved to ATS":       {"actual": int(a.get("ats", 0) or 0),            "target": float(t.get("moved_to_ats", 0) or 0)},
            }
        else:
            a = ts_actuals_from_pd(dash, pilot["name"], iso)
            out["data"][pk] = {
                "Outreach Contacted": {"actual": int(a.get("contacted", 0) or 0),      "target": ts_contacted_target(dash, pilot["name"], iso)},
                "Recruiter Screen":   {"actual": int(a.get("screens", 0) or 0),        "target": float(TS_RECRUITER_SCREEN_TARGET)},
                "Actual Screens":     {"actual": int(a.get("actual_screens", 0) or 0), "target": float(TS_ACTUAL_SCREENS_TARGET)},
                "Moved to ATS":       {"actual": int(a.get("ats", 0) or 0),            "target": float(TS_ATS_TARGET)},
                "_drops":             drops_for_ts(dash, pilot["name"], iso),
            }
    return out


def find_source_json():
    for p in [Path("/tmp/sf.json"),
              Path(__file__).resolve().parent / "dashboard_data_snowflake.json"]:
        if p.exists():
            return p
    print("ERROR: dashboard_data_snowflake.json not found", file=sys.stderr)
    sys.exit(1)


def main():
    src = find_source_json()
    print(f"Loading {src}")
    with src.open() as f:
        dash = json.load(f)
    today = date.today()
    periods = build_periods(today)
    emails = load_email_map()
    if not emails:
        print("WARNING: /tmp/circle_kpi.csv missing - email lookup will be empty")
    pilots, ts_wk = build_pilots(dash, emails)
    print(f"Built {sum(1 for p in pilots if p['role']=='TA')} TA + {sum(1 for p in pilots if p['role']=='TS')} TS pilots (TS roster from w{ts_wk})")
    members = {p["email"]: build_member(dash, p, periods) for p in pilots}

    # 2026-06-04: drop members with zero activity across both visible periods.
    # Circle only renders this_week + last_week, so members with no data in either
    # are dead rows (e.g. ex-employees whose WBR Target sheet entry was never cleaned
    # up). A member counts as active if any tile in any visible period has actual > 0.
    def has_any_activity(m):
        for pk in ("this_week", "last_week"):
            period = (m.get("data") or {}).get(pk) or {}
            for k, v in period.items():
                if k.startswith("_"):
                    continue
                if isinstance(v, dict) and (v.get("actual") or 0) > 0:
                    return True
        return False
    members = {email: m for email, m in members.items() if has_any_activity(m)}
    print(f"Active members after zero-activity filter: {len(members)}")

    out = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "source": str(src),
        "periods": periods,
        "members": members,
    }
    dst = Path(__file__).resolve().parent / "circle_data.json"
    with dst.open("w") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print(f"Wrote {dst}  ({len(members)} members)")
    print(f"Periods: this={periods['this_week']['iso_label']}  /  last={periods['last_week']['iso_label']}")


if __name__ == "__main__":
    main()
