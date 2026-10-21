"""Keeps the Mac awake during the trading day, even with the lid closed, then lets it sleep again.

Weekdays from 8:30 to 17:00 New York time (7:30 AM to 4 PM in Memphis): that covers the morning research, the whole
US trading day, the sell before the close and the evening review. JARVIS only trades the US stock market, so nothing
he does needs the Mac after that.

It uses macOS's own `pmset disablesleep`, which needs a one-time setup so JARVIS may switch only that one setting
without a password: bash scripts/setup_awake.sh. Without it, this does nothing except tell her once how to set it up.
Turn it off with KEEP_AWAKE=off in .env.
"""
import datetime
import os
import re
import subprocess
import sys

PMSET = "/usr/bin/pmset"
_state = {"on": None, "warned": False, "battery_day": None}


def wanted(now):
    if os.environ.get("KEEP_AWAKE", "on").strip().lower() in ("off", "no", "0"):
        return False
    mins = now.hour * 60 + now.minute
    return now.weekday() < 5 and 8 * 60 + 30 <= mins < 17 * 60


def _set(on):
    r = subprocess.run(["sudo", "-n", PMSET, "-a", "disablesleep", "1" if on else "0"], capture_output=True, text=True, timeout=15)
    return r.returncode == 0


def battery():
    """(percent, on_battery) or (None, False)."""
    try:
        out = subprocess.run([PMSET, "-g", "batt"], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return None, False
    m = re.search(r"(\d+)%", out)
    return (int(m.group(1)) if m else None), ("Battery Power" in out or "discharging" in out)


def tick(push, now=None):
    if sys.platform != "darwin":
        return
    from zoneinfo import ZoneInfo
    now = now or datetime.datetime.now(ZoneInfo("America/New_York"))
    want = wanted(now)
    if want != _state["on"]:
        if _set(want):
            _state["on"] = want
        elif want and not _state["warned"]:
            _state["warned"] = True
            push("alert", "I can't stay awake when the lid is closed yet. Run this once in a new Terminal window: bash ~/jarvis/scripts/setup_awake.sh")
    if want and _state["on"]:
        pct, on_batt = battery()
        day = now.strftime("%Y-%m-%d")
        if on_batt and pct is not None and pct <= 20 and _state["battery_day"] != day:
            _state["battery_day"] = day
            push("alert", "Madam Swain, the Mac is on battery at %d%%. Please plug it in, or I will go to sleep when it runs out and stop watching your trades." % pct)


def release():
    """Let the Mac sleep normally again (used when JARVIS shuts down)."""
    if sys.platform == "darwin" and _state["on"]:
        _set(False)
        _state["on"] = False
