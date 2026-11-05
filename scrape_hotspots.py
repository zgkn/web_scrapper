"""Scrape ASMC VIIRS daily hotspot counts (https://asmc.asean.org/asmc-haze-hotspot-daily-new).

The page's "View" button POSTs to
  .../asmctheme/page-functions/functions-ajax-haze-daily-hotspot-count-new.php
with: date=<"5 Nov, 2026">&pastDays=<n>&regions[]=...&daynight=day|night&conf=High|Medium|Low
and receives JSON: [{"date":"2026-10-29","Kalimantan":152,...}, ...] covering
[date - pastDays, date - 1] (the `date` value is the exclusive end).

Only values present in the response are written. A region/day missing from the
response is simply absent from the output (never filled with 0).

Output (long format): data/hotspot_counts_daily.csv
  date, region, time_of_day, confidence, count
Usage: python scrape_hotspots.py [--start YYYY-MM-DD] [--end YYYY-MM-DD]
         [--daynight both|day|night] [--conf all|High|Medium|Low] [--window 90]
"""
import argparse
import csv
import json
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests

PAGE = "https://asmc.asean.org/asmc-haze-hotspot-daily-new"
ENDPOINT = ("https://asmc.asean.org/wp-content/themes/asmctheme/page-functions/"
            "functions-ajax-haze-daily-hotspot-count-new.php")
REGIONS = ["Thailand", "Myanmar", "Cambodia", "Vietnam", "Lao_PDR", "Philippines",
           "P_Malaysia", "SabahSarawak", "Sumatra", "Kalimantan", "Singapore", "Brunei"]
SGT = timezone(timedelta(hours=8))


def fmt_date(d):  # "5 Nov, 2026"
    return f"{d.day} {d.strftime('%b')}, {d.year}"


def fetch(sess, end_excl, window, regions, daynight, conf, tries=4):
    data = {"date": fmt_date(end_excl), "pastDays": str(window),
            "regions[]": regions, "daynight": daynight, "conf": conf}
    for attempt in range(1, tries + 1):
        try:
            r = sess.post(ENDPOINT, data=data, timeout=60,
                          headers={"Referer": PAGE, "X-Requested-With": "XMLHttpRequest"})
            if r.status_code == 200:
                return json.loads(r.text)
            print(f"[warn] HTTP {r.status_code} {data['date']} {regions} (try {attempt})",
                  file=sys.stderr)
        except (requests.RequestException, ValueError) as e:
            print(f"[warn] {e} {data['date']} {regions} (try {attempt})", file=sys.stderr)
        time.sleep(2 * attempt)
    return None


def main():
    today = datetime.now(SGT).date()
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default=(today - timedelta(days=90)).isoformat())
    ap.add_argument("--end", default=today.isoformat(),
                    help="exclusive end (the page's date field); last day scraped = end-1")
    ap.add_argument("--daynight", default="both", choices=["both", "day", "night"])
    ap.add_argument("--conf", default="all", choices=["all", "High", "Medium", "Low"])
    ap.add_argument("--window", type=int, default=90)
    ap.add_argument("--out", default="data")
    a = ap.parse_args()
    start, end = date.fromisoformat(a.start), date.fromisoformat(a.end)
    dns = ["day", "night"] if a.daynight == "both" else [a.daynight]
    confs = ["High", "Medium", "Low"] if a.conf == "all" else [a.conf]
    groups = [REGIONS[i:i + 5] for i in range(0, len(REGIONS), 5)]  # page allows max 5
    sess = requests.Session()
    sess.headers["User-Agent"] = "Mozilla/5.0 (compatible; hotspot-data-scraper)"

    rows, problems, seen = {}, [], {}
    raw_values = 0
    for dn in dns:
        for conf in confs:
            for grp in groups:
                cur = end
                while cur > start:
                    js = fetch(sess, cur, a.window, grp, dn, conf)
                    win_lo = cur - timedelta(days=a.window)
                    tag = f"{dn}/{conf}/{','.join(grp)} end={cur}"
                    if js is None or not isinstance(js, list):
                        problems.append(f"{tag}: fetch/parse failed")
                    else:
                        dates = [x.get("date") for x in js]
                        if len(js) != a.window:
                            problems.append(f"{tag}: got {len(js)} days, expected {a.window}")
                        for x in js:
                            d = x.get("date")
                            if not d or not (start <= date.fromisoformat(d) < end):
                                continue
                            for k, v in x.items():
                                if k == "date" or k.endswith("LineColor"):
                                    continue
                                key = (d, k, dn, conf)
                                raw_values += 1
                                if key in rows and rows[key] != v:
                                    problems.append(f"{key}: conflicting {rows[key]} vs {v}")
                                rows[key] = v
                    time.sleep(0.5)
                    cur = win_lo
                print(f"done {dn}/{conf}/{grp}", flush=True)

    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    path = out / "hotspot_counts_daily.csv"
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "region", "time_of_day", "confidence", "count"])
        for (d, r, dn, c) in sorted(rows):
            w.writerow([d, r, dn, c, rows[(d, r, dn, c)]])
    print(f"\nwrote {len(rows)} rows ({raw_values} values read from responses) -> {path}")
    if problems:
        print("PROBLEMS:")
        for p in problems[:60]:
            print("  ", p)
        print(f"   ({len(problems)} total)")


if __name__ == "__main__":
    main()
