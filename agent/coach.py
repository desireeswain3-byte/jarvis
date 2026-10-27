"""The learning loop: which stocks he watches, which rule he trades, and how that rule gets better.

  * universe(): the 50 most active stocks of the day from Alpaca (falls back to a built-in list), plus her WATCHLIST.
  * Every week (Friday evening or the weekend, and whenever she asks), he backtests every rule and a few settings on
    the last 40 trading days. A rule is only proposed if it made money on the days it was chosen on AND on the most
    recent days it was not chosen on (so it is not just luck fitted to the past), with enough trades to mean something.
  * A better rule is never switched on by itself. He sends one phone notification and waits for her to approve
    (the Approve button on the Trading screen, or saying "approve the new rule").
Everything is kept in memory/strategy.json on her Mac.
"""
import datetime
import json
import os
import threading
import time

import memory
import strategies

PATH = memory.MEM / "strategy.json"
BUSY = threading.Lock()
FALLBACK = ["AAPL", "MSFT", "NVDA", "AMD", "TSLA", "AMZN", "META", "GOOGL", "NFLX", "AVGO", "PLTR", "SOFI", "INTC", "MU", "SMCI", "COIN",
            "MARA", "RIOT", "HOOD", "UBER", "SHOP", "BABA", "NIO", "F", "BAC", "JPM", "XOM", "PFE", "T", "DIS", "NKE", "WMT", "COST", "ORCL",
            "CRM", "PYPL", "SNAP", "RIVN", "LCID", "ARM", "MSTR", "CVNA", "DKNG", "RBLX", "AFRM", "UPST", "ROKU", "SQ", "CCL", "AAL"]
GRID = {"momentum": [{}, {"min_move": 3.0}, {"target_r": 1.5}],
        "orb15": [{}, {"target_r": 1.5}, {"target_r": 3.0}, {"vol_mult": 1.5}],
        "engulf": [{}, {"target_r": 1.5}, {"target_r": 3.0}, {"vol_mult": 1.5}]}
MIN_TRADES = 20


def load():
    try:
        return json.loads(PATH.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {"name": "momentum", "params": {}}


def save(cfg):
    try:
        PATH.parent.mkdir(parents=True, exist_ok=True)
        PATH.write_text(json.dumps(cfg, indent=1, default=str), encoding="utf-8")
    except OSError:
        pass


def current():
    cfg = load()
    name = cfg.get("name") if cfg.get("name") in strategies.NAMES else "momentum"
    return name, cfg.get("params") or {}


def describe(name, params):
    p = strategies.params_for(name, params)
    extra = []
    d = strategies.DEFAULTS.get(name, {})
    if p.get("min_move") != d.get("min_move") and "min_move" in p:
        extra.append("up %g%%" % p["min_move"])
    if p.get("vol_mult") != d.get("vol_mult") and "vol_mult" in p:
        extra.append("volume %gx" % p["vol_mult"])
    return "%s, target %gR%s" % (strategies.LABELS[name], p.get("target_r", 2), (", " + ", ".join(extra)) if extra else "")


# ---------------- which stocks ----------------

_uni = {"day": None, "list": []}


def universe(size=50):
    import broker
    import watch
    today = datetime.date.today().isoformat()
    if _uni["day"] == today and _uni["list"]:
        return _uni["list"]
    picks = []
    try:
        raw = broker._req("GET", "/v1beta1/screener/stocks/most-actives?by=volume&top=%d" % size, host="https://data.alpaca.markets") or {}
        picks = [str(x.get("symbol", "")).upper() for x in raw.get("most_actives", []) if x.get("symbol")]
    except Exception:  # noqa: BLE001
        picks = []
    if len(picks) < 20:
        picks = FALLBACK[:size]
    base = [s for s in watch.WATCHLIST if s not in ("SPY", "QQQ", "DIA", "IWM")]
    out = []
    for s in base + picks:
        if s not in out and broker.SYMBOL.match(s):
            out.append(s)
    _uni.update(day=today, list=out[:max(size, len(base))])
    return _uni["list"]


# ---------------- the weekly test ----------------

def evaluate(data, push=None):
    """Backtest every rule and setting. Returns the table and the best candidate that passed both halves."""
    import backtest
    first, last = backtest.split(data, 0.7)
    rows = []
    for name, variants in GRID.items():
        for v in variants:
            a = backtest.run(first, name, v)
            b = backtest.run(last, name, v)
            whole = backtest.run(data, name, v)
            rows.append({"name": name, "params": v, "first": a, "last": b, "whole": whole})
    ok = [r for r in rows if r["whole"]["trades"] >= MIN_TRADES and r["first"]["expectancy"] > 0 and r["last"]["expectancy"] > 0 and r["whole"]["total"] > 0]
    best = max(ok, key=lambda r: (r["first"]["expectancy"], r["whole"]["total"])) if ok else None
    return rows, best


def _short(st):
    return "%d trades, %.0f%% won, %s$%.2f total, about %s%.1f cents a trade" % (
        st["trades"], st["win_rate"], "+" if st["total"] >= 0 else "-", abs(st["total"]), "+" if st["expectancy"] >= 0 else "-", abs(st["expectancy"]) * 100)


def weekly(push, days=40):
    """Run the test and, if a better rule held up, ask her to approve it. Returns what he says."""
    import backtest
    if not BUSY.acquire(blocking=False):
        return "I am already testing. Give me a few minutes."
    try:
        data = backtest.fetch(universe(), days)
        if len(data.get("days", [])) < 15:
            return "I could not get enough past prices to test properly. I will try again later."
        rows, best = evaluate(data)
        name, params = current()
        cur = next((r for r in rows if r["name"] == name and strategies.params_for(name, r["params"]) == strategies.params_for(name, params)), None)
        if cur is None:
            cur = {"whole": backtest.run(data, name, params)}
        cfg = load()
        cfg["last_test"] = {"date": time.strftime("%Y-%m-%d"), "days": len(data["days"]), "symbols": len(universe()),
                            "table": [{"rule": describe(r["name"], r["params"]), "name": r["name"], "params": r["params"], "whole": {k: r["whole"][k] for k in ("trades", "win_rate", "total", "expectancy", "max_drawdown", "trades_per_day")},
                                       "held_up": r["first"]["expectancy"] > 0 and r["last"]["expectancy"] > 0} for r in rows],
                            "current": {"rule": describe(name, params), **{k: cur["whole"][k] for k in ("trades", "win_rate", "total", "expectancy", "max_drawdown", "trades_per_day")}}}
        better = best and (best["name"] != name or strategies.params_for(best["name"], best["params"]) != strategies.params_for(name, params)) and \
            best["whole"]["expectancy"] > cur["whole"]["expectancy"] + 0.02
        if better:
            cfg["proposal"] = {"name": best["name"], "params": best["params"], "made": time.strftime("%Y-%m-%d"),
                               "why": "Over the last %d trading days on %d active stocks, %s would have made %s. Your current rule, %s, would have made %s. "
                                      "It also held up on the most recent days it was not chosen on." % (
                                          len(data["days"]), len(universe()), describe(best["name"], best["params"]), _short(best["whole"]), describe(name, params), _short(cur["whole"]))}
            save(cfg)
            say = "I found a better rule. " + cfg["proposal"]["why"] + " Want me to switch? Tap Approve on the Trading screen or tell me to approve it. Past results do not promise future ones, and it stays on the practice account."
            if push:
                push("autopilot", say)
            return say
        cfg.pop("proposal", None)
        save(cfg)
        if best is None:
            say = ("I tested every rule on the last %d trading days. None made money reliably on both the older and the newer days, so I am not changing anything. "
                   "Your current rule: %s. Keeping trades small while we keep learning." % (len(data["days"]), _short(cur["whole"])))
        else:
            say = "I tested every rule on the last %d trading days. Your current rule is still the best one that held up: %s." % (len(data["days"]), _short(cur["whole"]))
        if push:
            push("research", say)
        return say
    finally:
        BUSY.release()


def approve():
    cfg = load()
    p = cfg.pop("proposal", None)
    if not p:
        return False, "There is no new rule waiting for approval."
    cfg.setdefault("history", []).append({"date": time.strftime("%Y-%m-%d"), "from": {"name": cfg.get("name", "momentum"), "params": cfg.get("params", {})},
                                          "to": {"name": p["name"], "params": p["params"]}, "why": p["why"]})
    cfg["name"], cfg["params"] = p["name"], p["params"]
    save(cfg)
    return True, "Done. From the next signal on, I trade with %s. I will keep score and tell you how it does." % describe(p["name"], p["params"])


def reject():
    cfg = load()
    if not cfg.pop("proposal", None):
        return False, "There is no new rule waiting."
    save(cfg)
    return True, "Okay, I kept your current rule."


def use(name, params=None):
    if name not in strategies.NAMES:
        return False, "I know these rules: %s." % ", ".join(strategies.NAMES)
    cfg = load()
    cfg.setdefault("history", []).append({"date": time.strftime("%Y-%m-%d"), "from": {"name": cfg.get("name", "momentum"), "params": cfg.get("params", {})},
                                          "to": {"name": name, "params": params or {}}, "why": "she chose it"})
    cfg["name"], cfg["params"] = name, params or {}
    cfg.pop("proposal", None)
    save(cfg)
    return True, "Switched to %s." % describe(name, params or {})


def due(now, cfg=None):
    """Friday from 4:30 PM New York time, or any weekend day, once a week."""
    cfg = cfg if cfg is not None else load()
    last = (cfg.get("last_test") or {}).get("date")
    if last:
        try:
            if (now.date() - datetime.date.fromisoformat(last)).days < 6:
                return False
        except ValueError:
            pass
    return (now.weekday() == 4 and now.hour * 60 + now.minute >= 16 * 60 + 30) or now.weekday() >= 5


def tick(push):
    """Called by the watcher. Starts the weekly test in the background when it is due."""
    import broker
    if not broker.configured() or os.environ.get("LEARNING_LOOP", "on").lower() in ("off", "no", "0"):
        return
    from zoneinfo import ZoneInfo
    now = datetime.datetime.now(ZoneInfo("America/New_York"))
    if not due(now) or BUSY.locked():
        return
    cfg = load()
    cfg["last_test"] = dict(cfg.get("last_test") or {}, date=now.date().isoformat())   # mark first, so a failure does not retry every few seconds
    save(cfg)

    def job():
        try:
            weekly(push)
        except Exception as e:  # noqa: BLE001
            push("alert", "My weekly rule test did not finish: %s" % str(e)[:140])
    threading.Thread(target=job, daemon=True).start()
