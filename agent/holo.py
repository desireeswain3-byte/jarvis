"""What the hologram bubbles show. Each bubble is a live summary with a few items to open.
Every part is optional: if one source is not connected, its bubble just says so. Cached briefly, because Mail and
Calendar can take a few seconds to answer."""
import time

import broker
import data
import memory

_cache = {"t": 0.0, "out": None}
TTL = 60


def _trading():
    if not broker.configured():
        return {"id": "trading", "label": "Trading", "big": "demo", "sub": "no broker", "items": []}
    a = broker.account()
    pos = broker.positions()
    import autopilot
    items = [{"title": p["symbol"], "text": "$%.2f, %s$%.2f" % (p["value"], "+" if p["pl"] >= 0 else "-", abs(p["pl"]))} for p in pos]
    items.append({"title": "Autopilot", "text": "on" if autopilot.is_on() else "off"})
    return {"id": "trading", "label": "Trading", "big": "$%s" % format(a["equity"], ",.0f"), "sub": "%s$%.2f today" % ("+" if a["today"] >= 0 else "-", abs(a["today"])),
            "tone": "up" if a["today"] >= 0 else "down", "items": items}


def _inbox():
    mail = data.inbox()
    if mail is None:
        return {"id": "inbox", "label": "Inbox", "big": "off", "sub": "not connected", "items": []}
    unread = [m for m in mail if m["unread"]]
    return {"id": "inbox", "label": "Inbox", "big": str(len(unread)), "sub": "unread", "items": [{"title": m["from"], "text": m["subject"]} for m in (unread or mail)[:8]]}


def _calendar():
    cal = data.calendar()
    if cal is None:
        return {"id": "calendar", "label": "Calendar", "big": "off", "sub": "not connected", "items": []}
    today = data.today().isoformat()
    td = [e for e in cal if e["date"] == today]
    up = [e for e in cal if e["date"] >= today]
    return {"id": "calendar", "label": "Calendar", "big": str(len(td)), "sub": "today", "items": [{"title": "%s %s" % (e["date"][5:], e["time"] or "all day"), "text": e["title"]} for e in up[:8]]}


def _reminders():
    if data.is_demo():
        return None
    import mac
    rows = mac.reminders()
    return {"id": "reminders", "label": "Reminders", "big": str(len(rows)), "sub": "to do", "items": [{"title": r["due"] or r["list"], "text": r["title"]} for r in rows[:8]]}


def _folder(sub, label, unit):
    d = memory.MEM / "trading" / sub
    files = sorted(d.glob("*.md"), reverse=True) if d.exists() else []
    items = []
    for p in files[:8]:
        txt = p.read_text(encoding="utf-8", errors="replace")
        title = next((ln[2:].strip() for ln in txt.splitlines() if ln.startswith("# ")), p.stem)
        body = " ".join(ln for ln in txt.split("---")[-1].splitlines() if ln and not ln.startswith("#"))[:160]
        items.append({"title": title, "text": body})
    return {"id": sub, "label": label, "big": str(len(files)), "sub": unit, "items": items}


def bubbles(vault=None):
    if _cache["out"] is not None and time.time() - _cache["t"] < TTL:
        return _cache["out"]
    out = []
    for fn in (_trading, _inbox, _calendar, _reminders, lambda: _folder("lessons", "Lessons", "learned"), lambda: _folder("research", "Research", "notes")):
        try:
            b = fn()
        except Exception as e:  # noqa: BLE001
            b = None
            out.append({"id": getattr(fn, "__name__", "x").strip("_"), "label": getattr(fn, "__name__", "x").strip("_").capitalize(), "big": "!", "sub": "error", "items": [{"title": "Problem", "text": str(e)[:160]}]})
        if b:
            out.append(b)
    if vault is not None:
        st = vault.stats()
        out.append({"id": "brain", "label": "Brain", "big": str(st.get("notes", 0)), "sub": "notes", "items": [{"title": "Links", "text": str(st.get("edges", 0))}]})
    _cache.update(t=time.time(), out=out)
    return out


def props():
    """3D models she dropped into ui/props (.glb files)."""
    from pathlib import Path
    d = Path(__file__).resolve().parent.parent / "ui" / "props"
    return sorted(p.name for p in d.glob("*.glb")) if d.exists() else []
