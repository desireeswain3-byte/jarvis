#!/usr/bin/env python3
"""JARVIS server. Standard library only. Run: python3 agent/main.py"""
import json
import mimetypes
import subprocess
import os
import sys
import time
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent.parent
UI = ROOT / "ui"


def load_env():
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


load_env()  # must run before data.py is imported

import data  # noqa: E402
import llm  # noqa: E402
import memory  # noqa: E402
import broker  # noqa: E402
import tools
import watch  # noqa: E402
import voice  # noqa: E402
from vault import Vault  # noqa: E402

LOCAL_HOSTS = {"localhost", "127.0.0.1", "[::1]"}
MAX_TURNS = 10


BUILD = 33   # shown in the top bar so you can see which update is running
ORB = {"state": "idle", "caption": "", "move": "", "move_seq": 0, "seen": 0.0}   # what the see-through overlay shows


class State:
    def __init__(self):
        self.lock = threading.Lock()
        self.history = []
        self.last_model_error = None
        memory.MEM.mkdir(exist_ok=True)
        self.vault = Vault(data.roots() + [("memory", memory.MEM)])
        self.toolbox = tools.Toolbox(self.vault)


S = None


def host_ok(host_header):
    host = (host_header or "").split(":")[0] if not (host_header or "").startswith("[") else "[::1]"
    return host in LOCAL_HOSTS


class Handler(BaseHTTPRequestHandler):
    server_version = "JARVIS"

    def log_message(self, fmt, *args):
        pass

    # ---------- helpers ----------
    def send_json(self, code, obj):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def read_body(self, limit=25 * 1024 * 1024):
        n = int(self.headers.get("Content-Length") or 0)
        if n > limit:
            raise ValueError("Body too large.")
        return self.rfile.read(n)

    def guard(self):
        if not host_ok(self.headers.get("Host")):
            self.send_json(403, {"error": "Local access only."})
            return False
        origin = self.headers.get("Origin")
        if origin and not host_ok(urlparse(origin).netloc):
            self.send_json(403, {"error": "Cross-site requests are blocked."})
            return False
        return True

    # ---------- GET ----------
    def do_GET(self):
        if not self.guard():
            return
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if u.path == "/api/status":
            return self.send_json(200, self.status())
        if u.path == "/api/orb":
            ORB["seen"] = time.time() if (q.get("overlay") or [""])[0] == "1" else ORB["seen"]
            out = dict(ORB)
            out["overlay"] = time.time() - ORB["seen"] < 4
            return self.send_json(200, out)
        if u.path == "/api/market":
            import watch as _w
            if not broker.configured():
                return self.send_json(200, {"ok": False, "error": "Add your Alpaca keys to .env to see live prices (the free practice keys work).", "rows": [], "open": _w.market_open()})
            try:
                snaps = broker.snapshots(["SPY", "QQQ", "DIA", "IWM"] + _w.WATCHLIST)
            except broker.BrokerError as e:
                return self.send_json(200, {"ok": False, "error": str(e), "rows": [], "open": _w.market_open()})
            rows = [{"symbol": k, "price": v["price"], "pct": v["pct"], "high": v["high"], "low": v["low"], "vol": v["vol"]} for k, v in snaps.items()]
            return self.send_json(200, {"ok": True, "rows": rows, "open": _w.market_open(), "index": ["SPY", "QQQ", "DIA", "IWM"]})
        if u.path == "/api/events":
            try: n = int((q.get("since") or ["0"])[0])
            except ValueError: n = 0
            evs, last = watch.since(n)
            return self.send_json(200, {"events": evs, "last": last})
        if u.path == "/api/graph":
            return self.send_json(200, S.vault.graph())
        if u.path == "/api/note":
            n = S.vault.note((q.get("id") or [""])[0])
            if n:
                n["flag"] = bool(tools.INJECTION.search(n["text"]))
            return self.send_json(200 if n else 404, n or {"error": "No such note."})
        if u.path == "/api/voices":
            try:
                return self.send_json(200, {"voices": voice.list_voices(), "default": voice.default_voice()})
            except voice.VoiceError as e:
                return self.send_json(503, {"error": str(e)})
        if u.path == "/api/memory":
            return self.send_json(200, {"files": memory.listing()})
        if u.path.startswith("/api/"):
            return self.send_json(404, {"error": "Not found."})
        self.static(u.path)

    def static(self, path):
        rel = "index.html" if path in ("", "/") else path.lstrip("/")
        f = (UI / rel).resolve()
        if UI.resolve() not in f.parents or not f.is_file():
            self.send_response(404)
            self.end_headers()
            return
        body = f.read_bytes()
        ctype = mimetypes.guess_type(str(f))[0] or "application/octet-stream"
        if f.suffix in (".html", ".js", ".css"):
            ctype += "; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def status(self):
        return {
            "build": BUILD,
            "trading": {"mode": (broker.mode() if broker.configured() else "demo"), "guard": __import__("watch").guard_enabled()},
            "demo": data.is_demo(),
            "problems": data.problems(),
            "model": {"available": llm.available(), "name": llm.model_name(), "error": S.last_model_error},
            "voice": {"tts": voice.tts_available(), "stt": voice.available(), "engine": voice.engine() or "off"},
            "vault": S.vault.stats(),
        }

    def wiring(self):
        """Live facts about how this JARVIS is set up, given to the model so it can describe itself truthfully."""
        return {
            "model": llm.model_name(), "model_on": llm.available(),
            "voice_output": {"piper": "a local Piper voice (Alan, British male), free and offline", "kokoro": "a local neural voice (Kokoro, British male), free and offline", "mac": "the Mac's own built-in voice, free and offline", "fish": "Fish Audio (cloud voice, free voice as backup)", "eleven": "ElevenLabs", None: "off"}[voice.engine()],
            "listening": "ElevenLabs transcription" if voice.available() else "typing only, no transcriber",
            "broker": ("%s account" % broker.mode()) if broker.configured() else "not connected",
            "data": "demo data" if data.is_demo() else "real data",
            "notes": S.vault.stats() if hasattr(S.vault, "stats") else {},
        }

    # ---------- POST ----------
    def do_POST(self):
        if not self.guard():
            return
        path = urlparse(self.path).path
        try:
            raw = self.read_body()
        except ValueError as e:
            return self.send_json(413, {"error": str(e)})
        try:
            if path == "/api/ask":
                return self.api_ask(json.loads(raw or b"{}"))
            if path == "/api/tool":
                return self.api_tool(json.loads(raw or b"{}"))
            if path == "/api/update":
                # Pull the newest JARVIS from GitHub. Needs a header a random website cannot send.
                if self.headers.get("X-Jarvis") != "1":
                    return self.send_json(403, {"ok": False, "error": "not allowed"})
                return self.send_json(200, run_update())
            if path == "/api/restart":
                self.send_json(200, {"ok": True})
                threading.Timer(0.5, lambda: os.execv(sys.executable, [sys.executable] + sys.argv)).start()
                return
            if path == "/api/orb":
                body = json.loads(raw or b"{}")
                if str(body.get("state", "")) in ("idle", "listening", "thinking", "speaking"):
                    ORB["state"] = body["state"]
                if "caption" in body:
                    ORB["caption"] = str(body["caption"])[:300]
                mv = str(body.get("move", ""))[:20]
                if mv in ("left", "right", "top", "bottom", "center", "top-left", "top-right", "bottom-left", "bottom-right", "home"):
                    ORB["move"] = mv
                    ORB["move_seq"] += 1
                return self.send_json(200, {"ok": True})
            if path == "/api/speak":
                return self.api_speak(json.loads(raw or b"{}"))
            if path == "/api/listen":
                return self.api_listen(raw)
            if path == "/api/broker/confirm":
                return self.api_confirm(json.loads(raw or b"{}"))
            if path == "/api/broker/cancel":
                return self.send_json(200, {"ok": S.toolbox.cancel_order(json.loads(raw or b"{}").get("id", ""))})
            if path == "/api/reset":
                with S.lock:
                    S.history.clear()
                return self.send_json(200, {"ok": True})
        except (ValueError, KeyError) as e:
            return self.send_json(400, {"error": "Bad request: %s" % e})
        self.send_json(404, {"error": "Not found."})

    def api_ask(self, body):
        text = str(body.get("text", "")).strip()[:2000]
        if not text:
            return self.send_json(400, {"error": "Empty question."})
        screen = body.get("screen") if isinstance(body.get("screen"), dict) else None
        image = body.get("image") if isinstance(body.get("image"), str) else None
        if image and (not image.startswith("data:image/jpeg;base64,") or len(image) > 3_000_000):
            image = None
        with S.lock:
            try:
                if not llm.available():
                    raise llm.ModelUnavailable("ANTHROPIC_API_KEY is not set in .env")
                out = llm.converse(text, S.history, S.toolbox, screen=screen, image=image, wiring=self.wiring())
                out["mode"] = "model"
                out["saw"] = {"screen": bool(screen), "image_kb": (len(image) * 3 // 4 // 1024) if image else 0}
                S.last_model_error = None
            except llm.ModelUnavailable as e:
                S.last_model_error = str(e)
                out = llm.offline(text, S.history, S.toolbox)
                out["mode"] = "offline"
                out["saw"] = {"screen": False, "image_kb": 0}
                out["error"] = str(e)
            S.history.append({"role": "user", "content": text})
            S.history.append({"role": "assistant", "content": out["reply"] or "(no reply)"})
            del S.history[:-MAX_TURNS * 2]
        self.send_json(200, out)

    def api_tool(self, body):
        name = body.get("name")
        if name not in ("brief_me", "plan_day", "read_inbox", "trading", "wellness"):
            return self.send_json(400, {"error": "Unknown tool."})
        out = S.toolbox.run(name, {"action": "show"} if name == "trading" else {"action": "quote"} if name == "wellness" else {})
        self.send_json(200, {"say": out["say"], "card": out["card"], "actions": out.get("actions", [])})

    def api_confirm(self, body):
        with S.lock:
            try:
                out = S.toolbox.confirm_order(body.get("id", ""))
            except broker.BrokerError as e:
                return self.send_json(409, {"error": str(e)})
        self.send_json(200, {"say": out["say"], "card": S.toolbox._trading_card()})

    def api_speak(self, body):
        text = str(body.get("text", "")).strip()
        if not text:
            return self.send_json(400, {"error": "Nothing to say."})
        try:
            try:
                speed = float(body.get("speed")) if body.get("speed") else None
            except (TypeError, ValueError):
                speed = None
            audio, ctype = voice.speak(text, str(body.get("voice") or ""), speed)
        except voice.VoiceError as e:
            return self.send_json(503, {"error": str(e)})
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("X-Speed-Applied", "1" if voice.speed_supported() else "0")
        self.send_header("Content-Length", str(len(audio)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(audio)

    def api_listen(self, raw):
        try:
            text = voice.transcribe(raw, self.headers.get("Content-Type", "audio/webm"))
        except voice.VoiceError as e:
            return self.send_json(503, {"error": str(e)})
        self.send_json(200, {"text": text})


def run_update():
    """git fetch and reset to the newest version. Her private files are untracked, so they are never touched."""
    if not (ROOT / ".git").exists():
        return {"ok": False, "message": "This folder is not connected to GitHub yet."}
    def git(*a):
        return subprocess.run(["git"] + list(a), cwd=str(ROOT), capture_output=True, text=True, timeout=90)
    try:
        before = git("rev-parse", "--short", "HEAD").stdout.strip()
        f = git("fetch", "-q", "origin")
        if f.returncode != 0:
            return {"ok": False, "message": "Could not reach GitHub. Check the internet and try again.", "detail": f.stderr.strip()[-300:]}
        r = git("reset", "-q", "--hard", "origin/main")
        if r.returncode != 0:
            return {"ok": False, "message": "The update did not apply.", "detail": r.stderr.strip()[-300:]}
        after = git("rev-parse", "--short", "HEAD").stdout.strip()
        return {"ok": True, "changed": before != after, "from": before, "to": after,
                "message": "Already on the newest version." if before == after else "Updated. JARVIS is restarting."}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "message": "The update failed.", "detail": str(e)[:200]}


def _code_stamp():
    """Newest change time among the program files. When an update lands, this moves."""
    try:
        return max(f.stat().st_mtime for f in Path(__file__).parent.glob("*.py"))
    except (OSError, ValueError):
        return 0.0


def _auto_restart():
    """If the program files change on disk (an update was unzipped), start over by itself so the new code runs."""
    first = _code_stamp()
    while True:
        time.sleep(3)
        now = _code_stamp()
        if now > first:
            time.sleep(3)                       # let the unzip finish
            if _code_stamp() == now:
                print("Update detected, restarting.", flush=True)
                try:
                    os.execv(sys.executable, [sys.executable] + sys.argv)
                except OSError as e:
                    print("could not restart:", e, flush=True)
                    first = now


def main():
    global S
    S = State()
    port = int(os.environ.get("JARVIS_PORT", "8765"))
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = "http://localhost:%d" % port
    watch.Watcher(S.toolbox).start()
    if os.environ.get("JARVIS_NO_AUTORESTART") != "1":
        threading.Thread(target=_auto_restart, daemon=True).start()
    st = S.vault.stats()
    print("JARVIS  %s  |  %s  |  %d notes, %d links" % (url, "DEMO data" if data.is_demo() else "REAL data", st["notes"], st["edges"]))
    print("model: %s  |  voice: %s" % ("on (%s)" % llm.model_name() if llm.available() else "OFF, keyword routing only", (voice.engine() or "OFF")))
    for p in data.problems():
        print("warning:", p)
    if "--no-open" not in sys.argv:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")


if __name__ == "__main__":
    main()
