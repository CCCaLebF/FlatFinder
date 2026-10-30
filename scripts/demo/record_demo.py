"""
FlatFinder demo recorder (SC2006 3.3.1).

Drives a browser through the demo while recording it as a 1920x1080, 30 fps H.264 video.
Each scene is held for at least as long as its voiceover, and every scene's start time is
written to scenes.json so the narration can be lined up afterwards.

Outputs (in ./out):  recording.mp4, scenes.json, log.txt, plus a PNG for any step that failed.

Run it while FlatFinder is up (docker compose up) with the data loaded. See docs/demo-video-handoff.md.
"""
import base64, json, os, re, subprocess, sys, threading, time, traceback
from urllib.parse import urlencode

from playwright.sync_api import sync_playwright

BASE = os.environ.get("FF_URL", "http://localhost:8000").rstrip("/")
OUT = os.environ.get("FF_OUT", "out")
FPS = 30
VIEW_W, VIEW_H, SCALE = 1440, 810, 4 / 3          # renders at 1920x1080
LEAD, TAIL = 0.6, 0.9                            # seconds of breathing room around each voiceover
SEARCH_PLACE = os.environ.get("FF_PLACE", "Bishan MRT")

HERE = os.path.dirname(os.path.abspath(__file__))

# Voiceover length of each scene, in seconds. tts.py writes vo/durations.json; these defaults
# match the committed narration.json voiced with Kokoro af_heart at speed 1.0.
_DUR_FILE = os.path.join(HERE, "vo", "durations.json")
DURATIONS = (json.load(open(_DUR_FILE)) if os.path.exists(_DUR_FILE) else None) or {
    "s01_intro": 22.23, "s02_filters": 17.62, "s03_weights": 15.77, "s04_results": 23.89,
    "s05_sort": 10.97, "s06_searchbar": 18.28, "s07_details": 14.98, "s08_details_more": 10.39,
    "s09_bookmark": 5.01, "s10_flatmap": 15.13, "s11_layers": 9.58, "s12_walking": 16.85,
    "s13_browse": 23.06, "s14_saved": 10.86, "s15_compare": 20.14, "s16_noresults": 13.03,
    "s17_failure": 19.35, "s18_outro": 18.11,
}

os.makedirs(OUT, exist_ok=True)
LOG = open(os.path.join(OUT, "log.txt"), "w", encoding="utf-8")


def log(*parts):
    line = time.strftime("%H:%M:%S ") + " ".join(str(p) for p in parts)
    print(line, flush=True)
    LOG.write(line + "\n"); LOG.flush()


def ffmpeg_exe():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


# --------------------------------------------------------------------------------------------
# Recorder: the page's own screencast frames (JPEG) -> constant 30 fps -> H.264
# --------------------------------------------------------------------------------------------
class Recorder:
    def __init__(self, page, path):
        self.page = page
        self.path = path
        self.latest = None
        self.lock = threading.Lock()
        self.stop_flag = threading.Event()
        self.cdp = page.context.new_cdp_session(page)
        self.cdp.on("Page.screencastFrame", self._on_frame)
        self.t0 = None
        self.frames = 0

    def _on_frame(self, params):
        with self.lock:
            self.latest = base64.b64decode(params["data"])
        try:
            self.cdp.send("Page.screencastFrameAck", {"sessionId": params["sessionId"]})
        except Exception:
            pass

    def _start_cast(self):
        self.cdp.send("Page.startScreencast", {"format": "jpeg", "quality": 92,
                                               "maxWidth": 1920, "maxHeight": 1080, "everyNthFrame": 1})

    def start(self):
        self._start_cast()
        deadline = time.time() + 10
        while self.latest is None and time.time() < deadline:
            self.page.wait_for_timeout(50)
        tmp = self.path + ".part.mp4"
        self.proc = subprocess.Popen(
            [ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y",
             "-f", "image2pipe", "-c:v", "mjpeg", "-framerate", str(FPS), "-i", "-",
             "-vf", "scale=1920:1080:flags=lanczos,format=yuv420p",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-r", str(FPS), tmp],
            stdin=subprocess.PIPE)
        self.tmp = tmp
        self.t0 = time.perf_counter()
        self.thread = threading.Thread(target=self._writer, daemon=True)
        self.thread.start()

    def _writer(self):
        while not self.stop_flag.is_set():
            target = self.t0 + self.frames / FPS
            delay = target - time.perf_counter()
            if delay > 0:
                time.sleep(delay)
            with self.lock:
                frame = self.latest
            try:
                self.proc.stdin.write(frame)
            except Exception:
                break
            self.frames += 1

    def now(self):
        return time.perf_counter() - self.t0

    def stop(self):
        self.stop_flag.set()
        self.thread.join(timeout=5)
        try:
            self.cdp.send("Page.stopScreencast")
        except Exception:
            pass
        self.proc.stdin.close()
        code = self.proc.wait()
        if code == 0:
            os.replace(self.tmp, self.path)
        log(f"recording stopped: {self.frames} frames ({self.frames / FPS:.1f}s), ffmpeg exit {code}")


# --------------------------------------------------------------------------------------------
# A visible cursor with click ripples (headless browsers don't draw the mouse)
# --------------------------------------------------------------------------------------------
CURSOR_JS = r"""
(() => {
  const KEY = '__ffpos';
  let pos = {x: 720, y: 405};
  try { pos = JSON.parse(sessionStorage.getItem(KEY)) || pos; } catch (e) {}
  let cursor;
  const place = () => { if (cursor) cursor.style.transform = `translate(${pos.x - 4}px, ${pos.y - 2}px)`; };
  const install = () => {
    if (document.getElementById('__ffcursor')) return;
    cursor = document.createElement('div');
    cursor.id = '__ffcursor';
    cursor.innerHTML = '<svg width="26" height="30" viewBox="0 0 26 30"><path d="M4 2 L4 24 L9.5 18.8 L13.2 27.2 L17 25.6 L13.4 17.4 L21 17.2 Z" fill="#111" stroke="#fff" stroke-width="2" stroke-linejoin="round"/></svg>';
    Object.assign(cursor.style, {position: 'fixed', left: 0, top: 0, zIndex: 2147483647, pointerEvents: 'none',
                                 filter: 'drop-shadow(0 1px 2px rgba(0,0,0,.35))', willChange: 'transform'});
    document.documentElement.appendChild(cursor);
    place();
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', install); else install();
  addEventListener('mousemove', e => {
    pos = {x: e.clientX, y: e.clientY}; install(); place();
    try { sessionStorage.setItem(KEY, JSON.stringify(pos)); } catch (err) {}
  }, true);
  addEventListener('mousedown', e => {
    const r = document.createElement('div');
    Object.assign(r.style, {position: 'fixed', left: (e.clientX - 18) + 'px', top: (e.clientY - 18) + 'px',
      width: '36px', height: '36px', borderRadius: '50%', border: '3px solid rgba(40,116,98,.85)',
      background: 'rgba(40,116,98,.18)', zIndex: 2147483646, pointerEvents: 'none',
      transform: 'scale(.3)', opacity: '1', transition: 'transform .45s ease-out, opacity .45s ease-out'});
    document.documentElement.appendChild(r);
    requestAnimationFrame(() => { r.style.transform = 'scale(1.4)'; r.style.opacity = '0'; });
    setTimeout(() => r.remove(), 600);
  }, true);
  // Smooth in-page scrolling for the scripted wheel moves.
  document.documentElement.style.scrollBehavior = 'auto';
})();
"""


# --------------------------------------------------------------------------------------------
# Human-like helpers
# --------------------------------------------------------------------------------------------
class Demo:
    def __init__(self, page, rec):
        self.page = page
        self.rec = rec
        self.mx, self.my = VIEW_W / 2, VIEW_H / 2
        self.scenes = []
        self.saved = {}
        self.budget_end = None

    def wait(self, s):
        """A hold. Inside a scene it shrinks once the scene is close to its narration length."""
        if self.budget_end is not None and self.rec.now() > self.budget_end - 1.5:
            s = min(s, 0.25)
        self.page.wait_for_timeout(int(s * 1000))

    def move(self, x, y, duration=0.55):
        steps = max(6, int(duration * 30))
        x0, y0 = self.mx, self.my
        for i in range(1, steps + 1):
            t = i / steps
            e = t * t * (3 - 2 * t)  # smoothstep
            self.page.mouse.move(x0 + (x - x0) * e, y0 + (y - y0) * e)
            self.page.wait_for_timeout(int(duration * 1000 / steps))
        self.mx, self.my = x, y

    def box(self, loc, timeout=8000):
        loc.wait_for(state="visible", timeout=timeout)
        loc.scroll_into_view_if_needed(timeout=timeout)
        self.page.wait_for_timeout(150)
        return loc.bounding_box()

    def hover(self, loc, dx=0.5, dy=0.5, duration=0.55):
        b = self.box(loc)
        self.move(b["x"] + b["width"] * dx, b["y"] + b["height"] * dy, duration)

    def click(self, loc, dx=0.5, dy=0.5, duration=0.55, settle=0.25):
        self.hover(loc, dx, dy, duration)
        self.wait(0.12)
        self.page.mouse.down(); self.wait(0.06); self.page.mouse.up()
        self.wait(settle)

    def click_pin(self, cat, duration=1.0):
        """Click the amenity pin of a category nearest the map centre (the flat) that no other pin
        covers. Close amenities can sit under the flat's own pin; if every pin of the category is
        covered, the cursor still moves there and the click goes straight to the pin's element."""
        pins = self.page.locator(f".leaflet-marker-icon:has(.ff-cat-{cat})")
        if not pins.count():
            return False
        order = pins.evaluate_all("""els => {
            const m = document.querySelector('.leaflet-container').getBoundingClientRect();
            const cx = m.left + m.width / 2, cy = m.top + m.height / 2;
            return els.map((el, i) => {
                const r = el.getBoundingClientRect(), x = r.left + r.width / 2, y = r.top + r.height * 0.4;
                return {i, free: el.contains(document.elementFromPoint(x, y)), d: Math.hypot(x - cx, y - cy)};
            }).sort((a, b) => (b.free - a.free) || (a.d - b.d));
        }""")
        best = order[0]
        pin = pins.nth(best["i"])
        if best["free"]:
            self.click(pin, dy=0.4, duration=duration)   # the point checked above
        else:
            self.hover(pin, duration=duration)
            self.wait(0.12)
            pin.dispatch_event("click")
            self.wait(0.25)
        return True

    def click_nav(self, loc, timeout=20000, **kw):
        with self.page.expect_navigation(wait_until="load", timeout=timeout):
            self.click(loc, **kw)
        self.settle()

    def settle(self):
        try:
            self.page.wait_for_load_state("networkidle", timeout=6000)
        except Exception:
            pass

    def type(self, loc, text, delay=75):
        self.click(loc)
        loc.press("Control+a"); loc.press("Backspace")
        loc.press_sequentially(text, delay=delay)

    def scroll(self, dy, duration=2.0, at=None):
        if at:
            self.move(*at, duration=0.4)
        steps = max(8, int(duration * 25))
        for _ in range(steps):
            self.page.mouse.wheel(0, dy / steps)
            self.page.wait_for_timeout(int(duration * 1000 / steps))

    def set_slider(self, name, value):
        s = self.page.locator(f"#id_{name}")
        b = self.box(s)
        lo, hi = float(s.get_attribute("min")), float(s.get_attribute("max"))
        frac = (value - lo) / (hi - lo)
        thumb = 16
        self.click(s, dx=(thumb / 2 + frac * (b["width"] - thumb)) / b["width"], dy=0.5, duration=0.45, settle=0.15)
        current = float(s.input_value())
        step = float(s.get_attribute("step") or 1)
        diff = int(round((value - current) / step))
        for _ in range(abs(diff)):
            s.press("ArrowRight" if diff > 0 else "ArrowLeft")
            self.page.wait_for_timeout(70)

    def off_toggle(self, flag):
        """Click the 'Any' / 'No limit' / 'Ignore' label next to a slider."""
        cb = self.page.locator(f"input[name='{flag}'][data-off]")
        self.click(cb.locator("xpath=.."), dx=0.25)

    # ---- scenes ----
    def scene(self, sid, fn):
        start = self.rec.now()
        need = LEAD + DURATIONS.get(sid, 5) + TAIL
        self.budget_end = start + need
        self.page.wait_for_timeout(int(LEAD * 500))
        ok = True
        try:
            fn()
        except Exception as exc:
            ok = False
            log(f"[{sid}] step failed: {exc!r}")
            LOG.write(traceback.format_exc() + "\n")
            try:
                self.page.screenshot(path=os.path.join(OUT, f"failed_{sid}.png"))
            except Exception:
                pass
        self.budget_end = None
        left = need - (self.rec.now() - start)
        if left > 0:
            self.page.wait_for_timeout(int(left * 1000))
        end = self.rec.now()
        self.scenes.append({"id": sid, "start": round(start, 3), "end": round(end, 3), "ok": ok, "url": self.page.url})
        log(f"[{sid}] {start:7.2f}s -> {end:7.2f}s ({end - start:5.2f}s){'' if ok else '  FAILED'}")


def with_view(url, view):
    from urllib.parse import urlsplit, urlunsplit, parse_qsl
    u = urlsplit(url)
    q = [(k, v) for k, v in parse_qsl(u.query, keep_blank_values=True) if k != "view"] + [("view", view)]
    return urlunsplit((u.scheme, u.netloc, u.path, urlencode(q), u.fragment))


def run():
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--no-proxy-server", "--hide-scrollbars", "--force-color-profile=srgb"])
        context = browser.new_context(viewport={"width": VIEW_W, "height": VIEW_H}, device_scale_factor=SCALE,
                                      locale="en-SG", timezone_id="Asia/Singapore")
        if os.environ.get("FF_DEV"):                     # offline development only, see dev/devroutes.py
            sys.path.insert(0, os.path.join(HERE, "dev")); import devroutes; devroutes.install(context)
        context.add_init_script(CURSOR_JS)
        page = context.new_page()
        page.set_default_timeout(15000)
        page.on("console", lambda m: log("console:", m.text) if m.type == "error" else None)

        # Warm up (fonts, CSS) before recording, then start fresh on the start page.
        page.goto(BASE + "/", wait_until="load")
        page.goto(BASE + "/", wait_until="load")
        page.wait_for_timeout(1500)

        rec = Recorder(page, os.path.join(OUT, "recording.mp4"))
        rec.start()
        d = Demo(page, rec)
        pg = page
        sidebar_btn = lambda: pg.locator("button[type=submit]", has_text="Find Matching Flats")

        # 1 — Start page
        def s01():
            d.wait(4)
            d.hover(pg.locator("h1, h2", has_text="FlatFinder").last, duration=1.2)
            d.wait(6)
            d.hover(pg.locator("text=Set your limits").first, dx=0.3, duration=1.2)
            d.wait(4)
            d.hover(pg.locator("input[name=max_budget]"), duration=1.0)
        d.scene("s01_intro", s01)

        # 2 — Filters (UC-08)
        def s02():
            d.type(pg.locator("input[name=max_budget]"), "650000")
            d.wait(0.6)
            for label in ("4 Room", "5 Room"):
                d.click(pg.locator("label", has=pg.locator("input[name=flat_type]")).filter(has_text=label))
                d.wait(0.3)
            d.wait(0.6)
            d.off_toggle("lease_any")
            d.set_slider("min_lease", 70)
            d.wait(1.0)
            d.off_toggle("mrt_any")
            d.set_slider("max_walk_mrt", 800)
        d.scene("s02_filters", s02)

        # 3 — Priority weights, then search (UC-01)
        def s03():
            d.hover(pg.locator("legend", has_text="Priority weights"), dx=0.2, duration=0.8)
            d.wait(2.5)
            d.set_slider("w_mrt_station", 9); d.wait(0.5)
            d.set_slider("w_hawker_centre", 8); d.wait(0.5)
            d.set_slider("w_child_care_centre", 2); d.wait(0.5)
            d.wait(max(0.0, DURATIONS["s03_weights"] - 9.5))
            d.click_nav(sidebar_btn())
            d.saved["results"] = pg.url
        d.scene("s03_weights", s03)

        # 4 — Ranked results (UC-09)
        def s04():
            d.hover(pg.locator("text=match your requirements").first, dx=0.2, duration=0.9)
            d.wait(2.5)
            card = pg.locator("[data-block-card], [data-flat-card]").first
            d.hover(card.locator("text=FIT").first, duration=0.9)
            d.wait(4)
            d.hover(card.locator("text=RESALE PRICE").first, duration=0.8)
            d.wait(2)
            d.hover(card.locator(".ff-swatch.ff-cat-bus_stop").first.locator("xpath=.."), duration=0.8)
            d.wait(2)
            d.scroll(1000, duration=3.2, at=(VIEW_W * 0.68, VIEW_H * 0.6))
            d.wait(0.8)
            d.scroll(-1000, duration=1.4)
        d.scene("s04_results", s04)

        # 5 — Sort (UC-10)
        def s05():
            sel = pg.locator("#sort")
            d.hover(sel, duration=0.8)
            d.wait(0.6)
            with pg.expect_navigation(wait_until="load"):
                sel.select_option("price-asc")
            d.settle(); d.wait(3.0)
            d.hover(pg.locator("[data-block-card], [data-flat-card]").first.locator("text=RESALE PRICE"), duration=0.8)
            d.wait(1.5)
            d.hover(pg.locator("#sort"), duration=0.8)
            with pg.expect_navigation(wait_until="load"):
                pg.locator("#sort").select_option(index=0)
            d.settle()
        d.scene("s05_sort", s05)

        # 6 — Search bar (UC-07)
        def s06():
            d.wait(1.5)
            d.type(pg.locator("#search-bar"), SEARCH_PLACE, delay=95)
            d.wait(0.5)
            d.click_nav(pg.locator("[data-search-bar] button[type=submit]"))
            d.saved["results"] = pg.url
            d.wait(1.0)
            chip = pg.locator("[data-anchor-chip]")
            if chip.count():
                d.hover(chip, dx=0.4, duration=0.8); d.wait(2.0)
            near = pg.locator("#id_w_anchor")
            if near.count():
                d.hover(near, duration=0.9); d.wait(2.0)
            d.hover(pg.locator("[data-block-card], [data-flat-card]").first, dx=0.3, dy=0.6, duration=1.0)
        d.scene("s06_searchbar", s06)

        # 7 — Flat details (UC-02)
        def s07():
            first = pg.locator("[data-block-card], [data-flat-card]").first
            d.click_nav(first.locator("a[aria-label^='View details']"), dx=0.3, dy=0.25)
            d.saved["details"] = pg.url
            d.wait(1.0)
            d.hover(pg.locator("[data-block-building], [data-block-house]").first, duration=1.0)
            d.wait(4.0)
            d.hover(pg.locator("[data-fit-score]").first, duration=1.0)
            d.wait(1.0)
            d.hover(pg.locator("text=Remaining lease").last, dx=0.2, duration=0.9)
        d.scene("s07_details", s07)

        # 8 — More details, nearby amenities (UC-11)
        def s08():
            d.scroll(700, duration=2.5, at=(VIEW_W * 0.5, VIEW_H * 0.6))
            d.wait(2.0)
            d.scroll(650, duration=2.5)
            d.wait(1.5)
            near = pg.locator("[data-nearby]")
            if near.count():
                near.first.scroll_into_view_if_needed()
            d.scroll(400, duration=1.5)
        d.scene("s08_details_more", s08)

        # 9 — Bookmark (UC-05)
        def s09():
            d.scroll(-3000, duration=1.6)
            d.click(pg.locator("[data-bookmark-button]").first, duration=0.8, settle=0.6)
            d.hover(pg.locator("header a[href$='/saved/']"), dx=0.4, duration=0.9)
        d.scene("s09_bookmark", s09)

        # 10 — The flat on the map (UC-03, UC-11)
        def s10():
            link = pg.locator("a", has_text="Open this block in Map View").first
            d.click_nav(link, dx=0.3)
            d.saved["flatmap"] = pg.url
            pg.locator(".ff-amenity").first.wait_for(timeout=15000)
            d.wait(2.0)
            d.move(VIEW_W * 0.68, VIEW_H * 0.52, duration=1.2)
        d.scene("s10_flatmap", s10)

        # 11 — Layer toggles (UC-12)
        def s11():
            for key in ("bus_stop", "child_care_centre"):
                lab = pg.locator(f"input[data-layer-toggle='{key}']").locator("xpath=..")
                d.click(lab, duration=0.8)
                d.wait(1.6)
        d.scene("s11_layers", s11)

        # 12 — Walking distance (UC-04)
        def s12():
            # Zoom in so the short walking routes are long enough to see beside the popup.
            for _ in range(2):
                d.click(pg.locator(".leaflet-control-zoom-in"), duration=0.6)
                d.wait(0.5)
            pg.wait_for_timeout(600)
            d.click_pin("mrt_station")
            try:
                pg.wait_for_function("() => { const w = document.querySelector('.leaflet-popup .ff-walk');"
                                     " return w && /done|failed/.test(w.dataset.state || ''); }", timeout=10000)
            except Exception:
                pass
            d.wait(4.5)
            pg.keyboard.press("Escape"); d.wait(0.4)
            if d.click_pin("hawker_centre"):
                try:
                    pg.wait_for_function("() => { const w = document.querySelector('.leaflet-popup .ff-walk');"
                                         " return w && /done|failed/.test(w.dataset.state || ''); }", timeout=10000)
                except Exception:
                    pass
        d.scene("s12_walking", s12)

        # 13 — Browse the whole result set on the map (UC-03)
        def s13():
            pg.goto(with_view(d.saved.get("results", BASE + "/"), "map"), wait_until="load"); d.settle()
            d.wait(0.8)
            areas = pg.locator(".leaflet-marker-icon:has(.ff-area)")
            zoom_out = pg.locator(".leaflet-control-zoom-out")
            for _ in range(5):                      # zoom out until the town counts show
                if areas.count():
                    break
                d.click(zoom_out, duration=0.5, settle=0.5)
            d.move(VIEW_W * 0.66, VIEW_H * 0.5, duration=0.8)
            d.wait(1.5)
            if areas.count():
                target = None
                for i in range(areas.count()):
                    if re.search(re.escape(SEARCH_PLACE.split()[0]), areas.nth(i).get_attribute("title") or "", re.I):
                        target = areas.nth(i); break
                d.click(target or areas.first, duration=0.9, settle=1.2)
            d.wait(1.0)
            show = pg.locator("[data-show-on-map]")
            if show.count():                        # highlight the top result on the map
                d.click(show.first, duration=0.8, settle=0.5)
                d.wait(1.2)
            toggle = pg.locator(".ff-panel-toggle")
            if toggle.count():
                d.click(toggle, duration=0.8); d.wait(1.8)
                d.click(toggle, duration=0.6, settle=0.6)
            # A pin opens that block's details (UC-02's map entry point).
            pins = pg.locator(".leaflet-marker-icon").filter(has=pg.locator(".ff-pin[class*='ff-fit-']:has(svg)"))
            # Nearest block pin to the map centre, measured in one in-page call.
            idx = pins.evaluate_all("""els => {
                const m = document.querySelector('#map').getBoundingClientRect();
                const cx = m.left + m.width / 2, cy = m.top + m.height / 2;
                let best = -1, bd = 1e12;
                els.forEach((e, i) => {
                    const r = e.getBoundingClientRect();
                    if (r.left < m.left + 40 || r.right > m.right - 60 || r.top < m.top + 40 || r.bottom > m.bottom - 60) return;
                    if (document.querySelector('.leaflet-popup')?.getBoundingClientRect &&
                        (() => { const p = document.querySelector('.leaflet-popup').getBoundingClientRect();
                                 return r.left < p.right && r.right > p.left && r.top < p.bottom && r.bottom > p.top; })()) return;
                    const d = (r.left - cx) ** 2 + (r.top - cy) ** 2;
                    if (d < bd) { bd = d; best = i; }
                });
                return best;
            }""")
            best = pins.nth(idx) if idx is not None and idx >= 0 else None
            if best is not None:
                d.hover(best, duration=0.8)
                d.wait(0.3)
                try:
                    d.click_nav(best, duration=0.2, timeout=6000)
                except Exception:
                    pass
                d.wait(0.5)
        d.scene("s13_browse", s13)

        # 14 — Bookmarks and the Saved page (UC-05, UC-14)
        def s14():
            pg.goto(with_view(d.saved.get("results", BASE + "/"), "list"), wait_until="load"); d.settle()
            cards = pg.locator("[data-block-card], [data-flat-card]")
            added = 0
            for i in range(cards.count()):
                btn = cards.nth(i).locator("[data-bookmark-button]")
                if btn.count() and (btn.first.get_attribute("aria-pressed") != "true"):
                    d.click(btn.first, duration=0.8, settle=0.5); added += 1
                if added == 2:
                    break
            d.click_nav(pg.locator("header a[href$='/saved/']"), dx=0.4)
            d.wait(2.5)
            items = pg.locator("[data-saved-item] button[aria-label='Remove from saved flats']")
            if items.count():
                d.click(items.last, duration=0.9, settle=0.2)
                pg.wait_for_timeout(1200)          # fixed hold: let the counter visibly drop
        d.scene("s14_saved", s14)

        # 15 — Compare (UC-15)
        def s15():
            pg.goto(with_view(d.saved.get("results", BASE + "/"), "list"), wait_until="load"); d.settle()
            btns = pg.locator("[data-compare-button]")
            for i in range(min(3, btns.count())):
                d.click(btns.nth(i), duration=0.8, settle=0.5)
            d.hover(pg.locator("#compare-tray"), dx=0.2, duration=0.8)
            d.wait(1.0)
            d.click_nav(pg.locator("#compare-tray a", has_text="Compare"))
            d.wait(1.5)
            win = pg.locator("text=/wins\\.$/").first
            if win.count():
                d.hover(win, dx=0.3, duration=0.9)
            d.wait(4.0)
            d.set_slider("cw_price", 10)
            d.wait(0.8)
            d.click_nav(pg.locator("button", has_text="Update"))
            d.wait(1.0)
            win = pg.locator("text=/wins\\.$/").first
            if win.count():
                d.hover(win, dx=0.3, duration=0.9)
        d.scene("s15_compare", s15)

        # 16 — No results (UC-01.EX.1)
        def s16():
            pg.goto(BASE + "/", wait_until="load"); d.settle()
            d.type(pg.locator("input[name=max_budget]"), "200000")
            d.click(pg.locator("label", has=pg.locator("input[name=flat_type]")).filter(has_text="5 Room"))
            d.click_nav(sidebar_btn())
            d.wait(1.0)
            d.hover(pg.locator("text=No flats match").first, duration=1.0)
            d.wait(2.0)
            d.hover(pg.locator("text=widening your budget").first, dx=0.3, duration=1.0)
        d.scene("s16_noresults", s16)

        # 17 — OneMap failure (UC-06, UC-13): block OneMap in the browser
        def s17():
            context.route(re.compile(r"https?://www\.onemap\.gov\.sg/maps/tiles/.*"), lambda r: r.abort())
            context.route(re.compile(r".*/api/walking-distance.*"), lambda r: r.fulfill(
                status=502, content_type="application/json",
                body=json.dumps({"error": "OneMap service currently unavailable. Please try again later."})))
            target = with_view(d.saved.get("results", BASE + "/"), "map")
            pg.goto(target, wait_until="load"); d.settle()
            d.wait(2.0)
            banner = pg.locator("[data-error-banner]")
            if banner.count():
                d.hover(banner, dx=0.3, duration=1.0)
            d.wait(4.0)
            if d.saved.get("flatmap"):
                pg.goto(d.saved["flatmap"], wait_until="load"); d.settle()
                d.wait(1.5)
                d.click_pin("mrt_station")
                d.wait(3.5)
            d.click_nav(pg.locator("header a[href$='/saved/']"), dx=0.4)
        d.scene("s17_failure", s17)

        # 18 — Outro
        def s18():
            context.unroute_all(behavior="ignoreErrors")
            if os.environ.get("FF_DEV"):
                import devroutes; devroutes.install(context)  # already on sys.path from the setup above
            pg.goto(with_view(d.saved.get("results", BASE + "/"), "list"), wait_until="load"); d.settle()
            d.move(VIEW_W * 0.62, VIEW_H * 0.45, duration=1.5)
            d.scroll(500, duration=6.0, at=(VIEW_W * 0.68, VIEW_H * 0.6))
        d.scene("s18_outro", s18)

        rec.stop()
        meta = {"fps": FPS, "size": [1920, 1080], "lead": LEAD, "tail": TAIL, "base": BASE,
                "place": SEARCH_PLACE, "scenes": d.scenes}
        json.dump(meta, open(os.path.join(OUT, "scenes.json"), "w"), indent=1)
        failed = [s["id"] for s in d.scenes if not s["ok"]]
        log("done.", "failed scenes: " + (", ".join(failed) if failed else "none"))
        browser.close()


if __name__ == "__main__":
    run()
