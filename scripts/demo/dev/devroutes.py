"""
DEV ONLY - not used for the real recording.

For a sandbox that can't reach the CDNs or OneMap: serves Tailwind, Leaflet and Inter from local
npm copies, grey map tiles, and fakes the two server-side OneMap calls (walking route, place search)
so every scene can be exercised. Enabled by running record_demo.py with FF_DEV=1.

Setup (once), from scripts/demo/dev/:
  mkdir cdn && cd cdn && npm init -y && npm i tailwindcss@3.4.17 leaflet@1.9.4 @fontsource/inter
  # tailwind.config.js with the brand palette from frontend/templates/base.html, content = the templates
  npx tailwindcss -c tailwind.config.js -i in.css -o tw.css --minify
  # tw.js = a script that injects tw.css as a <style>; tile.png = any 256x256 grey PNG
"""
import os, re
SP = os.path.dirname(os.path.abspath(__file__))
NM = os.path.join(SP, "cdn", "node_modules")

FONT_CSS = ""
for w in (400, 500, 600, 700):
    FONT_CSS += (f"@font-face{{font-family:'Inter';font-style:normal;font-weight:{w};font-display:swap;"
                 f"src:url(https://fonts.gstatic.com/inter-latin-{w}-normal.woff2) format('woff2');}}\n")


def install(context):
    def handle(route):
        url = route.request.url
        if "cdn.tailwindcss.com" in url:
            return route.fulfill(path=os.path.join(SP, "cdn", "tw.js"), content_type="application/javascript")
        if "unpkg.com/leaflet" in url:
            rel = url.split("/dist/", 1)[1]
            return route.fulfill(path=os.path.join(NM, "leaflet", "dist", rel),
                                 headers={"access-control-allow-origin": "*"})
        if "fonts.googleapis.com" in url:
            return route.fulfill(body=FONT_CSS, content_type="text/css")
        if "fonts.gstatic.com" in url:
            m = re.search(r"inter-latin-(\d+)-normal", url)
            return route.fulfill(path=os.path.join(NM, "@fontsource", "inter", "files", f"inter-latin-{m.group(1)}-normal.woff2"),
                                 headers={"access-control-allow-origin": "*"}, content_type="font/woff2")
        if "/maps/tiles/" in url:
            return route.fulfill(path=os.path.join(SP, "cdn", "tile.png"), content_type="image/png")
        if "onemap.gov.sg" in url:
            return route.fulfill(status=404, body="")
        return route.continue_()
    context.route(re.compile(r"https?://(cdn\.tailwindcss\.com|unpkg\.com|fonts\.(googleapis|gstatic)\.com|www\.onemap\.gov\.sg)/.*"), handle)

    # Stand-ins for the two server-side OneMap calls (routing, place search).
    import json, math, urllib.request
    from urllib.parse import urlparse, parse_qs, urlencode

    def enc(points):
        out, plat, plng = [], 0, 0
        for lat, lng in points:
            for v, prev in ((lat, plat), (lng, plng)):
                d = int(round(v * 1e5)) - int(round(prev * 1e5))
                d = ~(d << 1) if d < 0 else d << 1
                while d >= 0x20:
                    out.append(chr((0x20 | (d & 0x1f)) + 63)); d >>= 5
                out.append(chr(d + 63))
            plat, plng = lat, lng
        return "".join(out)

    def walking(route):
        q = parse_qs(urlparse(route.request.url).query)
        base = route.request.url.split("/api/")[0]
        flat = json.load(urllib.request.urlopen(f"{base}/api/flats/{q['flat_id'][0]}/amenities"))["flat"]
        a, b = (flat["lat"], flat["lng"]), (float(q["lat"][0]), float(q["lng"][0]))
        pts = [a, (a[0], (a[1] + b[1]) / 2), ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2 + 0.0004), b]
        m = math.hypot((a[0]-b[0]) * 111000, (a[1]-b[1]) * 111000) * 1.3
        route.fulfill(content_type="application/json",
                      body=json.dumps({"metres": round(m), "minutes": max(1, round(m / 80)), "routeGeometry": enc(pts)}))

    def place(route):
        u = urlparse(route.request.url); q = parse_qs(u.query)
        label = q.pop("q", [""])[0]
        q.update({"anchor_lat": ["1.351050"], "anchor_lng": ["103.848500"], "anchor_label": [label.upper()], "w_anchor": ["5"]})
        route.fulfill(status=302, headers={"location": u.path + "?" + urlencode(q, doseq=True)})

    context.route(re.compile(r".*/api/walking-distance\?.*"), walking)
    context.route(re.compile(r".*/results\?(.*&)?q=.*"), place)
