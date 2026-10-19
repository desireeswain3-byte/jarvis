#!/usr/bin/env python3
"""Private broker key setup. Run: python3 agent/setup_broker.py

Asks for the key ID and secret key (the secret is typed or pasted with nothing shown on screen), tests them
with Alpaca, and saves them to .env only if the test passes. Nothing is printed back."""
import getpass
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV = ROOT / ".env"
sys.path.insert(0, str(Path(__file__).resolve().parent))
import broker  # noqa: E402


def clip():
    try:
        return subprocess.run(["pbpaste"], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def clear_clip():
    try:
        subprocess.run(["pbcopy"], input="", text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        pass


def ask(label, hidden):
    if sys.stdin.isatty() and os.environ.get("JARVIS_SETUP_TYPE") != "1" and subprocess.run(["which", "pbpaste"], capture_output=True).returncode == 0:
        input("On Alpaca, click the copy button for the %s. Then come back here and press Return: " % label)
        return re.sub(r"\s+", "", clip() or "").strip("\"'")
    if sys.stdin.isatty():
        raw = getpass.getpass(label) if hidden else input(label)
    else:
        raw = sys.stdin.readline()
    return re.sub(r"\s+", "", raw or "").strip("\"'")


def save(key, secret):
    lines = ENV.read_text(encoding="utf-8").splitlines() if ENV.exists() else []
    lines = [ln for ln in lines if not re.match(r"\s*ALPACA_(KEY_ID|SECRET_KEY)\s*=", ln)]
    lines += ["ALPACA_KEY_ID=" + key, "ALPACA_SECRET_KEY=" + secret]
    ENV.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        os.chmod(ENV, 0o600)
    except OSError:
        pass


def main():
    print("This uses copy and paste from your clipboard, so you never type or paste into this window.")
    key = ask("Key ID", hidden=True)
    secret = ask("Secret key", hidden=True)
    if sys.stdin.isatty():
        clear_clip()
    if not key or not secret:
        print("\nOne of them was empty. Nothing was saved. Run this again.")
        return 1
    if key.startswith("AK"):
        print("\nThat key ID starts with AK, which is a LIVE account key. Use the Paper Trading keys. Nothing was saved.")
        return 1
    os.environ["ALPACA_KEY_ID"], os.environ["ALPACA_SECRET_KEY"] = key, secret
    os.environ["ALPACA_MODE"] = "paper"
    print("\nTesting with Alpaca...")
    try:
        a = broker.account()
    except broker.BrokerError as e:
        print("It did not work: %s" % e)
        print("Nothing was saved. If the keys look right, generate new Paper Trading keys and try again.")
        return 1
    save(key, secret)
    print("It works. Practice account equity: $%s. Keys saved." % format(a["equity"], ",.2f"))
    if os.environ.get("JARVIS_NO_RESTART") != "1":
        plist = Path.home() / "Library/LaunchAgents/com.jarvis.plist"
        if plist.exists():
            subprocess.run(["launchctl", "unload", str(plist)], capture_output=True)
            subprocess.run(["launchctl", "load", str(plist)], capture_output=True)
            print("JARVIS restarted. Reload the page in Chrome (Command, Shift and R) and press Trading.")
        else:
            print("Restart JARVIS, then reload the page.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
