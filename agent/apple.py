"""Read-only access to Apple Messages and Apple Notes on her Mac.

It only reads. It never sends a message and never changes a note. Everything stays on her computer until she asks
JARVIS about it, and then only the pieces needed for that answer are given to the assistant. macOS asks her for
permission the first time (Full Disk Access for Messages, Automation for Notes), and until she says yes this
module just explains how to give it.
"""
import datetime
import os
import re
import sqlite3
import subprocess
import sys

MESSAGES_DB = os.path.expanduser(os.environ.get("JARVIS_MESSAGES_DB", "~/Library/Messages/chat.db"))
OSASCRIPT = os.environ.get("JARVIS_OSASCRIPT_BIN", "osascript")
APPLE_EPOCH = datetime.datetime(2001, 1, 1)


class AppleError(Exception):
    pass


def _python_path():
    try:
        return os.path.realpath(sys.executable)
    except Exception:
        return "python3"


def _decode_body(blob):
    """Newer macOS keeps message text inside a binary blob. Pull the plain text back out."""
    if not blob:
        return ""
    try:
        b = bytes(blob)
        i = b.find(b"NSString")
        if i < 0:
            return ""
        b = b[i + len(b"NSString"):]
        j = b.find(b"\x01+")
        if j < 0:
            return ""
        b = b[j + 2:]
        n = b[0]
        if n == 0x81:
            n = int.from_bytes(b[1:3], "little"); b = b[3:]
        elif n == 0x82:
            n = int.from_bytes(b[1:5], "little"); b = b[5:]
        else:
            b = b[1:]
        return b[:n].decode("utf-8", "ignore").strip()
    except Exception:
        return ""


def _when(ns):
    try:
        secs = ns / 1e9 if ns > 1e12 else ns
        return (APPLE_EPOCH + datetime.timedelta(seconds=secs)).replace(tzinfo=datetime.timezone.utc).astimezone().strftime("%a %b %d, %I:%M %p").replace(" 0", " ")
    except Exception:
        return ""


def messages_help():
    return ("I can't open your Messages yet, because your Mac has not allowed it. Do this once: open System Settings, then Privacy and Security, then Full Disk Access. "
            "Click the plus button, press Command Shift G, paste %s, choose it, and switch it on. Then say 'restart yourself' or click Update, and ask me again. "
            "I only read messages, I never send them." % _python_path())


def recent_messages(limit=8, contact=""):
    limit = max(1, min(int(limit or 8), 25))
    if not os.path.exists(MESSAGES_DB):
        raise AppleError("There is no Messages database on this computer, so I can't read messages here.")
    try:
        con = sqlite3.connect("file:%s?mode=ro" % MESSAGES_DB, uri=True, timeout=3)
        sql = ("SELECT m.date, m.is_from_me, m.text, m.attributedBody, h.id FROM message m LEFT JOIN handle h ON m.handle_id = h.ROWID "
               "WHERE (? = '' OR h.id LIKE ?) ORDER BY m.date DESC LIMIT ?")
        c = (contact or "").strip()
        rows = con.execute(sql, (c, "%" + c + "%", limit * 3)).fetchall()
        con.close()
    except sqlite3.OperationalError as e:
        raise AppleError(messages_help() if ("unable to open" in str(e) or "authoriz" in str(e).lower() or "permission" in str(e).lower()) else "I could not read Messages: %s" % e)
    out = []
    for date, mine, text, blob, who in rows:
        body = (text or "").strip() or _decode_body(blob)
        if not body or body == "￼":
            continue
        out.append({"when": _when(date or 0), "from": "you" if mine else (who or "unknown"), "text": body[:400]})
        if len(out) >= limit:
            break
    return out


def notes_help():
    return ("I can't open your Notes yet, because your Mac has not allowed it. When the permission box appears, click OK. If it never appeared: open System Settings, then Privacy and Security, then Automation, "
            "find %s in the list and switch on Notes. Then ask me again. I only read notes, I never change them." % _python_path())


def recent_notes(query="", limit=5):
    limit = max(1, min(int(limit or 5), 10))
    script = ('tell application "Notes"\nset out to ""\nset c to count of notes\nif c > 60 then set c to 60\n'
              'repeat with i from 1 to c\nset n to note i\nset out to out & (name of n) & "|||" & (plaintext of n) & "<<<END>>>"\nend repeat\nreturn out\nend tell')
    try:
        r = subprocess.run([OSASCRIPT, "-e", script], capture_output=True, text=True, timeout=60)
    except FileNotFoundError:
        raise AppleError("Apple Notes is only available when JARVIS runs on your Mac.")
    except subprocess.TimeoutExpired:
        raise AppleError("Notes took too long to answer. Try again in a moment.")
    if r.returncode != 0:
        err = r.stderr or ""
        if "-1743" in err or "not authorized" in err.lower() or "not allowed" in err.lower():
            raise AppleError(notes_help())
        raise AppleError("I could not read Notes: %s" % err.strip()[:150])
    notes = []
    q = (query or "").strip().lower()
    for chunk in r.stdout.split("<<<END>>>"):
        if "|||" not in chunk:
            continue
        title, body = chunk.split("|||", 1)
        title, body = title.strip(), re.sub(r"\s+", " ", body).strip()
        if q and q not in title.lower() and q not in body.lower():
            continue
        notes.append({"title": title[:100], "text": body[:600]})
        if len(notes) >= limit:
            break
    return notes
