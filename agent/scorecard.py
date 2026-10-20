"""Practice scorecard: rebuilds finished trades from the broker's fills and keeps score, so the practice weeks tell her
whether the system makes money. Arithmetic on what already happened, never a prediction."""
import datetime
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")


def _day(iso):
    try:
        return datetime.datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(ET).strftime("%Y-%m-%d")
    except (ValueError, AttributeError):
        return (iso or "")[:10]


def trades_from_fills(fills):
    """Match fills first in, first out per symbol. A trade starts when a symbol goes from no position to a position and ends
    when it is back to zero. Returns finished trades (oldest first) and the open ones."""
    book = {}      # symbol -> {"lots": [[qty signed, price]], "pl": realized so far, "open": iso, "side": long/short, "cost": $ in}
    done = []
    for f in sorted(fills, key=lambda x: x["time"]):
        sym, q, px = f["symbol"], f["qty"], f["price"]
        if not sym or q <= 0 or px <= 0:
            continue
        sq = q if f["side"] == "buy" else -q
        b = book.get(sym)
        if b is None:
            b = book[sym] = {"lots": [], "pl": 0.0, "open": f["time"], "side": "long" if sq > 0 else "short", "cost": 0.0}
        left = sq
        while left and b["lots"] and (b["lots"][0][0] > 0) != (left > 0):
            lot = b["lots"][0]
            m = min(abs(lot[0]), abs(left))
            b["pl"] += m * (px - lot[1]) * (1 if lot[0] > 0 else -1)
            lot[0] += m if lot[0] < 0 else -m
            left += m if left < 0 else -m
            if abs(lot[0]) < 1e-9:
                b["lots"].pop(0)
            if abs(left) < 1e-9:
                left = 0
        if left:
            b["lots"].append([left, px])
            b["cost"] += abs(left) * px
        if not b["lots"]:
            done.append({"symbol": sym, "side": b["side"], "opened": b["open"], "closed": f["time"], "day": _day(f["time"]),
                         "pl": round(b["pl"], 2), "cost": round(b["cost"], 2), "pct": round(b["pl"] / b["cost"] * 100, 2) if b["cost"] else 0.0})
            del book[sym]
    return done, sorted(book)


def score(fills, positions=None, history=None):
    done, still_open = trades_from_fills(fills)
    wins = [t["pl"] for t in done if t["pl"] > 0]
    losses = [t["pl"] for t in done if t["pl"] <= 0]
    n = len(done)
    wr = len(wins) / n if n else 0.0
    aw = sum(wins) / len(wins) if wins else 0.0
    al = sum(losses) / len(losses) if losses else 0.0
    payoff = (aw / abs(al)) if al else None
    need = (1 / (1 + payoff)) if payoff else None
    days = {}
    for t in done:
        days[t["day"]] = days.get(t["day"], 0.0) + t["pl"]
    day_rows = [{"day": d, "pl": round(v, 2)} for d, v in sorted(days.items())]
    streak, kind = 0, None
    for t in reversed(done):
        k = "win" if t["pl"] > 0 else "loss"
        if kind is None:
            kind = k
        if k != kind:
            break
        streak += 1
    open_pl = round(sum(p.get("pl", 0.0) for p in (positions or [])), 2)
    eq_days = []
    if history:
        for h in history[-21:]:
            eq_days.append({"day": datetime.datetime.fromtimestamp(h["t"], ET).strftime("%Y-%m-%d"), "equity": round(h["equity"], 2), "pl": round(h["pl"], 2)})
    if n == 0:
        verdict = "No finished trades yet. A trade counts once you have bought and then sold all of it (or the other way round)."
    elif n < 20:
        verdict = "%d finished trade%s so far. Under 20 is too few to judge the system, so keep practicing at your real size." % (n, "" if n == 1 else "s")
    elif need is None:
        verdict = "No losing trades yet in %d trades, which will not last. Keep the stop loss on every trade." % n
    elif wr >= need:
        verdict = "Winning %.0f%% of trades, and at your average win and loss you need %.0f%% to break even. On these numbers the system makes money. Keep going before using real money." % (wr * 100, need * 100)
    else:
        verdict = "Winning %.0f%% of trades, but at your average win and loss you need %.0f%% to break even, so the system is losing money. Make wins bigger, losses smaller, or trades pickier before real money." % (wr * 100, need * 100)
    return {
        "trades": n, "wins": len(wins), "losses": len(losses), "win_rate": round(wr * 100, 1),
        "avg_win": round(aw, 2), "avg_loss": round(al, 2), "payoff": round(payoff, 2) if payoff else None,
        "breakeven_win_rate": round(need * 100, 1) if need else None,
        "expectancy": round(wr * aw + (1 - wr) * al, 2) if n else 0.0,
        "total": round(sum(t["pl"] for t in done), 2), "best": max((t["pl"] for t in done), default=0.0), "worst": min((t["pl"] for t in done), default=0.0),
        "green_days": sum(1 for d in day_rows if d["pl"] > 0), "red_days": sum(1 for d in day_rows if d["pl"] < 0),
        "streak": {"n": streak, "kind": kind}, "open_pl": open_pl, "open_symbols": still_open,
        "days": day_rows[-21:], "equity_days": eq_days, "recent": list(reversed(done[-12:])), "verdict": verdict,
        "today": next((d["pl"] for d in day_rows if d["day"] == datetime.datetime.now(ET).strftime("%Y-%m-%d")), 0.0),
        "today_trades": sum(1 for t in done if t["day"] == datetime.datetime.now(ET).strftime("%Y-%m-%d")),
    }


def fetch():
    import broker
    fl = broker.fills(90)
    try:
        pos = broker.positions()
    except broker.BrokerError:
        pos = []
    try:
        hist = broker.history("1M")
    except broker.BrokerError:
        hist = []
    out = score(fl, pos, hist)
    out["mode"] = broker.mode()
    return out


def spoken(s):
    """A short line JARVIS can say out loud."""
    if not s["trades"]:
        return s["verdict"]
    sign = lambda x: ("up " if x >= 0 else "down ") + "$%s" % format(abs(x), ",.2f")
    head = "%d finished trade%s, %d won, %.0f percent. Overall %s." % (s["trades"], "" if s["trades"] == 1 else "s", s["wins"], s["win_rate"], sign(s["total"]))
    if s["trades"] < 20:
        return head + " That is too few to judge the system yet, so keep practicing at your real size."
    return head + " " + s["verdict"]
