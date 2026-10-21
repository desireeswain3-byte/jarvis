"""Her real Mail, Calendar, Reminders, Contacts and Messages, through the Mac's own apps (AppleScript).

Whatever accounts she has added to those apps (Gmail, iCloud, Outlook) are what JARVIS sees. Nothing leaves her Mac
except the pieces needed to answer her, which go to the assistant.

Safety:
  * Reading mail, calendar and reminders, adding a reminder or a calendar event, and ticking off a reminder happen
    straight away. They are easy to undo in the app.
  * Sending a text, sending an email and deleting email are only ever done by confirm_* functions, which tools.py
    calls only after she presses Confirm on screen with a real click. Deleted mail goes to the Trash, not gone forever.
  * Everything she typed or said is passed to AppleScript as arguments, never pasted into the script, so a message
    or a subject line can never turn into a command.
macOS asks her once for each app the first time (Privacy and Security, Automation). Until she says yes, the error
explains how.
"""
import datetime
import os
import re
import subprocess
import sys

OSASCRIPT = os.environ.get("JARVIS_OSASCRIPT_BIN", "osascript")
SEP, END = "|||", "<<<END>>>"


class MacError(Exception):
    pass


def _python_path():
    try:
        return os.path.realpath(sys.executable)
    except Exception:  # noqa: BLE001
        return "python3"


def _help(app):
    return ("I can't open %s yet, because your Mac has not allowed it. When a permission box appears, click OK. If it never appeared: open System Settings, "
            "then Privacy and Security, then Automation, find %s and switch on %s. Then ask me again." % (app, _python_path(), app))


def run(script, args=(), app="that app", timeout=60):
    try:
        r = subprocess.run([OSASCRIPT, "-e", script] + [str(a) for a in args], capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        raise MacError("Your Mail, Calendar and Reminders only work when JARVIS runs on your Mac.")
    except subprocess.TimeoutExpired:
        raise MacError("%s took too long to answer. Try again in a moment." % app)
    if r.returncode != 0:
        err = (r.stderr or "").strip()
        if "-1743" in err or "not authorized" in err.lower() or "not allowed" in err.lower():
            raise MacError(_help(app))
        if "-600" in err or "isn't running" in err.lower():
            raise MacError("%s is not open. Open it once and try again." % app)
        raise MacError("%s had a problem: %s" % (app, err[:180]))
    return r.stdout


def _rows(out, n):
    rows = []
    for chunk in out.split(END):
        if SEP not in chunk:
            continue
        parts = [p.strip() for p in chunk.split(SEP)]
        rows.append((parts + [""] * n)[:n])
    return rows


def _iso(s):
    try:
        return datetime.datetime.fromisoformat(s.strip())
    except (ValueError, AttributeError):
        return None


# ---------------- Mail ----------------

MAIL_LIST = '''on run argv
set n to (item 1 of argv) as integer
set out to ""
tell application "Mail"
  set c to count of messages of inbox
  if c < n then set n to c
  repeat with i from 1 to n
    set m to message i of inbox
    set p to ""
    try
      set p to content of m
      if length of p > 400 then set p to text 1 thru 400 of p
    end try
    set out to out & (id of m) & "|||" & (sender of m) & "|||" & (subject of m) & "|||" & (((date received of m) as «class isot») as string) & "|||" & (read status of m) & "|||" & p & "<<<END>>>"
  end repeat
end tell
return out
end run'''

MAIL_DELETE = '''on run argv
set done to 0
tell application "Mail"
  repeat with x in argv
    try
      set m to (first message of inbox whose id is (x as integer))
      delete m
      set done to done + 1
    end try
  end repeat
end tell
return done as string
end run'''

MAIL_SEND = '''on run argv
tell application "Mail"
  set m to make new outgoing message with properties {subject:(item 2 of argv), content:(item 3 of argv), visible:false}
  tell m to make new to recipient at end of to recipients with properties {address:(item 1 of argv)}
  send m
end tell
return "ok"
end run'''


def _sender(s):
    m = re.match(r"\s*\"?([^\"<]*)\"?\s*<([^>]+)>", s or "")
    if m:
        return (m.group(1).strip() or m.group(2)), m.group(2).strip()
    return (s or "Unknown").strip(), (s or "").strip()


def inbox(limit=20):
    out = run(MAIL_LIST, [max(1, min(int(limit), 40))], "Mail", timeout=90)
    today = datetime.date.today()
    mail = []
    for mid, sender, subject, when, read, preview in _rows(out, 6):
        name, email = _sender(sender)
        d = _iso(when)
        mail.append({"id": mid, "from": name, "email": email, "subject": subject or "(no subject)", "when": d.strftime("%a %b %d %I:%M %p").replace(" 0", " ") if d else "",
                     "days_ago": (today - d.date()).days if d else 0, "unread": read.lower() != "true", "body": re.sub(r"\s+", " ", preview)[:400], "_t": d or datetime.datetime.min})
    mail.sort(key=lambda m: m["_t"], reverse=True)
    for m in mail:
        m.pop("_t", None)
    return mail


def confirm_delete_mail(ids):
    ids = [str(int(i)) for i in ids if str(i).strip().isdigit()][:25]
    if not ids:
        raise MacError("No emails to delete.")
    return int((run(MAIL_DELETE, ids, "Mail") or "0").strip() or 0)


def confirm_send_mail(to, subject, body):
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", to or ""):
        raise MacError("That email address does not look right.")
    run(MAIL_SEND, [to, subject or "", body or ""], "Mail")


# ---------------- Calendar ----------------

CAL_LIST = '''on run argv
set n to (item 1 of argv) as integer
set startD to current date
set time of startD to 0
set endD to startD + n * days
set out to ""
tell application "Calendar"
  repeat with cl in calendars
    set cname to name of cl
    try
      set evs to (every event of cl whose start date ≥ startD and start date < endD)
      repeat with e in evs
        set t to summary of e
        if t is missing value then set t to "(no title)"
        set loc to location of e
        if loc is missing value then set loc to ""
        set out to out & t & "|||" & (((start date of e) as «class isot») as string) & "|||" & (allday event of e) & "|||" & cname & "|||" & loc & "<<<END>>>"
      end repeat
    end try
  end repeat
end tell
return out
end run'''

CAL_ADD = '''on run argv
set d to current date
set day of d to 1
set year of d to (item 2 of argv) as integer
set month of d to (item 3 of argv) as integer
set day of d to (item 4 of argv) as integer
set time of d to ((item 5 of argv) as integer) * 3600 + ((item 6 of argv) as integer) * 60
set e2 to d + ((item 7 of argv) as integer) * minutes
tell application "Calendar"
  set cname to item 8 of argv
  if cname is "" then
    set c to first calendar whose writable is true
  else
    set c to first calendar whose name is cname
  end if
  make new event at end of events of c with properties {summary:(item 1 of argv), start date:d, end date:e2}
  return name of c
end tell
end run'''


def events(days=7):
    out = run(CAL_LIST, [max(1, min(int(days), 31))], "Calendar", timeout=120)
    evs = []
    for title, start, allday, cal, loc in _rows(out, 5):
        d = _iso(start)
        if not d:
            continue
        evs.append({"date": d.date().isoformat(), "time": "" if allday.lower() == "true" else d.strftime("%I:%M %p").lstrip("0"),
                    "title": title, "with": loc, "calendar": cal, "_t": d})
    evs.sort(key=lambda e: e["_t"])
    for e in evs:
        e.pop("_t", None)
    return evs


def add_event(title, when, minutes=60, calendar=""):
    d = when if isinstance(when, datetime.datetime) else _iso(str(when))
    if not d:
        raise MacError("I need a date and time like 2026-10-22 14:30.")
    cal = run(CAL_ADD, [title, d.year, d.month, d.day, d.hour, d.minute, max(5, int(minutes or 60)), calendar or ""], "Calendar").strip()
    return cal


# ---------------- Reminders ----------------

REM_LIST = '''set out to ""
tell application "Reminders"
  repeat with r in (reminders whose completed is false)
    set dd to ""
    try
      set x to due date of r
      if x is not missing value then set dd to ((x as «class isot») as string)
    end try
    set out to out & (name of r) & "|||" & dd & "|||" & (name of container of r) & "<<<END>>>"
  end repeat
end tell
return out'''

REM_ADD = '''on run argv
tell application "Reminders"
  set lname to item 2 of argv
  if lname is "" then
    set L to default list
  else
    set L to list lname
  end if
  set r to make new reminder at end of reminders of L with properties {name:(item 1 of argv)}
  if (item 3 of argv) is "1" then
    set d to current date
    set day of d to 1
    set year of d to (item 4 of argv) as integer
    set month of d to (item 5 of argv) as integer
    set day of d to (item 6 of argv) as integer
    set time of d to ((item 7 of argv) as integer) * 3600 + ((item 8 of argv) as integer) * 60
    set due date of r to d
    set remind me date of r to d
  end if
  return name of L
end tell
end run'''

REM_DONE = '''on run argv
tell application "Reminders"
  set r to first reminder whose completed is false and name contains (item 1 of argv)
  set completed of r to true
  return name of r
end tell
end run'''


def reminders():
    out = run(REM_LIST, [], "Reminders", timeout=90)
    rows = []
    for name, due, lst in _rows(out, 3):
        d = _iso(due)
        rows.append({"title": name, "due": d.strftime("%a %b %d %I:%M %p").replace(" 0", " ") if d else "", "list": lst, "_t": d or datetime.datetime.max})
    rows.sort(key=lambda r: r["_t"])
    for r in rows:
        r.pop("_t", None)
    return rows


def add_reminder(title, when=None, lst=""):
    d = when if isinstance(when, datetime.datetime) or when is None else _iso(str(when))
    args = [title, lst or "", "1" if d else "0"] + ([d.year, d.month, d.day, d.hour, d.minute] if d else [0, 0, 0, 0, 0])
    return run(REM_ADD, args, "Reminders").strip()


def complete_reminder(title):
    return run(REM_DONE, [title], "Reminders").strip()


# ---------------- Contacts and Messages ----------------

CONTACT_FIND = '''on run argv
set out to ""
tell application "Contacts"
  repeat with p in (people whose name contains (item 1 of argv))
    set nm to name of p
    repeat with ph in phones of p
      set out to out & nm & "|||" & (value of ph) & "|||phone<<<END>>>"
    end repeat
    repeat with em in emails of p
      set out to out & nm & "|||" & (value of em) & "|||email<<<END>>>"
    end repeat
  end repeat
end tell
return out
end run'''

TEXT_SEND = '''on run argv
tell application "Messages"
  try
    set s to 1st account whose service type = iMessage
    send (item 2 of argv) to participant (item 1 of argv) of s
    return "imessage"
  end try
  set s to 1st account whose service type = SMS
  send (item 2 of argv) to participant (item 1 of argv) of s
  return "sms"
end tell
end run'''


def find_contact(name, kind=None):
    """Matches in her Contacts as dicts with name, value, kind (phone or email)."""
    out = run(CONTACT_FIND, [name], "Contacts")
    rows = [{"name": n, "value": v, "kind": k} for n, v, k in _rows(out, 3)]
    return [r for r in rows if not kind or r["kind"] == kind][:8]


def looks_like_address(s):
    s = (s or "").strip()
    return bool(re.fullmatch(r"\+?[\d\s().-]{7,}", s) or re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", s))


def confirm_send_text(to, text):
    if not looks_like_address(to):
        raise MacError("I need a phone number or an iMessage email to text.")
    to = re.sub(r"[\s().-]", "", to) if not "@" in to else to
    return run(TEXT_SEND, [to, text], "Messages").strip()
