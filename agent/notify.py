"""Optional email and text alerts for real trading changes. Off until .env has the SMTP settings. Simulated events are never sent out."""
import os
import smtplib
import threading
from email.message import EmailMessage


def configured():
    return bool(os.environ.get("SMTP_HOST") and os.environ.get("SMTP_USER") and os.environ.get("SMTP_PASS") and (os.environ.get("NOTIFY_EMAIL") or os.environ.get("NOTIFY_SMS_EMAIL")))


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


SUBJECTS = {"order": "JARVIS: order", "fill": "JARVIS: order filled", "position": "JARVIS: position", "guard": "JARVIS: profit guard sold",
            "alert": "JARVIS: needs your attention", "autopilot": "JARVIS: autopilot", "summary": "JARVIS: end of day", "research": "JARVIS: research", "pl": "JARVIS: account moved"}


def send(kind, text):
    # "worth a look" signals can come often, so they stay on screen unless NOTIFY_SIGNALS=on
    if kind == "sim" or not configured() or (kind == "signal" and os.environ.get("NOTIFY_SIGNALS", "off").lower() != "on"):
        return
    threading.Thread(target=lambda: _try(SUBJECTS.get(kind, "JARVIS trading update"), text), daemon=True).start()


def _try(subject, text):
    try:
        _send(subject, text)
    except Exception:
        pass
