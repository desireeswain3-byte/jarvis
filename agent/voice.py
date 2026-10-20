"""ElevenLabs speech in and out. The API key lives here and never reaches the browser."""
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

API = os.environ.get("ELEVENLABS_BASE_URL", "https://api.elevenlabs.io").rstrip("/")  # override is for tests
MAX_SPEAK_CHARS = 1500
FISH_URL = os.environ.get("FISH_API_URL", "https://api.fish.audio").rstrip("/")  # override is for tests
# The voice Desi chose. Override with ELEVENLABS_VOICE_ID in .env.
DEFAULT_VOICE = "QYrOVogqhHWUzdZFXf0E"


class VoiceError(Exception):
    pass


ROOT = Path(__file__).resolve().parent.parent
KOKORO_VOICES = [("bm_george", "George"), ("bm_fable", "Fable"), ("bm_lewis", "Lewis"), ("bm_daniel", "Daniel")]   # British male
SAY = os.environ.get("JARVIS_SAY_BIN", "say")   # the Mac's built-in speech; the override is for tests
MAC_DEFAULT = "Daniel"                         # the British male voice every Mac ships with
MAC_OK_LOCALES = ("en_GB", "en_AU", "en_IE", "en_IN", "en_ZA", "en_US", "en_CA")
# Female and novelty voices are left out, since JARVIS is male and plain-spoken.
MAC_SKIP = {n.lower() for n in (
    "Samantha", "Karen", "Moira", "Tessa", "Fiona", "Kate", "Serena", "Martha", "Allison", "Ava", "Susan", "Victoria",
    "Zoe", "Nicky", "Flo", "Shelley", "Sandy", "Grandma", "Kathy", "Princess", "Agnes", "Joelle", "Catherine",
    "Albert", "Bad News", "Bahh", "Bells", "Boing", "Bubbles", "Cellos", "Deranged", "Good News", "Hysterical",
    "Jester", "Organ", "Pipe Organ", "Superstar", "Trinoids", "Whisper", "Wobble", "Zarvox", "Fred", "Junior", "Ralph")}


def key():
    return os.environ.get("ELEVENLABS_API_KEY", "").strip()


def available():
    return bool(key())


def fish_ready():
    """Fish Audio is used only when she has put both a key and a voice id in .env."""
    return bool(os.environ.get("FISH_API_KEY", "").strip()) and bool(re.fullmatch(r"[A-Za-z0-9]{16,64}", os.environ.get("FISH_VOICE_ID", "").strip()))


def _kpy():
    return Path(os.environ.get("KOKORO_PYTHON") or ROOT / ".venv-voice" / "bin" / "python")


def _kdir():
    return Path(os.environ.get("KOKORO_DIR") or ROOT / "voices")


def kokoro_ready():
    d = _kdir()
    return _kpy().exists() and (d / "voices-v1.0.bin").exists() and any((d / n).exists() for n in ("kokoro-v1.0.int8.onnx", "kokoro-v1.0.onnx"))


class _Soft(VoiceError):
    """The model refused one request but the process is fine, so it stays loaded."""


class _Worker:
    """One long-lived process that keeps the model loaded, so each reply costs only the speaking time."""
    lock = threading.Lock()
    proc = None

    @classmethod
    def _start(cls):
        cls.stop()
        script = str(Path(__file__).resolve().parent / "kokoro_worker.py")
        cls.proc = subprocess.Popen([str(_kpy()), script, str(_kdir())], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                    stderr=open(os.devnull, "wb"))
        box = {}
        t = threading.Thread(target=lambda: box.setdefault("l", cls.proc.stdout.readline()), daemon=True)
        t.start()
        t.join(120)   # the first load can take a while on an older Mac
        if box.get("l") != b"READY\n":
            cls.stop()
            raise VoiceError("The local voice did not start.")

    @classmethod
    def stop(cls):
        if cls.proc:
            try:
                cls.proc.kill()
            except OSError:
                pass
        cls.proc = None

    @classmethod
    def speak(cls, text, voice, speed):
        with cls.lock:
            last = "unknown"
            for _ in range(2):   # one retry with a fresh process if the first one died
                try:
                    if cls.proc is None or cls.proc.poll() is not None:
                        cls._start()
                    cls.proc.stdin.write((json.dumps({"text": text, "voice": voice, "speed": speed}) + "\n").encode())
                    cls.proc.stdin.flush()
                    head = cls.proc.stdout.readline().split()
                    if len(head) != 2:
                        raise VoiceError("The local voice stopped.")
                    body = cls.proc.stdout.read(int(head[1]))
                    if head[0] == b"OK" and len(body) == int(head[1]):
                        return body
                    raise _Soft("The local voice failed: %s" % body.decode("utf-8", "replace"))
                except _Soft as e:
                    raise VoiceError(str(e))
                except (OSError, ValueError, VoiceError) as e:
                    last = str(e)
                    cls.stop()
            raise VoiceError(last)


PIPER_MODEL = "en_GB-alan-medium"   # free British male voice


def _ppy():
    return Path(os.environ.get("PIPER_PYTHON") or ROOT / ".venv-piper" / "bin" / "python")


def piper_ready():
    m = _kdir() / (PIPER_MODEL + ".onnx")
    return _ppy().exists() and m.exists() and m.with_suffix(".onnx.json").exists()


def _speak_piper(text):
    model = _kdir() / (PIPER_MODEL + ".onnx")
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "speech.wav")
        try:
            r = subprocess.run([str(_ppy()), "-m", "piper", "-m", str(model), "-f", out], input=text[:MAX_SPEAK_CHARS],
                               capture_output=True, text=True, timeout=90)
        except (OSError, subprocess.SubprocessError) as e:
            raise VoiceError("The Piper voice failed: %s" % e)
        if r.returncode != 0 or not os.path.exists(out) or os.path.getsize(out) < 100:
            raise VoiceError("The Piper voice failed. %s" % (r.stderr or "")[-160:].strip())
        with open(out, "rb") as f:
            return f.read()


def _kokoro_names():
    return {v for v, _ in KOKORO_VOICES}


def speed_supported():
    """Engines that can speak faster or slower themselves, so the page can raise the pitch without rushing the words."""
    return engine() in ("kokoro", "mac", "fish")


def _speak_fish(text, speed=None):
    body = {"text": text[:MAX_SPEAK_CHARS], "reference_id": os.environ.get("FISH_VOICE_ID", "").strip(), "format": "mp3", "latency": os.environ.get("FISH_LATENCY", "balanced").strip() or "balanced"}
    if speed and 0.5 <= float(speed) <= 2.0 and abs(float(speed) - 1.0) > 0.01:
        body["prosody"] = {"speed": float(speed)}
    req = urllib.request.Request(
        FISH_URL + "/v1/tts", data=json.dumps(body).encode(), method="POST",
        headers={"Authorization": "Bearer " + os.environ.get("FISH_API_KEY", "").strip(), "Content-Type": "application/json",
                 "model": os.environ.get("FISH_MODEL", "s2.1-pro-free").strip()})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            audio = r.read()
    except urllib.error.HTTPError as e:
        raise VoiceError("Fish Audio returned %d. %s" % (e.code, e.read()[:160].decode("utf-8", "replace")))
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise VoiceError("Could not reach Fish Audio: %s" % e)
    if len(audio) < 200:
        raise VoiceError("Fish Audio sent back no sound.")
    return audio


def _speak_local(text, voice_id, speed):
    """The free voices on her own computer. Used when Fish Audio is out of credit or offline."""
    for name, ready, fn in (("kokoro", kokoro_ready, lambda: _speak_kokoro(text, "", speed)), ("piper", piper_ready, lambda: _speak_piper(text)),
                            ("mac", mac_ok, lambda: _speak_mac(text, "", speed))):
        if ready():
            try:
                return fn(), "audio/wav"
            except VoiceError:
                continue
    raise VoiceError("Fish Audio failed and no local voice is set up.")


def _speak_kokoro(text, voice_id, speed=None):
    voice = voice_id if voice_id in _kokoro_names() else default_voice()
    if speed is None:
        try:
            speed = float(os.environ.get("KOKORO_SPEED", "1.0"))
        except ValueError:
            speed = 1.0
    speed = max(0.6, min(1.6, speed))
    return _Worker.speak(text[:MAX_SPEAK_CHARS], voice, speed)


def mac_ok():
    return bool(shutil.which(SAY))


def engine():
    """Which voice speaks. VOICE_ENGINE=mac or eleven forces one. Otherwise the Mac's own voice is used when it is
    there (free, offline, no key), and ElevenLabs only when it is not."""
    want = os.environ.get("VOICE_ENGINE", "auto").strip().lower()
    if want == "eleven":
        return "eleven" if available() else None
    if want == "mac":
        return "mac" if mac_ok() else None
    if want == "fish":
        return "fish" if fish_ready() else None
    if want == "kokoro":
        return "kokoro" if kokoro_ready() else None
    if want == "piper":
        return "piper" if piper_ready() else None
    if fish_ready():
        return "fish"
    if kokoro_ready():
        return "kokoro"
    if piper_ready():
        return "piper"
    if mac_ok():
        return "mac"
    return "eleven" if available() else None


def tts_available():
    return engine() is not None


def _open(req, timeout=60):
    try:
        return urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        detail = e.read()[:200].decode("utf-8", "replace")
        raise VoiceError("ElevenLabs returned %d. %s" % (e.code, detail))
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise VoiceError("Could not reach ElevenLabs: %s" % e)


def _num(name, default):
    try:
        return max(0.0, min(1.0, float(os.environ.get(name, default))))
    except ValueError:
        return default


def default_voice():
    if engine() == "fish":
        return os.environ.get("FISH_VOICE_ID", "")
    if engine() == "piper":
        return PIPER_MODEL
    if engine() == "kokoro":
        v = os.environ.get("KOKORO_VOICE", "bm_george").strip()
        return v if v in _kokoro_names() else "bm_george"
    if engine() == "mac":
        return os.environ.get("MAC_VOICE", MAC_DEFAULT).strip() or MAC_DEFAULT
    return os.environ.get("ELEVENLABS_VOICE_ID", DEFAULT_VOICE).strip() or DEFAULT_VOICE


def _mac_voices():
    try:
        r = subprocess.run([SAY, "-v", "?"], capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError) as e:
        raise VoiceError("Could not list the Mac voices: %s" % e)
    out = []
    for line in r.stdout.splitlines():
        m = re.match(r"^(.+?)\s{2,}([a-z]{2}_[A-Z]{2})\s+#", line)
        if not m:
            continue
        name, loc = m.group(1).strip(), m.group(2)
        base = re.sub(r"\s*\(.*\)\s*$", "", name).strip().lower()
        if loc not in MAC_OK_LOCALES or base in MAC_SKIP:
            continue
        out.append({"id": name, "name": name, "accent": {"en_GB": "british", "en_AU": "australian", "en_IE": "irish", "en_IN": "indian", "en_ZA": "south african", "en_US": "american", "en_CA": "canadian"}[loc],
                    "gender": "male", "age": "", "description": "built in to this Mac", "preview": ""})
    out.sort(key=lambda v: (0 if v["accent"] == "british" else 1, 0 if v["name"].lower().startswith("daniel") else 1, v["name"].lower()))
    return out


def _speak_mac(text, voice_id, speed=None):
    voices = _mac_voices()
    names = {v["id"] for v in voices}
    voice = voice_id if voice_id in names else default_voice()
    if voice not in names and voices:
        voice = voices[0]["id"]
    try:
        rate_n = float(os.environ.get("MAC_VOICE_RATE", "180"))
    except ValueError:
        rate_n = 180.0
    rate = str(int(rate_n * max(0.6, min(1.6, speed or 1.0))))
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "speech.wav")
        try:
            r = subprocess.run([SAY, "-v", voice, "-r", rate, "-o", out, "--file-format=WAVE", "--data-format=LEI16@22050"],
                               input=text[:MAX_SPEAK_CHARS], capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.SubprocessError) as e:
            raise VoiceError("The Mac voice failed: %s" % e)
        if r.returncode != 0 or not os.path.exists(out):
            raise VoiceError("The Mac voice failed. %s" % (r.stderr or "")[:160].strip())
        with open(out, "rb") as f:
            return f.read()


def list_voices():
    """Voices to audition, British ones first."""
    if engine() == "fish":
        return [{"id": os.environ.get("FISH_VOICE_ID", ""), "name": "Fish Audio voice", "accent": "", "gender": "male", "age": "", "description": "your Fish Audio voice", "preview": ""}]
    if engine() == "piper":
        return [{"id": PIPER_MODEL, "name": "Alan", "accent": "british", "gender": "male", "age": "", "description": "local Piper voice", "preview": ""}]
    if engine() == "kokoro":
        return [{"id": v, "name": n, "accent": "british", "gender": "male", "age": "", "description": "local neural voice", "preview": ""} for v, n in KOKORO_VOICES]
    if engine() == "mac":
        return _mac_voices()
    if not available():
        raise VoiceError("ELEVENLABS_API_KEY is not set in .env, so there are no voices to list.")
    req = urllib.request.Request(API + "/v1/voices", headers={"xi-api-key": key(), "Accept": "application/json"})
    with _open(req, timeout=30) as r:
        try:
            raw = json.loads(r.read().decode("utf-8")).get("voices") or []
        except ValueError:
            raise VoiceError("ElevenLabs returned a voice list that could not be read.")
    out = []
    for v in raw:
        lab = v.get("labels") or {}
        out.append({
            "id": v.get("voice_id", ""), "name": v.get("name", "?"),
            "accent": (lab.get("accent") or "").lower(), "gender": (lab.get("gender") or "").lower(),
            "age": (lab.get("age") or "").lower(), "description": (lab.get("descriptive") or lab.get("description") or "").lower(),
            "preview": v.get("preview_url") or "",
        })
    out = [v for v in out if v["id"] and v["gender"] != "female"]   # JARVIS is male
    out.sort(key=lambda v: (0 if v["accent"] == "british" else 1 if v["accent"] else 2, v["gender"] != "male", v["name"].lower()))
    return out


def speak(text, voice_id=None, speed=None):
    """Text in, (audio bytes, content type) out. voice_id overrides the one in .env for this call."""
    if engine() == "fish":
        try:
            return _speak_fish(text, speed), "audio/mpeg"
        except VoiceError:
            return _speak_local(text, voice_id, speed)   # out of credit or offline: the free voice covers it, JARVIS never goes silent
    if engine() == "piper":
        try:
            return _speak_piper(text), "audio/wav"
        except VoiceError:
            if not mac_ok():
                raise
            return _speak_mac(text, ""), "audio/wav"
    if engine() == "kokoro":
        try:
            return _speak_kokoro(text, voice_id or "", speed), "audio/wav"
        except VoiceError:
            if not mac_ok():
                raise
            return _speak_mac(text, "", speed), "audio/wav"   # the local voice hiccuped, so the Mac's own voice covers this reply
    if engine() == "mac":
        return _speak_mac(text, voice_id or "", speed), "audio/wav"
    if not available():
        raise VoiceError("Voice output is off: this is not a Mac and there is no ELEVENLABS_API_KEY in .env.")
    voice = voice_id if voice_id and re.fullmatch(r"[A-Za-z0-9]{8,40}", voice_id) else default_voice()
    model = os.environ.get("ELEVENLABS_TTS_MODEL", "eleven_multilingual_v2").strip()
    # Lower stability and a little style push a voice toward its accent and character.
    settings = {"stability": _num("ELEVENLABS_STABILITY", 0.35), "similarity_boost": _num("ELEVENLABS_SIMILARITY", 0.8),
                "style": _num("ELEVENLABS_STYLE", 0.5), "use_speaker_boost": True}
    body = json.dumps({"text": text[:MAX_SPEAK_CHARS], "model_id": model, "voice_settings": settings}).encode()
    req = urllib.request.Request(
        "%s/v1/text-to-speech/%s?output_format=mp3_44100_128" % (API, voice), data=body, method="POST",
        headers={"xi-api-key": key(), "Content-Type": "application/json", "Accept": "audio/mpeg"})
    with _open(req) as r:
        return r.read(), "audio/mpeg"


def transcribe(audio, content_type):
    """Audio bytes in, transcript text out, via Scribe."""
    if not available():
        raise VoiceError("ELEVENLABS_API_KEY is not set in .env, so the transcriber is off.")
    if not audio:
        raise VoiceError("Empty recording.")
    boundary = "----jarvis" + uuid.uuid4().hex
    ct = (content_type or "audio/webm").split(";")[0]
    ext = {"audio/mp4": "mp4", "audio/ogg": "ogg", "audio/wav": "wav", "audio/mpeg": "mp3"}.get(ct, "webm")
    parts = [
        ("--%s\r\nContent-Disposition: form-data; name=\"model_id\"\r\n\r\nscribe_v1\r\n" % boundary).encode(),
        ("--%s\r\nContent-Disposition: form-data; name=\"file\"; filename=\"speech.%s\"\r\nContent-Type: %s\r\n\r\n" % (boundary, ext, ct)).encode(),
        audio,
        ("\r\n--%s--\r\n" % boundary).encode(),
    ]
    req = urllib.request.Request(
        API + "/v1/speech-to-text", data=b"".join(parts), method="POST",
        headers={"xi-api-key": key(), "Content-Type": "multipart/form-data; boundary=" + boundary})
    with _open(req, timeout=120) as r:
        try:
            return (json.loads(r.read().decode("utf-8")).get("text") or "").strip()
        except ValueError:
            raise VoiceError("Transcriber returned something unreadable.")
