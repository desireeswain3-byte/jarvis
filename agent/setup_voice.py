#!/usr/bin/env python3
"""One-time setup for JARVIS's free local voice (Kokoro, British male). Run: python3 ~/jarvis/agent/setup_voice.py

Makes a private Python environment inside the jarvis folder, installs the voice engine there, downloads the voice
model (about 115 MB) and plays a sample. Nothing outside the jarvis folder is changed. If anything fails, JARVIS
keeps the voice it already has."""
import io
import os
import platform
import re
import shutil
import subprocess
import sys
import time
import urllib.request
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PIPER = "--piper" in sys.argv
VENV = ROOT / (".venv-piper" if PIPER else ".venv-voice")
VOICES = ROOT / "voices"
BASE = os.environ.get("KOKORO_URL_BASE", "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0").rstrip("/")
FILES = ["kokoro-v1.0.int8.onnx", "voices-v1.0.bin"]
PIPER_BASE = os.environ.get("PIPER_URL_BASE", "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_GB/alan/medium").rstrip("/")
PIPER_FILES = ["en_GB-alan-medium.onnx", "en_GB-alan-medium.onnx.json"]
sys.path.insert(0, str(Path(__file__).resolve().parent))


def say(msg=""):
    print(msg, flush=True)


MIN = (3, 10)   # the voice engine needs Python 3.10 or newer; the one built into macOS is 3.9


def py_version(exe):
    try:
        out = subprocess.run([str(exe), "-c", "import sys;print('%d.%d' % sys.version_info[:2])"], capture_output=True, text=True, timeout=20).stdout.strip()
        return tuple(int(x) for x in out.split("."))
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def find_python():
    """The newest Python 3.10 or later already on this Mac, if any."""
    best = None
    for name in ("python3.13", "python3.12", "python3.11", "python3.10", "python3"):
        exe = shutil.which(name)
        ver = py_version(exe) if exe else None
        if ver and ver >= MIN and (best is None or ver > best[0]):
            best = (ver, exe)
    return best


def find_uv():
    for cand in (shutil.which("uv"), str(Path.home() / ".local/bin/uv"), str(Path.home() / ".cargo/bin/uv")):
        if cand and Path(cand).exists():
            return cand
    return None


def ensure_uv():
    """uv is one small program that can fetch a modern Python into the home folder, with no admin password."""
    uv = find_uv()
    if uv:
        return uv
    say("   This Mac's Python is too old, so I am getting a modern one with a small helper called uv (about 70 MB, kept in your home folder).")
    r = subprocess.run("curl -LsSf https://astral.sh/uv/install.sh | sh", shell=True, capture_output=True, text=True)
    uv = find_uv()
    if not uv:
        say("I could not install the helper: " + (r.stderr or r.stdout or "")[-300:])
    return uv


def step_env():
    py = VENV / "bin" / "python"
    if py.exists():
        ver = py_version(py)
        if ver and ver >= MIN:
            return py, find_uv() if (VENV / ".uv").exists() else None
        shutil.rmtree(VENV, ignore_errors=True)   # an old private folder from an earlier try
    found = find_python()
    if found:
        say("1 of 4. Making a private folder for the voice engine (Python %d.%d)..." % found[0])
        r = subprocess.run([found[1], "-m", "venv", str(VENV)], capture_output=True, text=True)
        if r.returncode != 0 or not py.exists():
            say("That did not work: " + (r.stderr or "")[-300:])
            return None, None
        return py, None
    uv = ensure_uv()
    if not uv:
        return None, None
    say("1 of 4. Getting Python 3.12 and making a private folder for the voice engine (a minute or two)...")
    r = subprocess.run([uv, "venv", "--python", "3.12", str(VENV)], capture_output=True, text=True)
    if r.returncode != 0 or not py.exists():
        say("That did not work: " + (r.stderr or r.stdout or "")[-400:])
        return None, None
    (VENV / ".uv").write_text("1")
    return py, uv


def installer(py, uv):
    return [uv, "pip", "install", "--python", str(py)] if uv else [str(py), "-m", "pip", "install", "--quiet"]


def step_pip(py, uv):
    if os.environ.get("JARVIS_VOICE_SKIP_PIP") == "1":
        return True
    say("2 of 4. Installing the voice engine. This takes a few minutes and prints little until it finishes...")
    base = installer(py, uv)
    if PIPER:
        r = subprocess.run(base + ["piper-tts"], capture_output=True, text=True)
        if r.returncode != 0:
            say("The install did not work. The last lines it printed:")
            say((r.stderr or r.stdout or "")[-900:])
            return False
        return True
    r = subprocess.run(base + ["kokoro-onnx", "numpy"], capture_output=True, text=True)
    if r.returncode != 0 and platform.system() == "Darwin" and platform.machine() == "x86_64":
        # Intel Macs: newer onnxruntime builds are Apple chip only, so use the last one that has an Intel build.
        say("   Trying the version that fits an Intel Mac...")
        r = subprocess.run(base + ["onnxruntime<1.20", "numpy", "colorlog", "espeakng-loader", "phonemizer-fork"], capture_output=True, text=True)
        if r.returncode == 0:
            r = subprocess.run(base + ["--no-deps", "kokoro-onnx"], capture_output=True, text=True)
    if r.returncode != 0:
        say("The install did not work. The last lines it printed:")
        say((r.stderr or r.stdout or "")[-900:])
        return False
    return True


def download(name):
    dest = VOICES / name
    if dest.exists() and dest.stat().st_size > (1_000 if name.endswith(".json") else 1_000_000):
        return True
    VOICES.mkdir(exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    try:
        with urllib.request.urlopen(urllib.request.Request((PIPER_BASE if PIPER else BASE) + "/" + name, headers={"User-Agent": "jarvis-local"}), timeout=60) as r, open(tmp, "wb") as f:
            total = int(r.headers.get("Content-Length") or 0)
            done, last = 0, -1
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                if total and done * 10 // total != last:
                    last = done * 10 // total
                    say("   %s: %d%%" % (name, last * 10))
        os.replace(tmp, dest)
        return True
    except (OSError, ValueError) as e:
        say("The download of %s did not work: %s" % (name, e))
        return False


def step_models():
    say("3 of 4. Downloading the voice (about %s)..." % ("65 MB" if PIPER else "115 MB"))
    return all(download(n) for n in (PIPER_FILES if PIPER else FILES))


def step_test():
    say("4 of 4. Trying it out...")
    os.environ["KOKORO_PYTHON"], os.environ["PIPER_PYTHON"], os.environ["KOKORO_DIR"] = str(VENV / "bin" / "python"), str(VENV / "bin" / "python"), str(VOICES)
    import voice
    if not (voice.piper_ready() if PIPER else voice.kokoro_ready()):
        say("The files are not all there.")
        return False
    text = "Good evening. All systems are running, and I have a few things for you to look at."
    try:
        t0 = time.time()
        one = (lambda: voice._speak_piper(text)) if PIPER else (lambda: voice.speak(text, "bm_george")[0])
        one()                                      # first call loads the model
        t1 = time.time()
        audio = one()                              # second call is what a normal reply costs
        t2 = time.time()
    except voice.VoiceError as e:
        say("The voice did not start: %s" % e)
        return False
    w = wave.open(io.BytesIO(audio))
    secs = w.getnframes() / float(w.getframerate())
    sample = VOICES / "sample.wav"
    sample.write_bytes(audio)
    say("   Loading took %.0f seconds once. A reply of %.0f seconds of speech takes about %.0f seconds to make." % (t1 - t0, secs, t2 - t1))
    if shutil.which("afplay"):
        say("   Playing it now.")
        subprocess.run(["afplay", str(sample)])
    if not PIPER:
        voice._Worker.stop()
    return True


def main():
    say("Setting up JARVIS's free local voice (%s). Nothing leaves this Mac and no key is needed." % ("Piper, Alan" if PIPER else "Kokoro"))
    say()
    py, uv = step_env()
    if not py or not step_pip(py, uv) or not step_models() or not step_test():
        say()
        say("Setup stopped. JARVIS keeps using his current voice. Take a photo of this window and send it to Claude.")
        return 1
    say()
    say("Done. The local voice is ready.")
    plist = Path.home() / "Library/LaunchAgents/com.jarvis.plist"
    if plist.exists() and os.environ.get("JARVIS_NO_RESTART") != "1":
        subprocess.run(["launchctl", "unload", str(plist)], capture_output=True)
        subprocess.run(["launchctl", "load", str(plist)], capture_output=True)
        say("JARVIS restarted. Reload the page in Chrome (Command, Shift and R).")
    else:
        say("Restart JARVIS, then reload the page.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
