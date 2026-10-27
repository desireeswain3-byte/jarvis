"""Entry rules, shared by the live autopilot and the backtester, so what gets tested is exactly what gets traded.

Every rule looks only at COMPLETED 5 minute bars of today (plus yesterday's high, low and close), and returns either
None or a plan: entry price, stop, target and a plain-words reason. Pure functions, no network.

  momentum : the original rule. Up 2% or more on the day with volume well above normal.
  orb15    : from @bagborrowtrade. Mark the first 15 minutes' high. Wait until a 15 minute candle CLOSES above it
             (a wick through is not a break) on decent volume. Stop under that candle, target 2R.
  engulf   : from DE'JA and the engulfing candle videos. After a 15 minute close above a key level (the first
             15 minutes' high or yesterday's high), buy a bullish engulfing 5 minute candle on above-normal volume.
             Stop under the engulfing candle, target 2R.
"""
import datetime

NAMES = ("momentum", "orb15", "engulf")
LABELS = {"momentum": "momentum (up 2% on heavy volume)", "orb15": "15 minute opening range close",
          "engulf": "engulfing candle after a 15 minute close above a key level"}

DEFAULTS = {
    "momentum": {"min_move": 2.0, "min_rvol": 1.5, "stop_pct": 3.0, "target_r": 2.0},
    "orb15": {"vol_mult": 1.0, "target_r": 2.0, "min_risk": 0.3, "max_risk": 3.0},
    "engulf": {"vol_mult": 1.2, "target_r": 2.0, "min_risk": 0.3, "max_risk": 3.0},
}

OPEN = datetime.time(9, 30)
FIRST_ENTRY = {"momentum": datetime.time(9, 45), "orb15": datetime.time(9, 45), "engulf": datetime.time(9, 50)}
LAST_ENTRY = datetime.time(15, 0)


def params_for(name, overrides=None):
    p = dict(DEFAULTS.get(name, {}))
    p.update({k: v for k, v in (overrides or {}).items() if k in p})
    return p


def agg15(bars5):
    """Group 5 minute bars into 15 minute candles starting at 9:30, 9:45, 10:00 ... Only whole candles are returned."""
    out, cur, key = [], None, None
    for b in bars5:
        t = b["t"]
        mins = (t.hour * 60 + t.minute) - (9 * 60 + 30)
        if mins < 0:
            continue
        k = mins // 15
        if k != key:
            if cur and cur["n"] == 3:
                out.append(cur)
            key = k
            cur = {"t": t, "o": b["o"], "h": b["h"], "l": b["l"], "c": b["c"], "v": b["v"], "n": 1}
        else:
            cur["h"] = max(cur["h"], b["h"]); cur["l"] = min(cur["l"], b["l"]); cur["c"] = b["c"]; cur["v"] += b["v"]; cur["n"] += 1
    if cur and cur["n"] == 3:
        out.append(cur)
    return out


def _plan(entry, stop, p, why):
    risk = entry - stop
    if entry <= 0 or risk <= 0:
        return None
    rp = risk / entry * 100
    if rp < p.get("min_risk", 0.0):
        stop = entry * (1 - p.get("min_risk", 0.3) / 100)
        risk = entry - stop
    elif rp > p.get("max_risk", 100.0):
        return None
    return {"entry": round(entry, 4), "stop": round(stop, 4), "target": round(entry + p["target_r"] * risk, 4), "why": why}


def momentum(bars5, prev, p):
    if not prev or not prev.get("c") or not bars5:
        return None
    last = bars5[-1]
    pct = (last["c"] - prev["c"]) / prev["c"] * 100
    if pct < p["min_move"]:
        return None
    t = last["t"]
    frac = max(0.05, min(1.0, ((t.hour * 60 + t.minute + 5) - (9 * 60 + 30)) / 390.0))
    vol = sum(b["v"] for b in bars5)
    rvol = vol / (prev.get("v", 0) * frac) if prev.get("v") else 0.0
    if rvol < p["min_rvol"]:
        return None
    e = last["c"]
    return _plan(e, e * (1 - p["stop_pct"] / 100), dict(p, min_risk=0, max_risk=100), "up %.1f%% on %.1fx normal volume" % (pct, rvol))


def orb15(bars5, prev, p):
    c15 = agg15(bars5)
    if len(c15) < 2:
        return None
    rng, last = c15[0], c15[-1]
    # only the moment the most recent 15 minute candle has just completed, and only the first close above
    if bars5[-1]["t"] != last["t"] + datetime.timedelta(minutes=10):
        return None
    if any(c["c"] > rng["h"] for c in c15[1:-1]):
        return None
    if last["c"] <= rng["h"] or last["c"] <= last["o"]:
        return None
    avg = sum(c["v"] for c in c15[1:-1]) / max(1, len(c15) - 2) if len(c15) > 2 else rng["v"] / 2
    if avg and last["v"] < p["vol_mult"] * avg:
        return None
    return _plan(last["c"], min(last["l"], rng["h"]) * 0.999, p, "a 15 minute candle closed above the opening range high (%.2f)" % rng["h"])


def engulf(bars5, prev, p):
    if len(bars5) < 4:
        return None
    c15 = agg15(bars5)
    if len(c15) < 2:
        return None
    rng = c15[0]
    levels = [rng["h"]] + ([prev["h"]] if prev and prev.get("h") else [])
    confirmed = [lv for lv in levels if any(c["c"] > lv for c in c15[1:])]
    if not confirmed:
        return None
    level = max(confirmed)
    a, b = bars5[-2], bars5[-1]
    if not (a["c"] < a["o"] and b["c"] > b["o"] and b["c"] >= a["o"] and b["o"] <= a["c"]):
        return None          # not a bullish engulfing candle
    if b["c"] <= level:
        return None          # it has to hold above the level that was confirmed
    look = bars5[-14:-2]
    avg = sum(x["v"] for x in look) / len(look) if look else 0
    if avg and b["v"] < p["vol_mult"] * avg:
        return None
    return _plan(b["c"], min(a["l"], b["l"]) * 0.999, p, "bullish engulfing candle above %.2f after a 15 minute close above it" % level)


RULES = {"momentum": momentum, "orb15": orb15, "engulf": engulf}


def signal(name, bars5, prev, params=None):
    """A plan for the latest completed bar, or None. Respects the entry window."""
    if not bars5:
        return None
    t = bars5[-1]["t"]
    end = (t + datetime.timedelta(minutes=5)).time()
    if end < FIRST_ENTRY.get(name, datetime.time(9, 45)) or end > LAST_ENTRY:
        return None
    return RULES[name](bars5, prev, params_for(name, params))
