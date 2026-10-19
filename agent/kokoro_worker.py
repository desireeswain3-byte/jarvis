"""Runs inside the voice venv. Keeps the Kokoro model loaded and turns lines of JSON into WAV bytes.
Protocol on stdout: the line READY once, then for each request either "OK <n>\\n" and n bytes of WAV, or "ERR <n>\\n" and n bytes of text."""
import io
import json
import sys
import wave
from pathlib import Path

out = sys.stdout.buffer
sys.stdout = sys.stderr   # anything a library prints must not corrupt the audio stream

import numpy as np  # noqa: E402
from kokoro_onnx import Kokoro  # noqa: E402

d = Path(sys.argv[1])
model = next((p for p in (d / "kokoro-v1.0.int8.onnx", d / "kokoro-v1.0.onnx") if p.exists()), None)
if model is None:
    sys.stderr.write("no model file in %s\n" % d)
    sys.exit(2)
k = Kokoro(str(model), str(d / "voices-v1.0.bin"))
out.write(b"READY\n")
out.flush()
for line in sys.stdin:
    try:
        req = json.loads(line)
        samples, sr = k.create(req["text"], voice=req.get("voice") or "bm_george", speed=float(req.get("speed") or 1.0), lang="en-gb")
        pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype("<i2").tobytes()
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(int(sr))
            w.writeframes(pcm)
        data = buf.getvalue()
        out.write(b"OK %d\n" % len(data) + data)
    except Exception as e:  # noqa: BLE001
        msg = ("%s: %s" % (type(e).__name__, e))[:300].encode("utf-8", "replace")
        out.write(b"ERR %d\n" % len(msg) + msg)
    out.flush()
