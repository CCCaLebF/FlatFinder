"""Assemble the final demo: title card + recording (with use-case labels) + end card, voiceover synced to scenes.json.
usage: python assemble.py <recording_dir> <out.mp4> [--title "..."] [--subtitle "..."]
"""
import argparse, json, os, subprocess, wave
from playwright.sync_api import sync_playwright

SP = os.path.dirname(os.path.abspath(__file__))
ap = argparse.ArgumentParser()
ap.add_argument("rec_dir"); ap.add_argument("out")
ap.add_argument("--title", default="FlatFinder")
ap.add_argument("--subtitle", default="SC2006 Software Engineering · Product Demo")
ap.add_argument("--team", default="")
args = ap.parse_args()

W = os.path.join(SP, "build"); os.makedirs(W, exist_ok=True)
meta = json.load(open(os.path.join(args.rec_dir, "scenes.json")))
narr = {s["id"]: s for s in json.load(open(os.path.join(SP, "narration.json")))}
LEAD = meta["lead"]
TITLE_S, END_S, FADE = 4.5, 5.0, 0.5
ENC = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", "-r", "30"]

def run(cmd):
    subprocess.run(cmd, check=True)

def dur(path):
    with wave.open(path) as w:
        return w.getnframes() / w.getframerate()

CARD = """<html><head>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=block">
<style>
@font-face{font-family:InterLocal;font-weight:400;src:url(file://%(nm)s/@fontsource/inter/files/inter-latin-400-normal.woff2)}
@font-face{font-family:InterLocal;font-weight:600;src:url(file://%(nm)s/@fontsource/inter/files/inter-latin-600-normal.woff2)}
@font-face{font-family:InterLocal;font-weight:700;src:url(file://%(nm)s/@fontsource/inter/files/inter-latin-700-normal.woff2)}
html,body{margin:0;width:1920px;height:1080px;font-family:Inter,InterLocal,sans-serif;background:%(bg)s}
</style></head><body>%(body)s</body></html>"""
NM = os.path.join(SP, "dev", "cdn", "node_modules")   # only used when Google Fonts is unreachable
HOUSE = '<svg width="%d" height="%d" viewBox="0 0 24 24" fill="none"><path d="M3 11.2 12 4l9 7.2V20a1 1 0 0 1-1 1h-5v-5.5h-6V21H4a1 1 0 0 1-1-1z" fill="#fff"/></svg>'

def card_html(kind):
    if kind == "title":
        team = f'<div style="margin-top:28px;font-size:30px;color:#84c9b3">{args.team}</div>' if args.team else ""
        body = f"""<div style="height:100%;display:flex;flex-direction:column;align-items:center;justify-content:center;
          background:radial-gradient(1200px 700px at 50% 40%,#225e50,#1a3f37)">
          <div style="width:150px;height:150px;border-radius:36px;background:#368f77;display:grid;place-items:center;box-shadow:0 20px 50px rgba(0,0,0,.3)">{HOUSE % (92, 92)}</div>
          <div style="margin-top:44px;font-size:110px;font-weight:700;color:#fff;letter-spacing:-2px">{args.title}</div>
          <div style="margin-top:16px;font-size:38px;color:#d9f0e8">Find an HDB resale flat that fits your budget and your life</div>
          <div style="margin-top:56px;font-size:30px;font-weight:600;color:#b4e0d1;letter-spacing:1px">{args.subtitle}</div>{team}</div>"""
        return CARD % {"nm": NM, "bg": "#1a3f37", "body": body}
    body = """<div style="height:100%;display:flex;flex-direction:column;align-items:center;justify-content:center;
      background:radial-gradient(1200px 700px at 50% 40%,#225e50,#1a3f37);color:#fff">
      <div style="font-size:84px;font-weight:700;letter-spacing:-1px">Thanks for watching</div>
      <div style="margin-top:30px;font-size:34px;color:#d9f0e8">Filter · Rank · Map · Walking routes · Save · Compare</div>
      <div style="margin-top:64px;font-size:28px;color:#b4e0d1">Django · PostgreSQL · Leaflet · OneMap · data.gov.sg</div>
      <div style="margin-top:14px;font-size:26px;color:#84c9b3">github.com/CCCaLebF/FlatFinder</div></div>"""
    return CARD % {"nm": NM, "bg": "#1a3f37", "body": body}

def label_html(text):
    code, _, name = text.partition(" ")
    body = f"""<div style="position:absolute;left:36px;bottom:36px;display:flex;align-items:center;gap:16px;
      background:rgba(26,63,55,.92);color:#fff;border-radius:16px;padding:16px 26px;box-shadow:0 10px 30px rgba(0,0,0,.25)">
      <span style="font-weight:700;font-size:28px;color:#84c9b3">{code}</span>
      <span style="font-weight:600;font-size:28px">{name}</span></div>"""
    return CARD % {"nm": NM, "bg": "transparent", "body": body}

# 1 — Render cards and labels
with sync_playwright() as p:
    b = p.chromium.launch(); pg = b.new_page(viewport={"width": 1920, "height": 1080})
    for kind in ("title", "end"):
        pg.set_content(card_html(kind), wait_until="load"); pg.evaluate("document.fonts.ready"); pg.wait_for_timeout(300)
        pg.screenshot(path=f"{W}/{kind}.png")
    for s in meta["scenes"]:
        uc = narr[s["id"]]["uc"]
        if not uc.startswith("UC-"):
            continue
        pg.set_content(label_html(uc), wait_until="load"); pg.evaluate("document.fonts.ready"); pg.wait_for_timeout(100)
        pg.screenshot(path=f"{W}/label_{s['id']}.png", omit_background=True)
    b.close()

# 2 — Title and end cards as their own files (fades inside each file)
for kind, d in (("title", TITLE_S), ("end", END_S)):
    run(["ffmpeg", "-v", "error", "-y", "-framerate", "30", "-i", f"{W}/{kind}.png", "-vf",
         f"format=yuv420p,loop=-1:1,trim=duration={d},fade=t=in:st=0:d={FADE},fade=t=out:st={d - FADE}:d={FADE}",
         *ENC, f"{W}/{kind}.tmp.mp4"])
    os.replace(f"{W}/{kind}.tmp.mp4", f"{W}/{kind}.mp4")

# 3 — Recording with use-case labels (shown for ~4.7 s at the start of each scene), fading in/out from black
from PIL import Image
rec = os.path.join(args.rec_dir, "recording.mp4")
rec_len = float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                         "-of", "csv=p=0", rec]).decode())
inputs, chain, last = ["-i", rec], [], "[0:v]"
n = 1
SHOW = 4.7
for s in meta["scenes"]:
    lp = f"{W}/label_{s['id']}.png"
    if not os.path.exists(lp):
        continue
    im = Image.open(lp); box = im.getbbox()           # crop to the chip so the overlay stays small
    box = (box[0] - 24, box[1] - 24, box[2] + 24, box[3] + 24)
    im.crop(box).save(f"{W}/chip_{s['id']}.png")
    a = s["start"] + 0.3
    inputs += ["-loop", "1", "-framerate", "30", "-t", f"{SHOW:.2f}", "-i", f"{W}/chip_{s['id']}.png"]
    chain.append(f"[{n}:v]format=rgba,fade=t=in:st=0:d=0.35:alpha=1,fade=t=out:st={SHOW - 0.35:.2f}:d=0.35:alpha=1,"
                 f"setpts=PTS+{a:.3f}/TB[l{n}]")
    chain.append(f"{last}[l{n}]overlay={box[0]}:{box[1]}:eof_action=pass:repeatlast=0[v{n}]")
    last = f"[v{n}]"; n += 1
chain.append(f"{last}fade=t=in:st=0:d={FADE},fade=t=out:st={rec_len - FADE:.2f}:d={FADE},format=yuv420p[vout]")
run(["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex", ";".join(chain), "-map", "[vout]", *ENC,
     f"{W}/main.tmp.mp4"])
os.replace(f"{W}/main.tmp.mp4", f"{W}/main.mp4")

# 4 — Join video files
open(f"{W}/list.txt", "w").write("".join(f"file '{W}/{k}.mp4'\n" for k in ("title", "main", "end")))
run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", f"{W}/list.txt", "-c", "copy", f"{W}/video.mp4"])

# 5 — Voiceover track: each clip at scene start + LEAD, after the title card; subtitles alongside
clips, srt, total = [], [], TITLE_S + rec_len + END_S
for s in meta["scenes"]:
    wav = os.path.join(SP, "vo", f"{s['id']}.wav")
    at = TITLE_S + s["start"] + LEAD
    clips.append((wav, at))
    srt.append((at, at + dur(wav), narr[s["id"]]["text"]))
ins, fl = [], []
for i, (wav, at) in enumerate(clips):
    ins += ["-i", wav]
    fl.append(f"[{i}:a]aresample=48000,adelay={int(at * 1000)}|{int(at * 1000)}[a{i}]")
fl.append("".join(f"[a{i}]" for i in range(len(clips))) +
          f"amix=inputs={len(clips)}:normalize=0,apad,atrim=0:{total:.2f},loudnorm=I=-16:TP=-1.5:LRA=11[aout]")
run(["ffmpeg", "-v", "error", "-y", *ins, "-filter_complex", ";".join(fl), "-map", "[aout]", "-ar", "48000", f"{W}/voice.wav"])

# 6 — Final mux
tmp = args.out + ".part.mp4"
run(["ffmpeg", "-v", "error", "-y", "-i", f"{W}/video.mp4", "-i", f"{W}/voice.wav", "-map", "0:v", "-map", "1:a",
     "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", "-shortest", tmp])
os.replace(tmp, args.out)

def ts(t):
    h, m, s = int(t // 3600), int(t % 3600 // 60), t % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}".replace(".", ",")
with open(os.path.splitext(args.out)[0] + ".srt", "w", encoding="utf-8") as f:
    for i, (a, z, text) in enumerate(srt, 1):
        f.write(f"{i}\n{ts(a)} --> {ts(z)}\n{text}\n\n")
print(f"final: {args.out}  ({total:.1f}s)")
