"""Practice-account autopilot.

Off by default. It only ever runs on the PRACTICE (paper) account with fake money. If the broker mode is live,
every function here refuses, no matter what is switched on. It buys small, rule-based positions from the same
"worth a look" scanner JARVIS already uses, and the profit guard sells them. It never shorts and never adds.
"""
import datetime
import json
import os
import time

import broker

STATE_FILE = None   # set lazily so tests can point it somewhere else


def _path():
    from pathlib import Path
    return STATE_FILE or (Path(__file__).resolve().parent.parent / "memory" / "autopilot.json")


def _num(name, default):
    try:
        v = float(os.environ.get(name, "") or default)
        return v if v > 0 else default
    except ValueError:
        return default


def limits():
    return {
        "max_positions": int(_num("AUTO_MAX_POSITIONS", 2)),
        "trade_pct": _num("AUTO_TRADE_PCT", 25.0),          # share of the account per trade, also capped by the per-order limit
        "daily_loss_pct": _num("AUTO_DAILY_LOSS_PCT", 2.0),  # stop buying for the day if the account is down this much
        "max_trades": int(_num("AUTO_MAX_TRADES", 3)),       # buys per day
        "wait_min": int(_num("AUTO_WAIT_MIN", 15)),          # no buys in the first minutes after the open
        "flatten_min": int(_num("AUTO_FLATTEN_MIN", 10)),    # sell what it bought this many minutes before the close
        "min_move": _num("AUTO_MIN_MOVE", 2.0),              # percent up on the day
        "min_rvol": _num("AUTO_MIN_RVOL", 1.5),              # volume must really be above normal
    }


def _load():
    try:
        return json.loads(_path().read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save(st):
    try:
        p = _path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(st), encoding="utf-8")
    except Exception:
        pass


def is_on():
    """True only when she switched it on AND the account is the practice account."""
    return bool(_load().get("on")) and broker.configured() and broker.mode() == "paper"


def set_on(on):
    if on and (not broker.configured()):
        return False, "I can't start autopilot yet, because no practice account is connected."
    if on and broker.mode() != "paper":
        return False, "Autopilot only works on the practice account. Your account is set to live, so I will not turn it on."
    if on and os.environ.get("PROFIT_GUARD", "").strip().lower() == "off":
        return False, "Autopilot needs the profit guard on, because the guard is what sells losers. Turn PROFIT_GUARD back on first."
    st = _load()
    st["on"] = bool(on)
    _save(st)
    if on:
        lim = limits()
        return True, ("Autopilot is on, practice account only, fake money. Rules: buys only when a stock is up %.0f%% or more on %.1fx normal volume, at most %d buys a day and %d open positions, "
                      "about %.0f%% of the account per buy (never over your per-order limit), and it stops for the day if the account is down %.0f%%. The profit guard sells for losses and giveback, "
                      "and I sell what I bought %d minutes before the close. Say 'autopilot off' any time." % (lim["min_move"], lim["min_rvol"], lim["max_trades"], lim["max_positions"], lim["trade_pct"], lim["daily_loss_pct"], lim["flatten_min"]))
    return True, "Autopilot is off. I will not place any orders on my own."


def status():
    st = _load()
    day = st.get("day")
    today = datetime.date.today().isoformat()
    n = st.get("count", 0) if day == today else 0
    return {"on": is_on(), "mode": broker.mode() if broker.configured() else "not connected", "buys_today": n, "holding": sorted(st.get("bought", [])) if day == today else []}


def _minutes_since_open(now):
    return now.hour * 60 + now.minute - (9 * 60 + 30)


def decide(sym, d, rvol, acct, positions, state, orders_today, now, lim=None):
    """Pure rule check. Returns (True, dollars, reason) or (False, 0, why_not). No network, so it can be tested."""
    lim = lim or limits()
    today = now.date().isoformat()
    bought = set(state.get("bought", [])) if state.get("day") == today else set()
    count = state.get("count", 0) if state.get("day") == today else 0
    held = {p["symbol"] for p in positions}
    since_open = _minutes_since_open(now)
    if now.weekday() >= 5 or since_open < lim["wait_min"] or since_open >= 390 - lim["flatten_min"]:
        return False, 0.0, "outside my trading window"
    if d["pct"] < lim["min_move"]:
        return False, 0.0, "not up enough"
    if not rvol or rvol < lim["min_rvol"]:
        return False, 0.0, "volume is not above normal"
    if sym in held or sym in bought:
        return False, 0.0, "already traded today"
    if len(held) >= lim["max_positions"]:
        return False, 0.0, "at the position limit"
    if count >= lim["max_trades"]:
        return False, 0.0, "reached today's buy limit"
    if orders_today >= broker.max_orders_per_day():
        return False, 0.0, "reached the daily order limit"
    equity = float(acct.get("equity", 0) or 0)
    if equity <= 0:
        return False, 0.0, "no account value"
    if float(acct.get("today", 0) or 0) <= -equity * lim["daily_loss_pct"] / 100.0:
        return False, 0.0, "down too much today"
    if acct.get("blocked"):
        return False, 0.0, "account is blocked"
    size = round(min(broker.max_order(), equity * lim["trade_pct"] / 100.0, float(acct.get("cash", equity) or equity)), 2)
    if size < 1:
        return False, 0.0, "not enough cash for the smallest order"
    return True, size, "up %.1f%% on %.1fx volume" % (d["pct"], rvol)


def consider(sym, d, rvol, push, now=None):
    """Called by the scanner when a stock is worth a look. Buys on the practice account if every rule passes."""
    if not is_on():
        return False
    try:
        from zoneinfo import ZoneInfo
        now = now or datetime.datetime.now(ZoneInfo("America/New_York"))
        st = _load()
        acct = broker.account()
        ok, size, why = decide(sym, d, rvol, acct, broker.positions(), st, broker.orders_today(), now)
        if not ok:
            return False
        broker.place(sym, "buy", size)
        today = now.date().isoformat()
        if st.get("day") != today:
            st["day"], st["count"], st["bought"] = today, 0, []
        st["count"] = st.get("count", 0) + 1
        st["bought"] = sorted(set(st.get("bought", [])) | {sym})
        _save(st)
        lim = limits()
        push("autopilot", "Autopilot, practice account: I bought %s for about $%.2f because it is %s. If it falls %.0f%% I sell, and the profit guard sells if it hands back 40%% of its best gain. "
                          "This is a test with fake money, not a prediction. Next step: I will report when it sells, and you can say 'autopilot off' any time." % (sym, size, why, _num("GUARD_MAX_LOSS", 3.0)))
        return True
    except Exception as e:  # noqa: BLE001
        push("alert", "Autopilot wanted to buy %s but something went wrong: %s. It did nothing else." % (sym, str(e)[:120]))
        return False


def record_close(pos, reason, journal_path=None):
    """Write the finished practice trade to the journal so 'review my journal' includes autopilot's results."""
    st = _load()
    if pos["symbol"] not in set(st.get("bought", [])):
        return
    from pathlib import Path
    p = Path(journal_path) if journal_path else Path(__file__).resolve().parent.parent / "memory" / "trading" / "journal.jsonl"
    cost = pos.get("cost") or (pos["value"] - pos["pl"])
    risk = max(0.01, cost * _num("GUARD_MAX_LOSS", 3.0) / 100.0)
    rec = {"date": time.strftime("%Y-%m-%d"), "symbol": pos["symbol"], "side": "long", "entry": 0, "exit": 0, "stop": 0, "r": round(pos["pl"] / risk, 2),
           "setup": "autopilot (practice)", "why": str(reason)[:200], "lesson": ""}
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")
    except Exception:
        pass


def flatten_due(now):
    since_open = _minutes_since_open(now)
    return now.weekday() < 5 and 390 - limits()["flatten_min"] <= since_open < 390


def flatten(positions, push):
    """Near the close: sell what autopilot bought. Only reduces risk. Never touches positions she opened herself."""
    if not is_on():
        return
    st = _load()
    mine = set(st.get("bought", [])) if st.get("day") == datetime.date.today().isoformat() else set()
    for p in positions:
        if p["symbol"] in mine and p["symbol"] not in st.get("flattened", []):
            try:
                broker.close_position(p["symbol"])
                record_close(p, "sold before the close")
                st.setdefault("flattened", []).append(p["symbol"])
                _save(st)
                push("autopilot", "Autopilot, practice account: sold %s before the close. Result about %s$%.2f. Next step: look at it in your journal." % (p["symbol"], "-" if p["pl"] < 0 else "+", abs(p["pl"])))
            except Exception as e:  # noqa: BLE001
                push("alert", "Autopilot tried to sell %s before the close but failed: %s. Please check it." % (p["symbol"], str(e)[:100]))
