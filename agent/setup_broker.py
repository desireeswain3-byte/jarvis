#!/usr/bin/env python3
"""Private broker key setup.
  Practice keys:  python3 agent/setup_broker.py
  Live keys:      python3 agent/setup_broker.py --live   (saved separately; the account stays on practice until you switch it)

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


def save(key, secret, live=False):
    pre = "ALPACA_LIVE_" if live else "ALPACA_"
    lines = ENV.read_text(encoding="utf-8").splitlines() if ENV.exists() else []
    lines = [ln for ln in lines if not re.match(r"\s*%s(KEY_ID|SECRET_KEY)\s*=" % pre, ln)]
    lines += [pre + "KEY_ID=" + key, pre + "SECRET_KEY=" + secret]
    ENV.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        os.chmod(ENV, 0o600)
    except OSError:
        pass


def main():
    live = "--live" in sys.argv
    print("Setting up your %s keys." % ("LIVE (real money)" if live else "PRACTICE (paper)"))
    print("This uses copy and paste from your clipboard, so you never type or paste into this window.")
    key = ask("Key ID", hidden=True)
    secret = ask("Secret key", hidden=True)
    if sys.stdin.isatty():
        clear_clip()
    if not key or not secret:
        print("\nOne of them was empty. Nothing was saved. Run this again.")
        return 1
    if key.startswith("AK") and not live:
        print("\nThat key ID starts with AK, which is a LIVE account key. For practice, use the Paper Trading keys."
              "\nTo save live keys, run: python3 agent/setup_broker.py --live\nNothing was saved.")
        return 1
    if key.startswith("PK") and live:
        print("\nThat key ID starts with PK, which is a PRACTICE key. Use the keys from your live account. Nothing was saved.")
        return 1
    os.environ["ALPACA_KEY_ID"], os.environ["ALPACA_SECRET_KEY"] = key, secret
    os.environ["ALPACA_MODE"] = "paper"
    print("\nTesting with Alpaca...")
    try:
        a = broker._req("GET", "/v2/account", host=broker.LIVE_URL if live else broker.PAPER_URL)
    except broker.BrokerError as e:
        print("It did not work: %s" % e)
        print("Nothing was saved. If the keys look right, generate new keys and try again.")
        return 1
    save(key, secret, live)
    try:
        eq = float(a.get("equity") or 0)
    except (TypeError, ValueError):
        eq = 0.0
    if live:
        print("It works. Live account equity: $%s. Live keys saved separately." % format(eq, ",.2f"))
        print("JARVIS still uses the PRACTICE account. Nothing trades with real money until you add ALPACA_MODE=live and ALPACA_ALLOW_LIVE=yes to .env,")
        print("and autopilot stays off on live until your practice run passes and you add AUTO_ALLOW_LIVE=yes.")
    else:
        print("It works. Practice account equity: $%s. Keys saved." % format(eq, ",.2f"))
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
