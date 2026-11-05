"""Audit: compare raw endpoint HTML against data/tides.csv. Prints discrepancies only."""
import csv, re, time, calendar
import requests
from collections import Counter
import scrape_tides as s

csv_rows = list(csv.DictReader(open("data/tides.csv")))
by_month = Counter(r["datetime_sgt"][:7] for r in csv_rows)
sess = requests.Session(); sess.headers["User-Agent"] = "Mozilla/5.0 (compatible; tide-data-scraper)"
odd = {"2025-02-22", "2026-02-11", "2026-03-12"}
mism = 0; total_raw = 0
for y in range(2015, 2027):
    for m in range(1, 13):
        if (y, m) > (2026, 11): break
        html = s.fetch_month(sess, y, m)
        raw = len(re.findall(r"<td>\s*[HL]\s*</td>", html))
        total_raw += raw
        got = by_month[f"{y}-{m:02d}"]
        if raw != got:
            mism += 1; print(f"MISMATCH {y}-{m:02d}: raw HL cells={raw} csv rows={got}")
        for d in range(1, calendar.monthrange(y, m)[1] + 1):
            key = f"{y}-{m:02d}-{d:02d}"
            if key in odd:
                i = html.find(f'>{d}</td>')
                print(f"RAW {key}:", re.sub(r"\s+", " ", html[i:i+900]))
        time.sleep(0.4)
print(f"total raw tide rows={total_raw} csv rows={len(csv_rows)} month mismatches={mism}")
