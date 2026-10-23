"""Swing mode: holds a trade for days instead of selling before the close. Off by default.

Day trading stays the main plan; swing mode is extra. It follows memory/trading/13-swing-trading.md:
  * only when SPY is above its 50 day average
  * buys late in the day (3:30 to 3:50 PM New York time) on a pullback to a rising 20 day average that closes up,
    or a breakout above the 20 day high on heavy volume
  * stop under the recent lows, skipped if that is more than 8% away; at most 1 swing trade at a time by default
  * every morning it puts the stop back in at Alpaca, because fractional-share stops only last until that day's close
  * once up 1R the stop moves to the entry; it takes profit at 2R; it sells after 10 trading days if nothing happened
It starts on the practice account. A live account needs AUTO_SWING_ALLOW_LIVE=yes and the day autopilot's live unlock.
The profit guard and the day autopilot leave swing trades alone; swing mode manages its own exits.
"""
import datetime
import json
import os
import time

import broker

STATE_FILE = None


def _path():
    from pathlib import Path
    return STATE_FILE or (Path(__file__).resolve().parent.parent / "memory" / "swing.json")


def _num(name, default):
    try:
        v = float(os.environ.get(name, "") or default)
        return v if v > 0 else default
    except ValueError:
        return default


def limits():
    return {"max_positions": int(_num("AUTO_SWING_MAX", 1)), "trade_pct": _num("AUTO_SWING_PCT", 20.0), "max_stop": _num("SWING_MAX_STOP", 8.0),
            "min_stop": _num("SWING_MIN_STOP", 3.0), "target_r": _num("SWING_TARGET_R", 2.0), "max_days": int(_num("SWING_MAX_DAYS", 10)),
            "min_rvol": _num("SWING_MIN_RVOL", 1.5)}


def _load():
    try:
        return json.loads(_path().read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _save(st):
    try:
        p = _path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(st, indent=1), encoding="utf-8")
    except OSError:
        pass


def allowed():
    if not broker.configured():
        return False
    if broker.mode() == "paper":
        return True
    import autopilot
    return os.environ.get("AUTO_SWING_ALLOW_LIVE", "").strip().lower() == "yes" and autopilot.live_ready()[0]


def is_on():
    return bool(_load().get("on")) and allowed()


def symbols():
    """Symbols swing mode is holding, so the profit guard and the day autopilot leave them alone."""
    return set(_load().get("positions", {}))


def _label():
    return "practice account" if broker.mode() == "paper" else "LIVE account"


def set_on(on):
    if on and not broker.configured():
        return False, "I can't start swing mode yet, because no practice account is connected."
    if on and not allowed():
        return False, "Swing mode only runs on the practice account for now. On live it needs AUTO_SWING_ALLOW_LIVE=yes and the autopilot's practice results to pass first."
    st = _load()
    st["on"] = bool(on)
    _save(st)
    if not on:
        held = sorted(st.get("positions", {}))
        return True, "Swing mode is off. I will not open new swing trades." + (" I will keep managing %s until it is sold." % ", ".join(held) if held else "")
    lim = limits()
    return True, ("Swing mode is on, %s. Day trading stays the main plan. Rules: only when SPY is above its 50 day average, I buy late in the day on a pullback to a rising "
                  "20 day average or a breakout on heavy volume, at most %d swing trade%s at a time, about %.0f%% of the account each (never over your per-order limit). "
                  "The stop goes under the recent lows and is put back in every morning. Once up 1R the stop moves to break even, I take profit at %gR, "
                  "and I sell after %d trading days if nothing happened. Overnight gaps can skip past a stop, so sizes stay small." % (
                      _label(), lim["max_positions"], "" if lim["max_positions"] == 1 else "s", lim["trade_pct"], lim["target_r"], lim["max_days"]))


def status():
    st = _load()
    pos = st.get("positions", {})
    return {"on": is_on(), "positions": {k: {"entry": v.get("entry"), "stop": v.get("stop"), "since": v.get("opened"), "setup": v.get("setup")} for k, v in pos.items()}}


# ---------------- the rules (pure, testable) ----------------

def _sma(xs, n):
    return sum(xs[-n:]) / n if len(xs) >= n else None


def market_ok(spy_bars):
    c = [b["c"] for b in spy_bars]
    s50 = _sma(c, 50)
    return bool(s50 and c[-1] > s50)


def setup(bars, lim=None):
    """('pullback' or 'breakout', stop) when today's daily chart fits a rule, else (None, why)."""
    lim = lim or limits()
    if len(bars) < 55:
        return None, "not enough history"
    c = [b["c"] for b in bars]; h = [b["h"] for b in bars]; lo = [b["l"] for b in bars]; v = [b["v"] for b in bars]
    last = c[-1]
    s20, s50, s20_before = _sma(c, 20), _sma(c, 50), _sma(c[:-5], 20)
    if not (last > s50 and s20 > s50 and s20 > s20_before):
        return None, "not in an uptrend"
    kind = None
    avg_v = sum(v[-21:-1]) / 20
    if last > max(h[-21:-1]) and avg_v and v[-1] >= lim["min_rvol"] * avg_v:
        kind = "breakout"
    elif min(lo[-3:]) <= s20 * 1.01 and last > s20 and last > c[-2]:
        kind = "pullback"
    if not kind:
        return None, "no setup today"
    stop = min(lo[-5:]) * 0.995
    risk = (last - stop) / last * 100
    if risk < lim["min_stop"]:
        stop = last * (1 - lim["min_stop"] / 100)
    elif risk > lim["max_stop"]:
        return None, "stop would be %.1f%% away, too loose" % risk
    return kind, round(stop, 2)


def trading_days(since_iso, today):
    d = datetime.date.fromisoformat(since_iso)
    n = 0
    while d < today:
        d += datetime.timedelta(days=1)
        if d.weekday() < 5:
            n += 1
    return n


def plan_exit(rec, price, today, lim=None):
    """What to do with a held swing trade at this price: ('sell', why), ('stop', new_stop) or ('hold', None)."""
    lim = lim or limits()
    entry, stop0, stop = rec["entry"], rec["stop0"], rec["stop"]
    r = max(0.01, entry - stop0)
    if price <= stop:
        return "sell", "it fell to the stop at $%.2f" % stop
    if price >= entry + lim["target_r"] * r:
        return "sell", "it reached the %gR profit target" % lim["target_r"]
    if trading_days(rec["opened"], today) >= lim["max_days"]:
        return "sell", "%d trading days passed without the move" % lim["max_days"]
    new = stop
    if price >= entry + r:
        new = max(new, round(entry, 2))                 # up 1R: it can no longer turn into a loss
    if price >= entry + 1.5 * r:
        new = max(new, round(entry + 0.5 * r, 2))       # up 1.5R: lock in half a unit
    return ("stop", new) if new > stop else ("hold", None)


# ---------------- running it ----------------

def _close(sym, rec, p, why, push, st):
    try:
        broker.close_position(sym)
    except broker.BrokerError as e:
        push("alert", "Swing mode wanted to sell %s (%s) but the broker refused: %s. Please check it." % (sym, why, e))
        return
    _journal(sym, rec, p.get("pl", 0.0) if p else 0.0, why)
    st["positions"].pop(sym, None)
    _save(st)
    pl = p.get("pl", 0.0) if p else 0.0
    push("autopilot", "Swing mode, %s: sold %s because %s. Result about %s$%.2f." % (_label(), sym, why, "-" if pl < 0 else "+", abs(pl)))


def _journal(sym, rec, pl, why):
    from pathlib import Path
    p = Path(__file__).resolve().parent.parent / "memory" / "trading" / "journal.jsonl"
    risk = max(0.01, (rec["entry"] - rec["stop0"]) * rec.get("qty", 0) or 0.01)
    line = {"date": time.strftime("%Y-%m-%d"), "symbol": sym, "side": "long", "entry": rec["entry"], "exit": 0, "stop": rec["stop0"], "r": round(pl / risk, 2),
            "setup": "swing %s (%s)" % (rec.get("setup", ""), "practice" if broker.mode() == "paper" else "live"), "why": why[:200], "lesson": ""}
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps(line) + "\n")
    except OSError:
        pass


def manage(positions, push, now):
    """Every few seconds while the market is open: exits, trailing, and the morning stop at the broker."""
    st = _load()
    held = st.get("positions", {})
    if not held:
        return
    by = {p["symbol"]: p for p in positions}
    today = now.date()
    for sym, rec in list(held.items()):
        p = by.get(sym)
        if not p:
            if rec.get("filled"):     # it was held and now it is gone: the stop at the broker sold it
                _journal(sym, rec, -(rec["entry"] - rec["stop"]) * rec.get("qty", 0), "the stop at the broker sold it")
                st["positions"].pop(sym, None)
                _save(st)
                push("autopilot", "Swing mode, %s: the stop at the broker sold %s near $%.2f." % (_label(), sym, rec["stop"]))
            elif time.time() - rec.get("t", 0) > 600:
                st["positions"].pop(sym, None)   # the buy never filled
                _save(st)
            continue
        if not rec.get("filled"):
            rec["filled"] = True
            rec["qty"] = p["qty"]
            if p.get("entry"):
                shift = p["entry"] - rec["entry"]   # use the real fill price, keep the same distance to the stop
                rec["entry"], rec["stop0"], rec["stop"] = p["entry"], round(rec["stop0"] + shift, 2), round(rec["stop"] + shift, 2)
        rec["qty"] = p["qty"]
        price = p["value"] / p["qty"] if p.get("qty") else 0
        if not price:
            continue
        act, val = plan_exit(rec, price, today)
        if act == "sell":
            _close(sym, rec, p, val, push, st)
            continue
        moved = act == "stop"
        if moved:
            rec["stop"] = val
            push("autopilot", "Swing mode, %s: %s is up, so I raised its stop to $%.2f." % (_label(), sym, val))
        if moved or rec.get("stop_day") != today.isoformat():
            for o in broker.open_orders(sym):
                if o["side"] == "sell":
                    try:
                        broker.cancel_order(o["id"])
                    except broker.BrokerError:
                        pass
            try:
                broker.place_stop(sym, p["qty"], rec["stop"])
                rec["stop_day"] = today.isoformat()
            except broker.BrokerError as e:
                if rec.get("stop_warn") != today.isoformat():
                    rec["stop_warn"] = today.isoformat()
                    push("alert", "I could not put the swing stop back in for %s: %s. I am still watching it while I run." % (sym, str(e)[:120]))
        _save(st)


def scan_due(now, st):
    mins = now.hour * 60 + now.minute
    return now.weekday() < 5 and 15 * 60 + 30 <= mins < 15 * 60 + 50 and st.get("scanned") != now.date().isoformat()


def scan(push, now, watchlist):
    """Once a day, late in the session: look for one swing setup and buy it."""
    st = _load()
    if not scan_due(now, st):
        return
    st["scanned"] = now.date().isoformat()
    _save(st)
    lim = limits()
    held = st.setdefault("positions", {})
    if len(held) >= lim["max_positions"]:
        return
    data = broker.bars(["SPY"] + list(watchlist), 120)
    if not market_ok(data.get("SPY", [])):
        push("autopilot", "Swing mode: SPY is below its 50 day average, so no new swing trades today.")
        return
    acct = broker.account()
    if acct.get("blocked"):
        return
    owned = {p["symbol"] for p in broker.positions()}
    picks = []
    for sym in watchlist:
        if sym in ("SPY", "QQQ", "DIA", "IWM") or sym in owned or sym in held:
            continue
        kind, stop = setup(data.get(sym, []), lim)
        if kind:
            last = data[sym][-1]["c"]
            picks.append(((last - stop) / last, sym, kind, stop, last))
    if not picks:
        return
    picks.sort()                       # the tightest stop first
    _, sym, kind, stop, last = picks[0]
    size = round(min(broker.max_order(), acct["equity"] * lim["trade_pct"] / 100.0, acct.get("cash", acct["equity"])), 2)
    if size < 1:
        return
    try:
        broker.place(sym, "buy", size)
    except broker.BrokerError as e:
        push("alert", "Swing mode wanted to buy %s but the broker refused: %s" % (sym, e))
        return
    held[sym] = {"opened": now.date().isoformat(), "entry": last, "stop0": stop, "stop": stop, "setup": kind, "t": time.time()}
    _save(st)
    r = last - stop
    push("autopilot", "Swing mode, %s: I bought %s for about $%.2f, a %s setup. Stop $%.2f, profit target about $%.2f, and I will hold it up to %d trading days. "
                      "Not a prediction. Say 'swing mode off' to stop new swing trades." % (_label(), sym, size, kind, stop, last + lim["target_r"] * r, lim["max_days"]))


def tick(push, now, watchlist):
    if not broker.configured():
        return
    st = _load()
    if not st.get("positions") and not is_on():
        return
    manage(broker.positions(), push, now)
    if is_on():
        scan(push, now, watchlist)
