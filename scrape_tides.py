"""Scrape Singapore monthly tide + astronomical tables (MSS / MPA data).

Source: https://www.weather.gov.sg/weather-astronomical-and-tidal-information-monthly-data/
The page only ships the current month in its static HTML; other year/month
tabs are switched client-side, so this drives a headless browser.

Outputs (in ./out):
  tides.csv       datetime_sgt, height_m, type (H/L)
  astro.csv       date, sunrise, sunset, moonrise, moonset, moon_fraction
  network_log.txt every request the page made (to spot a direct data endpoint)
  debug_*.html    page HTML on failures
Usage: python scrape_tides.py [--start-year 2015] [--end-year 2026] [--discover]
"""
import argparse
import csv
import hashlib
import re
import sys
import time
from datetime import datetime, date
from pathlib import Path

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

URL = "https://www.weather.gov.sg/weather-astronomical-and-tidal-information-monthly-data/"
MONTHS = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]
OUT = Path("out")


def to_24h(s):
    """'4.18 am' -> '04:18'; 'NIL'/'' -> None"""
    s = (s or "").strip().lower()
    m = re.match(r"^(\d{1,2})[.:](\d{2})\s*(am|pm)$", s)
    if not m:
        return None
    h, mi, ap = int(m.group(1)), int(m.group(2)), m.group(3)
    if ap == "pm" and h != 12:
        h += 12
    if ap == "am" and h == 12:
        h = 0
    return f"{h:02d}:{mi:02d}"


def parse_table(html, year, month):
    """Return (tide_rows, astro_rows) for the visible monthly table."""
    soup = BeautifulSoup(html, "html.parser")
    best = None
    for t in soup.find_all("table"):
        txt = t.get_text(" ", strip=True)
        if "Rise" in txt and "Height" in txt:
            best = t
            # prefer a visible-looking table whose header matches the month
            if txt.startswith(MONTHS[month - 1][:3]):
                break
    if best is None:
        return [], [], None
    header = best.get_text(" ", strip=True)[:3]
    tides, astro = [], []
    day = None
    for tr in best.find_all("tr"):
        cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
        if len(cells) < 9:
            continue
        d = cells[0]
        if d.isdigit():
            day = int(d)
            dt = date(year, month, day)
            astro.append({
                "date": dt.isoformat(),
                "sunrise": to_24h(cells[1]), "sunset": to_24h(cells[2]),
                "moonrise": to_24h(cells[3]), "moonset": to_24h(cells[4]),
                "moon_fraction": cells[5],
            })
        elif d == "" and day is not None:
            dt = date(year, month, day)
        else:
            continue  # header rows
        tm, ht, hl = to_24h(cells[6]), cells[7], cells[8]
        if tm and hl in ("H", "L"):
            h = re.sub(r"[^0-9.\-]", "", ht)
            tides.append({
                "datetime_sgt": f"{dt.isoformat()} {tm}",
                "height_m": h, "type": hl,
            })
    return tides, astro, header


def click_text(page, scope_hint, text):
    """Click a tab link by exact text (year '2015' or month 'January')."""
    loc = page.locator(f'a[href="#{text}"]')
    if loc.count() == 0:
        loc = page.get_by_role("link", name=text, exact=True)
    loc.first.click()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start-year", type=int, default=2015)
    ap.add_argument("--end-year", type=int, default=datetime.now().year)
    ap.add_argument("--discover", action="store_true",
                    help="only load the page, dump network log + HTML, exit")
    args = ap.parse_args()
    OUT.mkdir(exist_ok=True)

    net = []
    all_tides, all_astro, seen = [], [], {}

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.on("response", lambda r: net.append(
            f"{r.request.method} {r.status} {r.request.resource_type} {r.url}"))
        page.goto(URL, wait_until="networkidle")
        (OUT / "debug_initial.html").write_text(page.content(), encoding="utf-8")

        if args.discover:
            # click one old month to see what request (if any) fires
            click_text(page, "year", "2015")
            page.wait_for_timeout(1500)
            click_text(page, "month", "January")
            page.wait_for_timeout(2000)
            (OUT / "debug_2015_jan.html").write_text(page.content(), encoding="utf-8")
            (OUT / "network_log.txt").write_text("\n".join(net), encoding="utf-8")
            browser.close()
            return

        for year in range(args.start_year, args.end_year + 1):
            try:
                click_text(page, "year", str(year))
                page.wait_for_timeout(800)
            except Exception as e:
                print(f"[warn] year {year}: cannot click tab ({e})", file=sys.stderr)
                continue
            for mi, mname in enumerate(MONTHS, start=1):
                if year == datetime.now().year and mi > datetime.now().month + 1:
                    break
                try:
                    click_text(page, "month", mname)
                    page.wait_for_timeout(700)
                    tides, astro, header = parse_table(page.content(), year, mi)
                except Exception as e:
                    print(f"[warn] {year}-{mi:02d}: {e}", file=sys.stderr)
                    continue
                if not tides:
                    print(f"[warn] {year}-{mi:02d}: no rows", file=sys.stderr)
                    continue
                if header != mname[:3]:
                    print(f"[warn] {year}-{mi:02d}: table header '{header}' != {mname[:3]}",
                          file=sys.stderr)
                    continue
                sig = hashlib.md5(repr(astro).encode()).hexdigest()
                if sig in seen:
                    print(f"[warn] {year}-{mi:02d} identical to {seen[sig]} - tab switch "
                          f"probably failed, skipping", file=sys.stderr)
                    continue
                seen[sig] = f"{year}-{mi:02d}"
                all_tides += tides
                all_astro += astro
                print(f"{year}-{mi:02d}: {len(tides)} tides, {len(astro)} days")
                time.sleep(0.3)  # be polite
        browser.close()

    (OUT / "network_log.txt").write_text("\n".join(net), encoding="utf-8")
    for name, rows, cols in [
        ("tides.csv", all_tides, ["datetime_sgt", "height_m", "type"]),
        ("astro.csv", all_astro,
         ["date", "sunrise", "sunset", "moonrise", "moonset", "moon_fraction"]),
    ]:
        with open(OUT / name, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            w.writerows(rows)
    print(f"done: {len(all_tides)} tide events, {len(all_astro)} days")


if __name__ == "__main__":
    main()
