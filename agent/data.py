"""The only file that touches real data.

JARVIS_DEMO is read here and nowhere else. Default is demo (1). Set
JARVIS_DEMO=0 in .env to point JARVIS at your real folders.
"""
import datetime
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DEMO = os.environ.get("JARVIS_DEMO", "1").strip() != "0"

_problems = []


def is_demo():
    return DEMO


def problems():
    return list(_problems)


def _ensure_demo():
    if not (DATA / "demo" / "notes").exists():
        subprocess.run([sys.executable, str(DATA / "generate_demo.py")], check=True)


def roots():
    """Folders to index, as (label, Path). Read-only."""
    if DEMO:
        _ensure_demo()
        return [("demo", DATA / "demo" / "notes")]
    out = []
    raw = os.environ.get("JARVIS_FOLDERS", "")
    for part in raw.split(os.pathsep):
        part = part.strip()
        if not part:
            continue
        p = Path(part).expanduser()
        if p.is_dir():
            out.append((p.name or "root", p))
        else:
            _problems.append("Folder not found: " + part)
    if not out:
        _problems.append("JARVIS_DEMO=0 but no folders found. Set JARVIS_FOLDERS in .env (separate paths with '%s')." % os.pathsep)
    return out


def _load(name):
    path = (DATA / "demo" / name) if DEMO else (DATA / name)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        _problems.append("Could not read %s: %s" % (path.name, e))
        return None


def today():
    return datetime.date.today()


def inbox():
    """List of emails, or None when no inbox export exists."""
    raw = _load("inbox.json")
    if raw is None:
        return None
    out = []
    for m in raw:
        days = m.get("days_ago")
        if days is None and m.get("date"):
            try:
                days = (today() - datetime.date.fromisoformat(m["date"][:10])).days
            except ValueError:
                days = 0
        out.append({
            "from": m.get("from", "Unknown"),
            "email": m.get("email", ""),
            "subject": m.get("subject", "(no subject)"),
            "days_ago": int(days or 0),
            "unread": bool(m.get("unread", False)),
            "body": m.get("body", ""),
        })
    return out


def calendar():
    """List of events with ISO dates, or None when no calendar export exists."""
    raw = _load("calendar.json")
    if raw is None:
        return None
    out = []
    for e in raw:
        if "day" in e:
            date = (today() + datetime.timedelta(days=int(e["day"]))).isoformat()
        else:
            date = e.get("date", "")[:10]
        out.append({"date": date, "time": e.get("time", ""), "title": e.get("title", ""), "with": e.get("with", "")})
    return sorted(out, key=lambda x: (x["date"], x["time"]))


def ledger():
    """Invoices, or None when there is no ledger file."""
    return _load("ledger.json")
