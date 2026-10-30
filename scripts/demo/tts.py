"""Voice every scene in narration.json with Kokoro (open-source TTS) and record each clip's length.
usage: python tts.py [voice] [speed]          (default: af_heart 1.0)
writes vo/<scene_id>.wav and vo/durations.json next to this script.
"""
import json, os, sys, urllib.request
import soundfile as sf
from kokoro_onnx import Kokoro

HERE = os.path.dirname(os.path.abspath(__file__))
MODELS = os.path.join(HERE, "tts")
REL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/"
os.makedirs(MODELS, exist_ok=True)
for name in ("kokoro-v1.0.onnx", "voices-v1.0.bin"):
    path = os.path.join(MODELS, name)
    if not os.path.exists(path):
        print("downloading", name); urllib.request.urlretrieve(REL + name, path)

voice = sys.argv[1] if len(sys.argv) > 1 else "af_heart"
speed = float(sys.argv[2]) if len(sys.argv) > 2 else 1.0
only = set(sys.argv[3].split(",")) if len(sys.argv) > 3 else None   # optional: re-voice some scenes only
k = Kokoro(os.path.join(MODELS, "kokoro-v1.0.onnx"), os.path.join(MODELS, "voices-v1.0.bin"))
vo = os.path.join(HERE, "vo"); os.makedirs(vo, exist_ok=True)
dfile = os.path.join(vo, "durations.json")
out = json.load(open(dfile)) if os.path.exists(dfile) else {}
for s in json.load(open(os.path.join(HERE, "narration.json"))):
    if only and s["id"] not in only:
        continue
    a, sr = k.create(s["text"], voice=voice, speed=speed, lang="en-us")
    sf.write(os.path.join(vo, s["id"] + ".wav"), a, sr)
    out[s["id"]] = round(len(a) / sr, 2)
    print(s["id"], out[s["id"]])
json.dump(out, open(dfile, "w"), indent=1)
print("total", round(sum(out.values()), 1))
