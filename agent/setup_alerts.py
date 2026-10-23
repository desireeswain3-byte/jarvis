#!/usr/bin/env python3
"""Set up email alerts to her phone. Run: python3 agent/setup_alerts.py

Everything is asked in the Mac's normal pop-up boxes (the password box shows dots), not typed into Terminal.
It sends a test email first and saves the settings to .env only if that works. Gmail sends a notification to her
phone for each alert through the Gmail app."""
import os
import re
import smtplib
import subprocess
import sys
import webbrowser
from email.message import EmailMessage
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV = ROOT / ".env"


def _q(s):
    return s.replace("\\", "\\\\").replace('"', '\\"')


def ask(prompt, default="", hidden=False):
    if sys.platform == "darwin":
        script = 'text returned of (display dialog "%s" default answer "%s"%s with title "JARVIS alerts" buttons {"Cancel", "OK"} default button "OK")' % (
            _q(prompt), _q(default), " with hidden answer" if hidden else "")
        r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
        if r.returncode != 0:
            print("Cancelled. Nothing was saved.")
            sys.exit(1)
        return r.stdout.strip()
    import getpass
    return (getpass.getpass(prompt + " ") if hidden else input(prompt + " ")).strip() or default


def tell(msg):
    print(msg)
    if sys.platform == "darwin":
        subprocess.run(["osascript", "-e", 'display dialog "%s" with title "JARVIS alerts" buttons {"OK"} default button "OK"' % _q(msg)], capture_output=True)


def save(values):
    lines = ENV.read_text(encoding="utf-8").splitlines() if ENV.exists() else []
    keys = set(values)
    lines = [ln for ln in lines if not any(re.match(r"\s*%s\s*=" % k, ln) for k in keys)]
    lines += ["%s=%s" % (k, v) for k, v in values.items()]
    ENV.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.chmod(ENV, 0o600)


def main():
    user = ask("Which Gmail address should send the alerts? (Your own Gmail is fine.)", "")
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", user):
        tell("That does not look like an email address. Nothing was saved. Run this again.")
        return 1
    tell("Next, Google needs an App Password for JARVIS (a special 16-letter password just for him; your real password is never used).\n\n"
         "A Google page will open. If it says App Passwords are not available, turn on 2-Step Verification first, then come back to that page.\n\n"
         "Name it JARVIS, click Create, and copy the 16 letters.")
    webbrowser.open("https://myaccount.google.com/apppasswords")
    pw = re.sub(r"\s+", "", ask("Paste the 16-letter App Password here:", hidden=True))
    if len(pw) < 12:
        tell("That App Password looks too short. Nothing was saved. Run this again.")
        return 1
    to = ask("Which email should the alerts go to? (Use the Gmail on your phone so it buzzes.)", user)
    print("Sending a test email...")
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = user, to, "JARVIS alerts are on"
    msg.set_content("Good day, Madam Swain. This is JARVIS. Trading alerts will arrive here: buys, sells, stops, the profit guard, and the evening summary.")
    try:
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=20) as s:
            s.starttls()
            s.login(user, pw)
            s.send_message(msg)
    except smtplib.SMTPAuthenticationError:
        tell("Google did not accept that App Password. Nothing was saved. Make a new App Password and run this again.")
        return 1
    except Exception as e:  # noqa: BLE001
        tell("The test email did not send (%s). Nothing was saved." % str(e)[:120])
        return 1
    save({"SMTP_HOST": "smtp.gmail.com", "SMTP_PORT": "587", "SMTP_USER": user, "SMTP_PASS": pw, "NOTIFY_EMAIL": to})
    plist = Path.home() / "Library/LaunchAgents/com.jarvis.plist"
    if plist.exists():
        subprocess.run(["launchctl", "unload", str(plist)], capture_output=True)
        subprocess.run(["launchctl", "load", str(plist)], capture_output=True)
    tell("Done. A test email was sent to %s. JARVIS restarted and will email you trading alerts from now on.\n\n"
         "On your iPhone, make sure the Gmail app has notifications turned on." % to)
    return 0


if __name__ == "__main__":
    sys.exit(main())
