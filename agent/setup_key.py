#!/usr/bin/env python3
"""Swap in a new Anthropic API key for JARVIS's brain. Run: python3 ~/jarvis/agent/setup_key.py

Reads the new key from the clipboard (nothing is typed or shown), tests it with Anthropic, and only if the test
passes replaces ANTHROPIC_API_KEY in .env, then restarts JARVIS. The old key line is removed. Nothing is printed back."""
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV = ROOT / ".env"


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


def get_key():
    if sys.stdin.isatty() and subprocess.run(["which", "pbpaste"], capture_output=True).returncode == 0 and os.environ.get("JARVIS_SETUP_TYPE") != "1":
        input("In the Anthropic Console, press Create Key, then click the copy button next to the new key.\nThen come back here and press Return: ")
        raw = clip()
    elif sys.stdin.isatty():
        import getpass
        raw = getpass.getpass("New API key (nothing shows as you paste): ")
    else:
        raw = sys.stdin.readline()
    return re.sub(r"\s+", "", raw or "").strip("\"'")


def test(key):
    """True if Anthropic accepts the key. Lists models, which costs nothing."""
    base = os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com").rstrip("/")
    req = urllib.request.Request(base + "/v1/models?limit=1", headers={"x-api-key": key, "anthropic-version": "2023-06-01"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            json.loads(r.read() or b"{}")
            return True, ""
    except urllib.error.HTTPError as e:
        return False, "Anthropic said %s (%s)." % (e.code, "the key was not accepted" if e.code in (401, 403) else "try again in a minute")
    except (urllib.error.URLError, OSError) as e:
        return False, "Could not reach Anthropic: %s" % e


def save(key):
    lines = ENV.read_text(encoding="utf-8").splitlines() if ENV.exists() else []
    lines = [ln for ln in lines if not re.match(r"\s*(export\s+)?ANTHROPIC_API_KEY\s*=", ln)]
    lines.append("ANTHROPIC_API_KEY=" + key)
    ENV.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        os.chmod(ENV, 0o600)
    except OSError:
        pass


def main():
    print("Swapping in a new Anthropic API key for JARVIS.")
    key = get_key()
    if sys.stdin.isatty():
        clear_clip()
    if not key:
        print("\nThe clipboard was empty. Nothing was saved. Copy the key and run this again.")
        return 1
    if not key.startswith("sk-ant-"):
        print("\nThat does not look like an Anthropic API key (they start with sk-ant-). Nothing was saved.")
        return 1
    print("\nTesting the new key with Anthropic...")
    ok, why = test(key)
    if not ok:
        print("It did not work. " + why + "\nNothing was saved, so JARVIS keeps the old key for now.")
        return 1
    save(key)
    print("It works. New key saved and the old one removed from .env.")
    if os.environ.get("JARVIS_NO_RESTART") != "1":
        plist = Path.home() / "Library/LaunchAgents/com.jarvis.plist"
        if plist.exists():
            subprocess.run(["launchctl", "unload", str(plist)], capture_output=True)
            subprocess.run(["launchctl", "load", str(plist)], capture_output=True)
            print("JARVIS restarted. Reload his page in Chrome (Command, Shift and R) and say hello.")
        else:
            print("Restart JARVIS, then reload the page.")
    print("\nLast step: back in the Anthropic Console, you can delete the old key named Jarvis (the one expiring Nov 17).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
