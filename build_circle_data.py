"""
build_circle_data.py
Generates circle_data.json from dashboard_data.json.

Circle is a per-recruiter KPI ring view embedded in overview.tribe.xyz.
Scope (per Martin, 2026-05-06):
- Stages: Outreach Contacted, Actual Screens, Moved to ATS
- Periods: This week, Last week
- No filters beyond email + period

Input:  dashboard_data.json (from the recruiting dashboard pipeline)
Output: circle_data.json  (consumed by circle.html via ?member=<email> param)
"""

import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

# ---- Pilot recruiters (from Blake's selection, 2026-05-11) ----
# Maps recruiting-dashboard (client, ta_name) to overview.tribe.xyz email.
PILOTS = [
    {"email": "lejla@tribe.xyz",           "client": "Aviv",         "ta": "Lejla Silva"},
    {"email": "maria.gerbore@tribe.xyz",   "client": "Nexi",         "ta": "Maria Desiree Gerbore"},
    {"email": "jandokulil@tribe.xyz",      "client": "Wolt Market",  "ta": "Jan Dokulil"},
    {"email": "chene@tribe.xyz",           "client": "Glovo",        "ta": "Chené Elliot"},
    {"email": "samanthanel@tribe.xyz",     "client": "Glovo",        "ta": "Samantha Nel"},
]

# Stage display label -> (wbr_actuals key, targets key)
STAGES = [
    ("Outreach Contacted", "contacted",       "contacted"),
    ("Actual Screens",     "actual_screens",  "actual_screens"),
    ("Moved to ATS",       "ats",             "moved_to_ats"),
]


def iso_week_bounds(d: date) -> tuple[date, date, int]:
    """Return Monday-Sunday bounds for the ISO week containing d, plus the week number.
    Tribe uses Mon-Sun weeks aligned with ISO weeks — 2026W20 = Mon May 11 - Sun May 17.
    Confirmed by Blake 2026-05-18."""
    monday = d - timedelta(days=d.weekday())   # Mon=0..Sun=6
    sunday = monday + timedelta(days=6)
    iso_week = monday.isocalendar()[1]
    return monday, sunday, iso_week


def fmt_range(start: date, end: date) -> str:
    if start.month == end.month:
        return f"{start.strftime('%b %-d')}-{end.day}"
    return f"{start.strftime('%b %-d')}-{end.strftime('%b %-d')}"


def build_periods(today: date | None = None) -> dict:
    """Build 'this_week' and 'last_week' period metadata."""
    today = today or date.today()
    this_start, this_end, this_iso = iso_week_bounds(today)
    last_start = this_start - timedelta(days=7)
    last_end   = this_end   - timedelta(days=7)
    last_iso   = last_start.isocalendar()[1]

    # elapsed_pct for current week: portion of Mon-Sun that has passed by end of "today"
    elapsed_days = (today - this_start).days + 1   # +1 so Monday=1/7, Sunday=7/7
    elapsed_days = max(1, min(7, elapsed_days))
    this_elapsed = elapsed_days / 7.0

    return {
        "this_week": {
            "label": "This week",
            "iso_label": f"W{this_iso}, {fmt_range(this_start, this_end)}",
            "start": this_start.isoformat(),
            "end":   this_end.isoformat(),
            "iso_week":  this_iso,
            "elapsed_pct": round(this_elapsed, 3),
        },
        "last_week": {
            "label": "Last week",
            "iso_label": f"W{last_iso}, {fmt_range(last_start, last_end)}",
            "start": last_start.isoformat(),
            "end":   last_end.isoformat(),
            "iso_week":  last_iso,
            "elapsed_pct": 1.0,
        },
    }


def find_actuals_for_iso_week(dash: dict, client: str, ta: str, iso_week: int) -> dict | None:
    """Look up wbr_actuals['{client}|{ta}'] for week 'w{iso_week}'."""
    key = f"{client}|{ta}"
    weeks = dash.get("wbr_actuals", {}).get(key)
    if not weeks:
        return None
    wk_key = f"w{iso_week}"
    return weeks.get(wk_key)


def fallback_latest_two_weeks(dash: dict) -> tuple[str, str]:
    """When live weeks have no data yet (lag), use the two most-recent weeks in the dataset.
    Returns (this_week_key, last_week_key)."""
    all_weeks = set()
    for v in dash.get("wbr_actuals", {}).values():
        all_weeks.update(v.keys())
    all_weeks = sorted(all_weeks, key=lambda x: int(x[1:]))
    if len(all_weeks) < 2:
        return all_weeks[-1] if all_weeks else "w0", all_weeks[-1] if all_weeks else "w0"
    return all_weeks[-1], all_weeks[-2]   # this=most recent, last=prev


def build_member_data(dash: dict, pilot: dict, periods: dict, target_lookup: dict, use_fallback: bool) -> dict:
    """Build per-period stage data for a single pilot."""
    out = {}
    tgt = target_lookup.get((pilot["client"], pilot["ta"]), {})

    if use_fallback:
        this_wk_key, last_wk_key = fallback_latest_two_weeks(dash)
        this_iso = int(this_wk_key[1:])
        last_iso = int(last_wk_key[1:])
    else:
        this_iso = periods["this_week"]["iso_week"]
        last_iso = periods["last_week"]["iso_week"]

    for period_key, iso in (("this_week", this_iso), ("last_week", last_iso)):
        actuals = find_actuals_for_iso_week(dash, pilot["client"], pilot["ta"], iso) or {}
        out[period_key] = {}
        for display, actual_field, target_field in STAGES:
            out[period_key][display] = {
                "actual": int(actuals.get(actual_field, 0)),
                "target": float(tgt.get(target_field, 0)),
            }
    return out


def first_name(full: str) -> str:
    return full.split()[0] if full else ""


def main():
    repo_root = Path(__file__).resolve().parent
    # Look in known locations. Prefer dashboard_data_snowflake.json (live, freshest)
    # over dashboard_data.json (older snapshot lagging by ~4 weeks).
    candidates = [
        Path("/tmp/sf.json"),
        repo_root / "dashboard_data_snowflake.json",
        repo_root / "dashboard_data.json",
        repo_root.parent / "dashboard_data_snowflake.json",
        repo_root.parent / "dashboard_data.json",
        Path("/sessions/adoring-relaxed-brown/mnt/Recruiting Dashboard/dashboard_data_snowflake.json"),
        Path("/sessions/adoring-relaxed-brown/mnt/Recruiting Dashboard/dashboard_data.json"),
    ]
    src = next((p for p in candidates if p.exists()), None)
    if not src:
        print("ERROR: dashboard_data.json not found", file=sys.stderr)
        sys.exit(1)
    print(f"Loading {src}")

    with src.open() as f:
        dash = json.load(f)

    today = date.today()
    periods = build_periods(today)

    # Build target lookup
    target_lookup = {(t["client"], t["ta"]): t for t in dash.get("targets", [])}

    # Decide whether to use fallback (if today's iso_week isn't in the dataset)
    sample_weeks = set()
    for v in dash.get("wbr_actuals", {}).values():
        sample_weeks.update(v.keys())
    # Only fall back to the latest-available-two-weeks when BOTH the current
    # ISO week AND the previous ISO week are missing from the data (truly stale).
    # Normal Monday-morning case (W21 not yet populated, W20 complete) should
    # still label periods correctly — this_week=W21 (with 0s), last_week=W20.
    this_key = f"w{periods['this_week']['iso_week']}"
    last_key = f"w{periods['last_week']['iso_week']}"
    use_fallback = (this_key not in sample_weeks) and (last_key not in sample_weeks)
    if use_fallback:
        last_two = fallback_latest_two_weeks(dash)
        # Override the period labels to reflect the actual weeks we're showing.
        # Tribe labels Sun-Sat weeks by the iso-week of the inside Monday, so to
        # recover the Sun-Sat range from an iso-week, take Monday of that iso-week
        # and step back one day to Sunday.
        for period_key, wk_key in (("this_week", last_two[0]), ("last_week", last_two[1])):
            iso = int(wk_key[1:])
            start = date.fromisocalendar(today.year, iso, 1)   # Monday of ISO week
            end = start + timedelta(days=6)                    # Sunday
            periods[period_key].update({
                "iso_label": f"W{iso}, {fmt_range(start, end)} (latest available)",
                "iso_week":  iso,
                "start":     start.isoformat(),
                "end":       end.isoformat(),
                "elapsed_pct": 1.0,
            })
        print(f"Using fallback weeks (live data lag): this_week={last_two[0]}, last_week={last_two[1]}")

    members = {}
    for pilot in PILOTS:
        data = build_member_data(dash, pilot, periods, target_lookup, use_fallback)
        members[pilot["email"]] = {
            "name":       pilot["ta"],
            "first_name": first_name(pilot["ta"]),
            "role":       "TAP",
            "client":     pilot["client"],
            "data":       data,
        }

    out = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "source":       str(src),
        "periods":      periods,
        "members":      members,
    }

    dst = repo_root / "circle_data.json"
    with dst.open("w") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)

    print(f"Wrote {dst}  ({len(members)} members)")
    print(f"Periods: this={periods['this_week']['iso_label']}  /  last={periods['last_week']['iso_label']}")


if __name__ == "__main__":
    main()
