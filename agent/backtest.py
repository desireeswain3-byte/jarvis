"""Backtester: replays past trading days, 5 minutes at a time, with the same rules (strategies.py), trade size and daily
limits the autopilot uses, so she can see what a rule would have done before he trades it.

Honest by design:
  * a signal at the close of a bar is bought at the OPEN of the next bar, plus a little slippage
  * if a bar touches both the stop and the target, it counts as a loss
  * if a bar opens below the stop, the loss is taken at that worse open price
  * everything still open is sold at the close of the 3:45 to 3:50 PM bar, like the live autopilot
Past results never promise future ones; this only shows which rules held up and which did not.
"""
import datetime
import json
import time
from zoneinfo import ZoneInfo

import strategies

ET = ZoneInfo("America/New_York")
SLIP = 0.0005          # 0.05% worse on every buy and sell
FLAT_AT = datetime.time(15, 50)


def _limits():
    import autopilot
    lim = autopilot.limits()
    import broker
    return {"max_positions": lim["max_positions"], "max_trades": lim["max_trades"], "trade_pct": lim["trade_pct"],
            "max_order": broker.max_order(), "daily_loss": lim["daily_loss"], "daily_loss_pct": lim["daily_loss_pct"], "daily_goal": lim["daily_goal"]}


def simulate_day(day_bars, prevs, name, params, equity, lim):
    """day_bars: {symbol: [bars oldest first, t in New York time]}. Returns (trades, equity at the end)."""
    times = sorted({b["t"] for bars in day_bars.values() for b in bars})
    idx = {s: {b["t"]: i for i, b in enumerate(bars)} for s, bars in day_bars.items()}
    open_pos, pending, trades, traded = {}, {}, [], set()
    day_pl = 0.0
    stopped = False

    def close(sym, px, why, t):
        nonlocal equity, day_pl
        pos = open_pos.pop(sym)
        px = px * (1 - SLIP)
        pl = (px - pos["entry"]) * pos["qty"]
        equity += pl
        day_pl += pl
        trades.append({"symbol": sym, "in": pos["t"].strftime("%H:%M"), "out": t.strftime("%H:%M"), "entry": round(pos["entry"], 4), "exit": round(px, 4),
                       "pl": round(pl, 4), "r": round(pl / pos["risk_d"], 2) if pos["risk_d"] else 0.0, "why": why, "setup": pos["why"]})

    for t in times:
        # 1. fill orders placed at the previous bar's close, at this bar's open
        for sym in list(pending):
            i = idx[sym].get(t)
            if i is None:
                continue
            plan = pending.pop(sym)
            b = day_bars[sym][i]
            entry = b["o"] * (1 + SLIP)
            if entry <= plan["stop"]:
                continue                                  # it gapped through the stop before we got in: skip
            size = min(lim["max_order"], equity * lim["trade_pct"] / 100.0, equity)
            if size < 1:
                continue
            shift = entry - plan["entry"]
            open_pos[sym] = {"entry": entry, "qty": size / entry, "stop": plan["stop"], "target": plan["target"] + shift, "t": t,
                             "risk_d": (entry - plan["stop"]) * size / entry, "why": plan["why"]}
        # 2. exits on this bar
        for sym in list(open_pos):
            i = idx[sym].get(t)
            if i is None:
                continue
            b, pos = day_bars[sym][i], open_pos[sym]
            if b["o"] <= pos["stop"]:
                close(sym, b["o"], "opened below the stop", t)
            elif b["l"] <= pos["stop"]:
                close(sym, pos["stop"], "stop", t)
            elif b["h"] >= pos["target"]:
                close(sym, pos["target"], "target", t)
            elif (t + datetime.timedelta(minutes=5)).time() >= FLAT_AT:
                close(sym, b["c"], "sold before the close", t)
        # 3. daily stops, the same as live
        if not stopped and (day_pl <= -min(lim["daily_loss"], equity * lim["daily_loss_pct"] / 100.0) or day_pl >= lim["daily_goal"]):
            stopped = True
        if stopped:
            continue
        # 4. new signals at this bar's close
        for sym, bars in day_bars.items():
            i = idx[sym].get(t)
            if i is None or sym in traded or sym in open_pos or sym in pending:
                continue
            if len(open_pos) + len(pending) >= lim["max_positions"] or len(traded) >= lim["max_trades"]:
                break
            plan = strategies.signal(name, bars[:i + 1], prevs.get(sym), params)
            if plan:
                pending[sym] = plan
                traded.add(sym)
    for sym in list(open_pos):                            # data ended early: sell at the last price
        bars = day_bars[sym]
        close(sym, bars[-1]["c"], "end of data", bars[-1]["t"])
    return trades, equity


def run(data, name, params=None, start_equity=200.0, lim=None):
    """data: {"days": [{"date", "bars": {sym: [...]}, "prev": {sym: {h,l,c,v}}}]} oldest first."""
    lim = lim or _limits()
    equity, all_trades, curve = start_equity, [], []
    for d in data["days"]:
        tr, equity = simulate_day(d["bars"], d["prev"], name, params, equity, lim)
        for x in tr:
            x["date"] = d["date"]
        all_trades += tr
        curve.append(round(equity, 2))
    return stats(all_trades, start_equity, curve, name, params)


def stats(trades, start, curve, name="", params=None):
    n = len(trades)
    wins = [t["pl"] for t in trades if t["pl"] > 0]
    losses = [t["pl"] for t in trades if t["pl"] <= 0]
    peak, dd = start, 0.0
    for e in curve:
        peak = max(peak, e)
        dd = max(dd, peak - e)
    total = sum(t["pl"] for t in trades)
    return {"strategy": name, "params": strategies.params_for(name, params), "trades": n, "wins": len(wins), "win_rate": round(len(wins) / n * 100, 1) if n else 0.0,
            "avg_win": round(sum(wins) / len(wins), 3) if wins else 0.0, "avg_loss": round(sum(losses) / len(losses), 3) if losses else 0.0,
            "expectancy": round(total / n, 4) if n else 0.0, "avg_r": round(sum(t["r"] for t in trades) / n, 3) if n else 0.0,
            "total": round(total, 2), "max_drawdown": round(dd, 2), "days": len(curve), "trades_per_day": round(n / len(curve), 2) if curve else 0.0,
            "end_equity": curve[-1] if curve else start, "recent": trades[-8:]}


# ---------------- getting the past prices (on her Mac, from Alpaca, cached) ----------------

def _parse(rows):
    out = []
    for b in rows or []:
        t = datetime.datetime.fromisoformat(str(b["t"]).replace("Z", "+00:00")).astimezone(ET).replace(tzinfo=None)
        out.append({"t": t, "o": float(b["o"]), "h": float(b["h"]), "l": float(b["l"]), "c": float(b["c"]), "v": float(b["v"])})
    return out


def fetch(symbols, days=40, cache_dir=None):
    """The last `days` trading days of 5 minute bars and the daily bars, for these symbols. Cached in memory/backtest_cache."""
    import urllib.parse
    from pathlib import Path
    import broker
    import memory
    cache = Path(cache_dir) if cache_dir else memory.MEM / "backtest_cache"
    cache.mkdir(parents=True, exist_ok=True)
    key = cache / ("%s-%d-%s.json" % (datetime.date.today().isoformat(), days, abs(hash(",".join(sorted(symbols)))) % 10**8))
    if key.exists():
        return _load(key)
    syms = sorted({s.upper() for s in symbols})
    start = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=int(days * 1.6) + 5)).strftime("%Y-%m-%dT00:00:00Z")
    end = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=20)).strftime("%Y-%m-%dT%H:%M:%SZ")

    def pull(tf):
        got, token = {}, None
        for _ in range(400):
            q = "/v2/stocks/bars?symbols=%s&timeframe=%s&start=%s&end=%s&limit=10000&adjustment=split&feed=iex%s" % (
                urllib.parse.quote(",".join(syms), safe=","), tf, start, end, ("&page_token=" + urllib.parse.quote(token, safe="")) if token else "")
            page = broker._req("GET", q, host="https://data.alpaca.markets") or {}
            for s, rows in (page.get("bars") or {}).items():
                got.setdefault(s, []).extend(rows or [])
            token = page.get("next_page_token")
            if not token:
                break
            time.sleep(0.35)       # stay well under the free data limit
        return {s: _parse(r) for s, r in got.items()}

    m5, d1 = pull("5Min"), pull("1Day")
    data = build(m5, d1, days)
    try:
        key.write_text(json.dumps(data, default=str), encoding="utf-8")
    except OSError:
        pass
    return data


def build(m5, d1, days):
    """Arrange bars into trading days (regular hours only) with yesterday's daily bar for each symbol."""
    by_day = {}
    for s, bars in m5.items():
        for b in bars:
            tm = b["t"].time()
            if datetime.time(9, 30) <= tm < datetime.time(16, 0):
                by_day.setdefault(b["t"].date().isoformat(), {}).setdefault(s, []).append(b)
    daily = {s: sorted(bars, key=lambda b: b["t"]) for s, bars in d1.items()}
    out = []
    for day in sorted(by_day)[-days:]:
        prev = {}
        for s in by_day[day]:
            before = [b for b in daily.get(s, []) if b["t"].date().isoformat() < day]
            if before:
                p = before[-1]
                prev[s] = {"h": p["h"], "l": p["l"], "c": p["c"], "v": p["v"]}
        out.append({"date": day, "bars": {s: sorted(v, key=lambda b: b["t"]) for s, v in by_day[day].items()}, "prev": prev})
    return {"days": out}


def _load(path):
    raw = json.loads(path.read_text(encoding="utf-8"))
    for d in raw["days"]:
        for s, bars in d["bars"].items():
            for b in bars:
                b["t"] = datetime.datetime.fromisoformat(b["t"])
    return raw


def split(data, frac=0.7):
    """First part to choose a rule, last part to check it still worked on days it was not chosen on."""
    n = len(data["days"])
    k = max(1, int(n * frac))
    return {"days": data["days"][:k]}, {"days": data["days"][k:]}
