"""Scrape Singapore monthly tide + astronomical tables (MSS / MPA data).

The monthly page loads each table with a form POST:
  POST .../wiptheme/page-functions/functions-sun-moon-tide-ajax.php
       smt_year=2015&smt_month=January
which returns the <thead>/<tbody> HTML. We call it directly.

Day rows have 9 cells (day, sun rise/set, moon rise/set, fraction, tide time,
height, H/L) with rowspan; the following rows for that day have only 3 cells
(tide time, height, H/L).

Outputs (default ./data):
  tides.csv  datetime_sgt, height_m, type (H/L)
  astro.csv  date, sunrise, sunset, moonrise, moonset, moon_fraction
Usage: python scrape_tides.py [--start-year 2015] [--end-year 2026] [--out data]
"""
import argparse
import calendar
import csv
import hashlib
import re
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

PAGE = "https://www.weather.gov.sg/weather-astronomical-and-tidal-information-monthly-data/"
ENDPOINT = ("https://www.weather.gov.sg/wp-content/themes/wiptheme/"
            "page-functions/functions-sun-moon-tide-ajax.php")
MONTHS = list(calendar.month_name)[1:]
SGT = timezone(timedelta(hours=8))


def to_24h(s):
    """'4.18 am' -> '04:18'; 'NIL'/'' -> None"""
    m = re.match(r"^(\d{1,2})[.:](\d{2})\s*(am|pm)$", (s or "").strip().lower())
    if not m:
        return None
    h, mi, ap = int(m.group(1)), int(m.group(2)), m.group(3)
    if ap == "pm" and h != 12:
        h += 12
    if ap == "am" and h == 12:
        h = 0
    return f"{h:02d}:{mi:02d}"


def parse_month(html, year, month):
    """Parse the endpoint response -> (tides, astro, header_abbrev)."""
    soup = BeautifulSoup(html, "html.parser")
    th = soup.find("th")
    header = th.get_text(strip=True) if th else None
    tides, astro = [], []
    day = None
    for tr in soup.find_all("tr"):
        if tr.find("th"):
            continue
        cells = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
        if len(cells) == 9 and cells[0].isdigit():
            day = int(cells[0])
            d = date(year, month, day)
            astro.append({
                "date": d.isoformat(),
                "sunrise": to_24h(cells[1]), "sunset": to_24h(cells[2]),
                "moonrise": to_24h(cells[3]), "moonset": to_24h(cells[4]),
                "moon_fraction": cells[5],
            })
            tide = cells[6:9]
        elif len(cells) == 3 and day is not None:
            tide = cells
        else:
            continue
        tm = to_24h(tide[0])
        hl = tide[2].strip().upper()
        if tm and hl in ("H", "L"):
            tides.append({
                "datetime_sgt": f"{date(year, month, day).isoformat()} {tm}",
                "height_m": re.sub(r"[^0-9.\-]", "", tide[1]),
                "type": hl,
            })
    return tides, astro, header


def fetch_month(sess, year, month, tries=4):
    for attempt in range(1, tries + 1):
        try:
            r = sess.post(ENDPOINT, data={"smt_year": str(year),
                                          "smt_month": MONTHS[month - 1]},
                          headers={"Referer": PAGE,
                                   "X-Requested-With": "XMLHttpRequest"},
                          timeout=30)
            if r.status_code == 200 and "<tr" in r.text:
                return r.text
            print(f"[warn] {year}-{month:02d}: HTTP {r.status_code}, "
                  f"{len(r.text)} bytes (try {attempt})", file=sys.stderr)
        except requests.RequestException as e:
            print(f"[warn] {year}-{month:02d}: {e} (try {attempt})", file=sys.stderr)
        time.sleep(2 * attempt)
    return None


def main():
    now = datetime.now(SGT)
    ap = argparse.ArgumentParser()
    ap.add_argument("--start-year", type=int, default=2015)
    ap.add_argument("--end-year", type=int, default=now.year)
    ap.add_argument("--out", default="data")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    sess = requests.Session()
    sess.headers["User-Agent"] = "Mozilla/5.0 (compatible; tide-data-scraper)"
    all_tides, all_astro, seen, problems = [], [], {}, []

    for year in range(args.start_year, args.end_year + 1):
        for month in range(1, 13):
            if (year, month) > (now.year, now.month):
                break
            html = fetch_month(sess, year, month)
            if html is None:
                problems.append(f"{year}-{month:02d}: fetch failed")
                continue
            tides, astro, header = parse_month(html, year, month)
            ndays = calendar.monthrange(year, month)[1]
            if header != MONTHS[month - 1][:3]:
                problems.append(f"{year}-{month:02d}: header {header!r}")
                continue
            if len(astro) != ndays:
                problems.append(f"{year}-{month:02d}: {len(astro)} day rows, expected {ndays}")
            if not tides:
                problems.append(f"{year}-{month:02d}: no tide rows")
                continue
            sig = hashlib.md5(repr(astro).encode()).hexdigest()
            if sig in seen:
                problems.append(f"{year}-{month:02d}: identical to {seen[sig]}")
                continue
            seen[sig] = f"{year}-{month:02d}"
            all_tides += tides
            all_astro += astro
            print(f"{year}-{month:02d}: {len(tides)} tides over {len(astro)} days")
            time.sleep(0.5)  # be polite

    for name, rows, cols in [
        ("tides.csv", all_tides, ["datetime_sgt", "height_m", "type"]),
        ("astro.csv", all_astro,
         ["date", "sunrise", "sunset", "moonrise", "moonset", "moon_fraction"]),
    ]:
        with open(out / name, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            w.writerows(rows)
    print(f"\ndone: {len(all_tides)} tide events, {len(all_astro)} days "
          f"-> {out}/")
    if problems:
        print("PROBLEMS:")
        for p in problems:
            print("  ", p)


if __name__ == "__main__":
    main()
