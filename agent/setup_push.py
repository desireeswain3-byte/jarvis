#!/usr/bin/env python3
"""Instant phone notifications through the free ntfy app. Run: python3 agent/setup_push.py

Makes a private, random channel name, saves it to .env, sends a test notification, and (if email alerts are set up)
emails her the channel name so she can copy it on her phone instead of typing it."""
import os
import re
import secrets
import string
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV = ROOT / ".env"
sys.path.insert(0, str(Path(__file__).resolve().parent))


def load_env():
    if ENV.exists():
        for ln in ENV.read_text(encoding="utf-8").splitlines():
            m = re.match(r"\s*([A-Z0-9_]+)\s*=\s*(.*)$", ln)
            if m and m.group(1) not in os.environ:
                os.environ[m.group(1)] = m.group(2).strip().strip("\"'")


def save(key, value):
    lines = ENV.read_text(encoding="utf-8").splitlines() if ENV.exists() else []
    lines = [ln for ln in lines if not re.match(r"\s*%s\s*=" % key, ln)]
    lines.append("%s=%s" % (key, value))
    ENV.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.chmod(ENV, 0o600)


def main():
    load_env()
    import notify
    topic = os.environ.get("NTFY_TOPIC", "").strip()
    if not topic:
        topic = "jarvis-" + "".join(secrets.choice(string.ascii_lowercase + string.digits) for _ in range(12))
    try:
        notify.push("JARVIS is connected", "Good day, Madam Swain. Trading alerts will buzz your phone here.", topic=topic)
    except Exception as e:  # noqa: BLE001
        print("Could not reach ntfy.sh (%s). Check the internet and run this again. Nothing was saved." % str(e)[:120])
        return 1
    save("NTFY_TOPIC", topic)
    os.environ["NTFY_TOPIC"] = topic
    emailed = False
    if notify.email_ready():
        try:
            notify._send("Your JARVIS notification channel", "On your iPhone, install the free ntfy app from the App Store, tap the + button, and paste this channel name:\n\n%s\n\n"
                         "Keep it private, like a password." % topic)
            emailed = True
        except Exception:  # noqa: BLE001
            pass
    plist = Path.home() / "Library/LaunchAgents/com.jarvis.plist"
    if plist.exists():
        subprocess.run(["launchctl", "unload", str(plist)], capture_output=True)
        subprocess.run(["launchctl", "load", str(plist)], capture_output=True)
    print("")
    print("Done. Your private channel name is:")
    print("")
    print("    " + topic)
    print("")
    print("On your iPhone:")
    print("  1. Install the free app called ntfy from the App Store.")
    print("  2. Open it, tap the + button, and enter the channel name above" + (" (I also emailed it to you, so you can copy it from Gmail)." if emailed else "."))
    print("  3. Tap Subscribe, and allow notifications when it asks.")
    print("Keep the channel name private, like a password. JARVIS has restarted and will buzz your phone for every trade.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
