"""Discovery for https://asmc.asean.org/asmc-haze-hotspot-daily-new : what loads the hotspot data?"""
import re
from playwright.sync_api import sync_playwright

URL = "https://asmc.asean.org/asmc-haze-hotspot-daily-new"
STATIC = re.compile(r"\.(png|jpe?g|gif|svg|webp|ico|woff2?|ttf|css)(\?|$)", re.I)
THIRD = re.compile(r"google|gstatic|facebook|doubleclick|wogaa|snowplow|clarity|hotjar", re.I)
log = []

def on_resp(r):
    u = r.url
    if STATIC.search(u) or THIRD.search(u):
        return
    line = f"{r.request.method} {r.status} {r.request.resource_type} {u}"
    if r.request.resource_type in ("xhr", "fetch") or r.request.method != "GET":
        try:
            body = r.text()
        except Exception as e:
            body = f"<no body: {e}>"
        line += (f"\n    POSTDATA: {r.request.post_data}"
                 f"\n    CT: {r.request.headers.get('content-type')}"
                 f"\n    RESP[{len(body)}]: {body[:1200]!r}")
    log.append(line)

with sync_playwright() as p:
    b = p.chromium.launch()
    page = b.new_page(viewport={"width": 1400, "height": 1000})
    page.on("response", on_resp)
    page.goto(URL, wait_until="networkidle")
    log.append("=== AFTER LOAD ===")
    html = page.content()
    open("hotspots_initial.html", "w", encoding="utf-8").write(html)

    print("=== FORM CONTROLS ===")
    for el in page.query_selector_all("input, select, button, a[onclick], [onclick]"):
        try:
            d = el.evaluate("e => ({t:e.tagName, id:e.id, name:e.name||'', type:e.type||'', cls:(e.className||'').toString().slice(0,60), val:(e.value||'').slice(0,40), txt:(e.innerText||'').trim().slice(0,40), onclick:(e.getAttribute('onclick')||'').slice(0,80)})")
            print(d)
        except Exception:
            pass

    print("=== SCRIPT LINES (ajax/url/hotspot) ===")
    n = 0
    for s in re.findall(r"<script[^>]*>(.*?)</script>", html, re.S):
        for ln in s.splitlines():
            if re.search(r"ajax|fetch\(|\.php|\.json|api|hotspot|geojson|\.csv|endpoint|url\s*[:=]", ln, re.I):
                print("  ", ln.strip()[:220]); n += 1
                if n > 120: break
        if n > 120: break
    print("=== SCRIPT SRC ===")
    for m in re.findall(r"<script[^>]+src=[\"']([^\"']+)", html):
        print("  ", m)

    # try pressing View
    log.append("=== CLICK VIEW ===")
    clicked = False
    for sel in ['button:has-text("View")', 'input[value="View"]', 'a:has-text("View")', 'text=View']:
        loc = page.locator(sel)
        if loc.count():
            try:
                loc.first.evaluate("el => el.click()")
                clicked = True
                log.append(f"clicked via {sel} (count={loc.count()})")
                break
            except Exception as e:
                log.append(f"click fail {sel}: {e}")
    page.wait_for_timeout(8000)
    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        pass
    open("hotspots_after_view.html", "w", encoding="utf-8").write(page.content())
    txt = page.evaluate("() => document.body.innerText")
    print("=== BODY TEXT AFTER VIEW (first 2500) ===")
    print(txt[:2500])
    print("=== TABLES/CANVAS/SVG/IMG COUNTS ===")
    print(page.evaluate("() => ({tables:document.querySelectorAll('table').length, canvas:document.querySelectorAll('canvas').length, svg:document.querySelectorAll('svg').length, iframes:document.querySelectorAll('iframe').length, leaflet:!!document.querySelector('.leaflet-container'), gmaps:!!document.querySelector('.gm-style'), ol:!!document.querySelector('.ol-viewport')})"))
    b.close()

print("=== NETWORK ===")
print("\n".join(log))
