"""Alerts for real trading changes: an email (if SMTP is set) and an instant phone notification through the free
ntfy app (if NTFY_TOPIC is set). Simulated events are never sent out.

The ntfy topic is a long random name made by agent/setup_push.py. Anyone who knew it could read the alerts, so it is
kept private in .env like a password. Alerts only ever say what JARVIS did, never keys or passwords."""
import os
import smtplib
import threading
import urllib.request
from email.message import EmailMessage

SUBJECTS = {"order": "JARVIS: order", "fill": "JARVIS: order filled", "position": "JARVIS: position", "guard": "JARVIS: profit guard sold",
            "alert": "JARVIS: needs your attention", "autopilot": "JARVIS: autopilot", "summary": "JARVIS: end of day", "research": "JARVIS: research", "pl": "JARVIS: account moved"}
URGENT = {"alert", "guard"}


def email_ready():
    return bool(os.environ.get("SMTP_HOST") and os.environ.get("SMTP_USER") and os.environ.get("SMTP_PASS") and (os.environ.get("NOTIFY_EMAIL") or os.environ.get("NOTIFY_SMS_EMAIL")))


def push_ready():
    return bool(os.environ.get("NTFY_TOPIC", "").strip())


def configured():
    return email_ready() or push_ready()


def _send(subject, body):
    to = [a for a in (os.environ.get("NOTIFY_EMAIL"), os.environ.get("NOTIFY_SMS_EMAIL")) if a]
    msg = EmailMessage()
    msg["From"] = os.environ["SMTP_USER"]
    msg["To"] = ", ".join(to)
    msg["Subject"] = subject
    msg.set_content(body)
    port = int(os.environ.get("SMTP_PORT", "587"))
    with smtplib.SMTP(os.environ["SMTP_HOST"], port, timeout=20) as s:
        s.starttls()
        s.login(os.environ["SMTP_USER"], os.environ["SMTP_PASS"])
        s.send_message(msg)


def push(title, body, urgent=False, topic=None):
    server = os.environ.get("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
    topic = topic or os.environ.get("NTFY_TOPIC", "").strip()
    headers = {"Title": title.encode("ascii", "ignore").decode(), "Priority": "high" if urgent else "default", "Tags": "robot"}
    host = os.environ.get("JARVIS_ALLOWED_HOSTS", "").split(",")[0].strip()
    if host:
        headers["Click"] = "https://%s/trading.html" % host     # tapping the notification opens his Trading screen
    req = urllib.request.Request(server + "/" + topic, data=body.encode("utf-8"), method="POST", headers=headers)
    with urllib.request.urlopen(req, timeout=15) as r:
        r.read()


def send(kind, text):
    # "worth a look" signals can come often, so they stay on screen unless NOTIFY_SIGNALS=on
    if kind == "sim" or not configured() or (kind == "signal" and os.environ.get("NOTIFY_SIGNALS", "off").lower() != "on"):
        return
    subject = SUBJECTS.get(kind, "JARVIS trading update")
    threading.Thread(target=lambda: _try(subject, text, kind in URGENT), daemon=True).start()


def _try(subject, text, urgent):
    if push_ready():
        try:
            push(subject, text, urgent)
        except Exception:  # noqa: BLE001
            pass
    if email_ready():
        try:
            _send(subject, text)
        except Exception:  # noqa: BLE001
            pass
