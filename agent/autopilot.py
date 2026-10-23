"""Autopilot: small, rule-based trades with the guardrails doing the protecting.

Off by default. It starts on the PRACTICE (paper) account with fake money. A LIVE account is locked until ALL of these are true:
  1. the practice autopilot has finished at least AUTO_GRADUATE_TRADES trades (20 by default) and they made money overall,
  2. .env has AUTO_ALLOW_LIVE=yes as well as the two lines that switch the broker to live,
  3. the profit guard is on.
It buys from the same "worth a look" scanner JARVIS already uses. It never shorts and never adds to a position.

Guardrails, every one checked before every buy:
  * a stop loss at the broker on every buy, so it still sells if JARVIS or the computer is asleep
  * the profit guard (in watch.py) sells for a loss or when a winner gives back too much of its best profit
  * stops for the day when today's finished trades lost more than they won ("losses bigger than wins")
  * stops for the day once the daily goal is reached, so a good day is kept
  * stops for the day at a dollar loss limit and a percent loss limit, whichever comes first
  * pauses itself completely if, after enough trades, the system is losing money overall
  * sells everything it bought shortly before the close
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


def _flag(name, default="on"):
    return (os.environ.get(name, "") or default).strip().lower() not in ("off", "no", "0", "false")


def limits():
    return {
        "max_positions": int(_num("AUTO_MAX_POSITIONS", 2)),
        "trade_pct": _num("AUTO_TRADE_PCT", 25.0),          # share of the account per trade, also capped by the per-order limit
        "daily_loss_pct": _num("AUTO_DAILY_LOSS_PCT", 2.0),  # stop buying for the day if the account is down this much
        "daily_loss": _num("AUTO_DAILY_LOSS", 5.0),          # ...or down this many dollars, whichever comes first
        "daily_goal": _num("AUTO_DAILY_GOAL", 10.0),         # stop buying for the day once up this many dollars, to keep it
        "stop_when_behind": _flag("AUTO_STOP_WHEN_BEHIND"),  # stop for the day when today's losses are bigger than today's wins
        "max_trades": int(_num("AUTO_MAX_TRADES", 3)),       # buys per day
        "wait_min": int(_num("AUTO_WAIT_MIN", 15)),          # no buys in the first minutes after the open
        "flatten_min": int(_num("AUTO_FLATTEN_MIN", 10)),    # sell what it bought this many minutes before the close
        "min_move": _num("AUTO_MIN_MOVE", 2.0),              # percent up on the day
        "min_rvol": _num("AUTO_MIN_RVOL", 1.5),              # volume must really be above normal
        "stop_pct": _num("GUARD_MAX_LOSS", 3.0),             # the broker-side stop sits this far under the entry price
        "graduate_trades": int(_num("AUTO_GRADUATE_TRADES", 20)),
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


def _guard_on():
    import watch
    return watch.guard_enabled()


def graduated():
    return bool(_load().get("graduated"))


def live_ready():
    """(True, '') when a live account may run autopilot, otherwise (False, the plain reason)."""
    lim = limits()
    if not graduated():
        return False, ("Live autopilot is locked until the practice autopilot has finished %d trades and made money overall. "
                       "That proves the rules work before real money is used." % lim["graduate_trades"])
    if os.environ.get("AUTO_ALLOW_LIVE", "").strip().lower() != "yes":
        return False, "The practice results passed, but live autopilot also needs AUTO_ALLOW_LIVE=yes in .env, so that turning it on is your decision."
    if not _guard_on():
        return False, "Live autopilot needs the profit guard on. Add PROFIT_GUARD=on to .env."
    return True, ""


def allowed():
    if not broker.configured():
        return False
    return broker.mode() == "paper" or live_ready()[0]


def is_on():
    """True only when she switched it on AND the account is allowed to run it."""
    return bool(_load().get("on")) and allowed()


def _rules_text(lim):
    return ("buys only when a stock is up %.0f%% or more on %.1fx normal volume, at most %d buys a day and %d open positions, about %.0f%% of the account per buy "
            "(never over your $%.0f per-order limit). Every buy gets a stop loss at the broker %.0f%% under the price, and the profit guard sells a winner that gives back too much. "
            "I stop buying for the day when today's losses are bigger than today's wins, when the day is up $%.0f (to keep it), or when it is down $%.0f or %.0f%%. "
            "I sell what I bought %d minutes before the close" % (
                lim["min_move"], lim["min_rvol"], lim["max_trades"], lim["max_positions"], lim["trade_pct"], broker.max_order(), lim["stop_pct"],
                lim["daily_goal"], lim["daily_loss"], lim["daily_loss_pct"], lim["flatten_min"]))


def set_on(on):
    if on and (not broker.configured()):
        return False, "I can't start autopilot yet, because no practice account is connected."
    if on and broker.mode() != "paper":
        ok, why = live_ready()
        if not ok:
            return False, why
    if on and os.environ.get("PROFIT_GUARD", "").strip().lower() == "off":
        return False, "Autopilot needs the profit guard on, because the guard is what sells losers. Turn PROFIT_GUARD back on first."
    st = _load()
    st["on"] = bool(on)
    if on:
        st.pop("paused", None)
    _save(st)
    if on:
        lim = limits()
        where = "practice account, fake money" if broker.mode() == "paper" else "LIVE account, real money"
        return True, "Autopilot is on, %s. Rules: %s. Say 'autopilot off' any time." % (where, _rules_text(lim))
    return True, "Autopilot is off. I will not place any orders on my own."


def status():
    st = _load()
    day = st.get("day")
    today = datetime.date.today().isoformat()
    n = st.get("count", 0) if day == today else 0
    return {"on": is_on(), "mode": broker.mode() if broker.configured() else "not connected", "buys_today": n,
            "holding": sorted(st.get("bought", [])) if day == today else [], "done_for_day": st.get("done_why") if st.get("done_day") == today else None,
            "paused": st.get("paused"), "graduated": bool(st.get("graduated")), "live_ready": live_ready()}


def _minutes_since_open(now):
    return now.hour * 60 + now.minute - (9 * 60 + 30)


def day_stop(acct, closed_today, lim=None):
    """Why to stop buying for the rest of today, or None. closed_today: {'pl': $, 'wins': $, 'losses': $ (negative), 'n': trades}."""
    lim = lim or limits()
    equity = float(acct.get("equity", 0) or 0)
    today = float(acct.get("today", 0) or 0)
    if equity > 0 and today <= -equity * lim["daily_loss_pct"] / 100.0:
        return "the account is down %.0f%% today" % lim["daily_loss_pct"]
    if today <= -lim["daily_loss"]:
        return "the account is down $%.2f today, past the $%.0f daily loss limit" % (-today, lim["daily_loss"])
    if today >= lim["daily_goal"] or closed_today.get("pl", 0.0) >= lim["daily_goal"]:
        return "today reached the $%.0f goal, so I am keeping it" % lim["daily_goal"]
    if lim["stop_when_behind"] and closed_today.get("n", 0) and abs(closed_today.get("losses", 0.0)) > closed_today.get("wins", 0.0):
        return "today's losses ($%.2f) are bigger than today's wins ($%.2f)" % (abs(closed_today.get("losses", 0.0)), closed_today.get("wins", 0.0))
    return None


def decide(sym, d, rvol, acct, positions, state, orders_today, now, lim=None, closed_today=None):
    """Pure rule check. Returns (True, dollars, reason) or (False, 0, why_not). No network, so it can be tested."""
    lim = lim or limits()
    closed_today = closed_today or {}
    today = now.date().isoformat()
    bought = set(state.get("bought", [])) if state.get("day") == today else set()
    count = state.get("count", 0) if state.get("day") == today else 0
    held = {p["symbol"] for p in positions}
    since_open = _minutes_since_open(now)
    if state.get("paused"):
        return False, 0.0, "paused: " + str(state["paused"])
    if state.get("done_day") == today:
        return False, 0.0, "done for the day: " + str(state.get("done_why", ""))
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
    if acct.get("blocked"):
        return False, 0.0, "account is blocked"
    stop = day_stop(acct, closed_today, lim)
    if stop:
        return False, 0.0, "done for the day: " + stop
    size = round(min(broker.max_order(), equity * lim["trade_pct"] / 100.0, float(acct.get("cash", equity) or equity)), 2)
    if size < 1:
        return False, 0.0, "not enough cash for the smallest order"
    return True, size, "up %.1f%% on %.1fx volume" % (d["pct"], rvol)


def closed_today_from(score):
    """Today's finished trades from the scorecard, as wins and losses in dollars."""
    day = datetime.datetime.now(__import__("zoneinfo").ZoneInfo("America/New_York")).strftime("%Y-%m-%d")
    rows = [t for t in score.get("recent", []) if t.get("day") == day]
    wins = sum(t["pl"] for t in rows if t["pl"] > 0)
    losses = sum(t["pl"] for t in rows if t["pl"] <= 0)
    return {"pl": round(wins + losses, 2), "wins": round(wins, 2), "losses": round(losses, 2), "n": len(rows)}


def review(score, push=None):
    """Long-run check on the scorecard. Pauses autopilot when the system is losing money, and marks graduation on the
    practice account when it has proven itself. Returns the pause reason or None."""
    lim = limits()
    st = _load()
    changed = False
    # after a pause she can turn it back on; it re-checks only after 10 more finished trades
    recheck_at = max(lim["graduate_trades"], int(st.get("paused_at", 0)) + 10 if st.get("paused_at") else 0)
    if score.get("trades", 0) >= recheck_at and score.get("expectancy", 0) < 0 and not st.get("paused"):
        st["paused"] = "after %d trades the system loses about $%.2f per trade on average" % (score["trades"], -score["expectancy"])
        st["paused_at"] = score["trades"]
        st["on"] = False
        changed = True
        if push:
            push("autopilot", "Autopilot paused itself: %s. It will not trade again until you turn it back on. Next step: review the journal and change the rules." % st["paused"])
    if (broker.mode() == "paper" and not st.get("graduated") and score.get("trades", 0) >= lim["graduate_trades"]
            and score.get("expectancy", 0) > 0 and score.get("total", 0) > 0):
        st["graduated"] = {"date": time.strftime("%Y-%m-%d"), "trades": score["trades"], "win_rate": score.get("win_rate"), "total": score.get("total")}
        changed = True
        if push:
            push("autopilot", "Practice results passed: %d finished trades, %.0f%% won, up $%.2f overall. Live autopilot is now unlocked, "
                              "but it stays off until you add AUTO_ALLOW_LIVE=yes and switch the account to live. Start live at the same small size." % (
                                  score["trades"], score.get("win_rate", 0), score.get("total", 0)))
    if changed:
        _save(st)
    return st.get("paused")


def _label():
    return "practice account" if broker.mode() == "paper" else "LIVE account"


def consider(sym, d, rvol, push, now=None):
    """Called by the scanner when a stock is worth a look. Buys if every rule passes."""
    if not is_on():
        return False
    try:
        from zoneinfo import ZoneInfo
        import scorecard
        now = now or datetime.datetime.now(ZoneInfo("America/New_York"))
        try:
            sc = scorecard.fetch()
        except Exception:  # noqa: BLE001
            sc = {}
        if sc and review(sc, push):
            return False
        st = _load()
        acct = broker.account()
        closed = closed_today_from(sc) if sc else {}
        import swing
        if sym in swing.symbols():
            return False   # held as a swing trade
        day_pos = [p for p in broker.positions() if p["symbol"] not in swing.symbols()]
        ok, size, why = decide(sym, d, rvol, acct, day_pos, st, broker.orders_today(), now, closed_today=closed)
        if not ok:
            if why.startswith("done for the day") and st.get("done_day") != now.date().isoformat():
                st["done_day"], st["done_why"] = now.date().isoformat(), why[len("done for the day: "):]
                _save(st)
                push("autopilot", "Autopilot, %s: I am done buying for today, because %s. Anything still open stays protected by its stop and the profit guard." % (_label(), st["done_why"]))
            return False
        broker.place(sym, "buy", size)
        today = now.date().isoformat()
        if st.get("day") != today:
            st["leftover"] = sorted(set(st.get("leftover", [])) | (set(st.get("bought", [])) - set(st.get("flattened", []))))
            st["day"], st["count"], st["bought"], st["stops"], st["flattened"] = today, 0, [], {}, []
        st["count"] = st.get("count", 0) + 1
        st["bought"] = sorted(set(st.get("bought", [])) | {sym})
        _save(st)
        lim = limits()
        push("autopilot", "Autopilot, %s: I bought %s for about $%.2f because it is %s. A stop loss %.0f%% under the price goes in at the broker as soon as it fills, "
                          "and the profit guard sells if it hands back %.0f%% of its best gain. This is not a prediction. Say 'autopilot off' any time." % (
                              _label(), sym, size, why, lim["stop_pct"], _num("GUARD_GIVEBACK", 40.0)))
        return True
    except Exception as e:  # noqa: BLE001
        push("alert", "Autopilot wanted to buy %s but something went wrong: %s. It did nothing else." % (sym, str(e)[:120]))
        return False


def protect(positions, push):
    """Put a stop loss at the broker under every position autopilot bought today, once it has filled.
    It only ever sells shares already held, so it can only reduce risk."""
    st = _load()
    today = datetime.date.today().isoformat()
    if st.get("day") != today or not st.get("bought"):
        return
    stops = st.setdefault("stops", {})
    lim = limits()
    for p in positions:
        sym = p["symbol"]
        if sym not in st["bought"] or sym in stops or sym in st.get("flattened", []):
            continue
        entry = p.get("entry") or ((p.get("cost") or 0) / p["qty"] if p.get("qty") else 0)
        if not entry or p.get("qty", 0) <= 0:
            continue
        price = entry * (1 - lim["stop_pct"] / 100.0)
        try:
            o = broker.place_stop(sym, p["qty"], price)
            stops[sym] = str(o.get("id", "")) or "placed"
            _save(st)
            push("autopilot", "Autopilot, %s: %s is protected. A stop loss at $%.2f now sits at the broker, so it sells even if I am asleep." % (_label(), sym, price))
        except Exception as e:  # noqa: BLE001
            stops[sym] = "failed"
            _save(st)
            push("alert", "I could not put a stop loss at the broker for %s: %s. The profit guard still watches it while I am running." % (sym, str(e)[:120]))


def record_close(pos, reason, journal_path=None):
    """Write the finished trade to the journal so 'review my journal' includes autopilot's results."""
    st = _load()
    if pos["symbol"] not in set(st.get("bought", [])):
        return
    from pathlib import Path
    p = Path(journal_path) if journal_path else Path(__file__).resolve().parent.parent / "memory" / "trading" / "journal.jsonl"
    cost = pos.get("cost") or (pos["value"] - pos["pl"])
    risk = max(0.01, cost * _num("GUARD_MAX_LOSS", 3.0) / 100.0)
    rec = {"date": time.strftime("%Y-%m-%d"), "symbol": pos["symbol"], "side": "long", "entry": pos.get("entry", 0), "exit": 0, "stop": 0, "r": round(pos["pl"] / risk, 2),
           "setup": "autopilot (%s)" % ("practice" if broker.mode() == "paper" else "live"), "why": str(reason)[:200], "lesson": ""}
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")
    except Exception:
        pass


def sell_leftovers(positions, push, now=None):
    """If the computer slept through the close, sell anything autopilot bought on an earlier day, once the market is open.
    Only reduces risk, and never touches positions she opened herself."""
    st = _load()
    today = datetime.date.today().isoformat()
    old = set(st.get("leftover", []))
    if st.get("day") and st.get("day") != today:
        old |= set(st.get("bought", [])) - set(st.get("flattened", []))
    if not old:
        return
    held = {p["symbol"]: p for p in positions}
    for sym in sorted(old):
        p = held.get(sym)
        if p:
            try:
                broker.close_position(sym)
                record_close(p, "left over from an earlier day, sold at the open")
                push("autopilot", "Autopilot, %s: %s was still held from an earlier day, probably because the computer was asleep at the close, so I sold it. Result about %s$%.2f." % (
                    _label(), sym, "-" if p["pl"] < 0 else "+", abs(p["pl"])))
            except Exception as e:  # noqa: BLE001
                push("alert", "Autopilot tried to sell %s, left over from an earlier day, but failed: %s. Please check it." % (sym, str(e)[:100]))
                continue
        old.discard(sym)
    st = _load()
    st["leftover"] = sorted(old)
    if st.get("day") != today:
        st["flattened"] = sorted(set(st.get("flattened", [])) | set(st.get("bought", [])))
    _save(st)


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
                push("autopilot", "Autopilot, %s: sold %s before the close. Result about %s$%.2f. Next step: look at it in your journal." % (_label(), p["symbol"], "-" if p["pl"] < 0 else "+", abs(p["pl"])))
            except Exception as e:  # noqa: BLE001
                push("alert", "Autopilot tried to sell %s before the close but failed: %s. Please check it." % (p["symbol"], str(e)[:100]))
