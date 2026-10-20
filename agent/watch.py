"""Background watcher: notices trading changes and queues them so JARVIS can tell the person without being asked."""
import datetime
import os
import random
import threading
import time

import autopilot
import broker
import notify
import research

LOCK = threading.Lock()
EVENTS = []          # newest last; each has an increasing id
_NEXT = [1]
POLL = 20            # seconds between broker checks
SIM_EVERY = int(__import__("os").environ.get("JARVIS_SIM_EVERY", "75"))   # 0 turns the demo moves off
SIM_SYMBOLS = ["NVDA", "TSLA", "AAPL", "MSFT", "AMZN", "META", "AMD", "GOOGL"]


def push(kind, say, detail=""):
    with LOCK:
        ev = {"id": _NEXT[0], "kind": kind, "say": say, "detail": detail, "t": time.time()}
        _NEXT[0] += 1
        EVENTS.append(ev)
        del EVENTS[:-50]
    notify.send(kind, say)
    return ev


def since(n):
    with LOCK:
        return [e for e in EVENTS if e["id"] > n], (_NEXT[0] - 1)


def _money(x):
    return "$%s" % format(abs(x), ",.2f")


WATCHLIST = [x.strip().upper() for x in os.environ.get("WATCHLIST", "SPY,QQQ,AAPL,MSFT,NVDA,AMD,TSLA,AMZN,META,GOOGL").split(",") if x.strip()]


def market_open(now=None):
    try:
        from zoneinfo import ZoneInfo
        n = now or datetime.datetime.now(ZoneInfo("America/New_York"))
    except Exception:
        return False
    if n.weekday() >= 5:
        return False
    mins = n.hour * 60 + n.minute
    return 9 * 60 + 30 <= mins < 16 * 60


def session_fraction(now=None):
    from zoneinfo import ZoneInfo
    n = now or datetime.datetime.now(ZoneInfo("America/New_York"))
    return max(0.05, min(1.0, (n.hour * 60 + n.minute - (9 * 60 + 30)) / 390.0))


def start_money():
    try:
        return max(1.0, float(os.environ.get("START_MONEY", "100")))
    except ValueError:
        return 100.0


def signal_text(sym, d, rvol):
    """What worth-a-look means in plain words, sized for a small account. Always labeled as not a prediction."""
    acct = start_money()
    risk = acct * 0.01
    stop_pct = 2.0
    size = risk / (stop_pct / 100.0)
    size = min(size, acct)
    side = "up" if d["pct"] > 0 else "down"
    return ("Worth a look, not a prediction: %s is %s %.1f%% today%s. For a $%.0f account, risking 1%% (about $%.2f) with a stop %.0f%% away means a position of about $%.0f. "
            "A 2 to 1 target would earn about $%.2f. Practice account first." % (sym, side, abs(d["pct"]), (" on %.1fx normal volume" % rvol) if rvol else "", acct, risk, stop_pct, size, risk * 2))


def _fnum(name, default):
    try:
        return float(os.environ.get(name, "") or default)
    except ValueError:
        return default


def guard_enabled():
    """On for the practice account unless turned off. On a live account it only runs if PROFIT_GUARD=on is set on purpose."""
    v = os.environ.get("PROFIT_GUARD", "").strip().lower()
    if broker.mode() == "live":
        return v == "on"
    return v != "off"


def guard_reason(pos, peak):
    """Why this position should be closed, or None. Giveback is the share of the best profit it reached that has been lost."""
    giveback = _fnum("GUARD_GIVEBACK", 40.0) / 100.0
    max_loss = _fnum("GUARD_MAX_LOSS", 3.0) / 100.0
    min_profit = _fnum("GUARD_MIN_PROFIT", 0.25)
    cost = pos.get("cost") or (pos["value"] - pos["pl"])
    if cost > 0 and pos["pl"] <= -cost * max_loss:
        return "loss", "%s is down %.1f%%, past your %.0f%% loss limit" % (pos["symbol"], -pos["pl"] / cost * 100, max_loss * 100)
    if peak >= min_profit and pos["pl"] <= peak * (1 - giveback):
        return "giveback", "%s gave back %.0f%% of its best profit (peak %s, now %s)" % (pos["symbol"], (1 - pos["pl"] / peak) * 100, _money(peak), ("-" if pos["pl"] < 0 else "") + _money(pos["pl"]))
    return None


class Watcher:
    def __init__(self, toolbox):
        self.tb = toolbox
        self.orders = None      # id -> status
        self.syms = None
        self.breaker_on = None
        self.last_pl = None
        self.sim_n = 0
        self.stop = False
        self.flagged = set()
        self.flag_day = None
        self.peaks = {}
        self.closed = set()
        self.t_scan = 0.0

    def start(self):
        threading.Thread(target=self.loop, daemon=True).start()

    def loop(self):
        t_sim = time.time()
        while not self.stop:
            try:
                research.tick(self.tb, push)   # morning research before the open, evening review after the close
            except Exception:  # noqa: BLE001
                pass
            try:
                if broker.configured() and market_open() and time.time() - self.t_scan >= 90:
                    self.t_scan = time.time()
                    self.scan()
                if broker.configured() and autopilot.is_on():
                    from zoneinfo import ZoneInfo
                    held = broker.positions()
                    if market_open():
                        autopilot.sell_leftovers(held, push)   # anything still held from a day the Mac slept through the close
                    autopilot.protect(held, push)   # a stop loss at the broker under each new autopilot buy
                    if autopilot.flatten_due(datetime.datetime.now(ZoneInfo("America/New_York"))):
                        autopilot.flatten(held, push)
                if broker.configured():
                    self.check_broker()
                    self.day_summary()
                elif SIM_EVERY > 0 and time.time() - t_sim >= SIM_EVERY:
                    t_sim = time.time()
                    self.sim_step()
            except Exception:
                pass   # a hiccup in the network must never take JARVIS down
            time.sleep(POLL if broker.configured() else 5)

    def check_broker(self):
        label = "Practice account" if broker.mode() == "paper" else "Live account"
        orders = broker.orders(15)
        cur = {o["id"]: o for o in orders}
        if self.orders is not None:
            for i, o in cur.items():
                old = self.orders.get(i)
                if old is None and o["status"] not in ("FILLED",):
                    push("order", "%s: a %s order for %s was placed. Status: %s." % (label, o["side"].lower(), o["symbol"], o["status"].lower()))
                elif old is not None and old != o["status"]:
                    if o["status"] == "FILLED":
                        push("fill", "%s: your %s order for %s filled, %s." % (label, o["side"].lower(), o["symbol"], _money(o["size"])))
                    else:
                        push("order", "%s: your %s order for %s is now %s." % (label, o["side"].lower(), o["symbol"], o["status"].lower()))
                elif old is None and o["status"] == "FILLED":
                    push("fill", "%s: your %s order for %s filled, %s." % (label, o["side"].lower(), o["symbol"], _money(o["size"])))
        self.orders = {i: o["status"] for i, o in cur.items()}
        acct = broker.account()
        limit = float(self.tb.trading.get("breaker", 50.0))
        tripped = acct["today"] <= -limit
        if self.breaker_on is not None and tripped and not self.breaker_on:
            push("alert", "Circuit breaker tripped. Today is down %s, so I am blocking new orders." % _money(acct["today"]))
        self.breaker_on = tripped
        if acct["blocked"]:
            push("alert", "Your broker says trading is blocked on this account.")
        positions = broker.positions()
        if guard_enabled():
            self.guard(positions, label)
            positions = [p for p in positions if p["symbol"] not in self.closed]
        syms = {p["symbol"] for p in positions}
        if self.syms is not None:
            for s in sorted(syms - self.syms):
                push("position", "%s: you now hold %s." % (label, s))
            for s in sorted(self.syms - syms):
                push("position", "%s: your %s position is closed." % (label, s))
        self.syms = syms
        step = max(100.0, acct["equity"] * 0.01)   # tell her about each 1 percent move
        if self.last_pl is None:
            self.last_pl = acct["today"]
        elif abs(acct["today"] - self.last_pl) >= step:
            push("pl", "%s is %s %s since your last update." % (label, "up" if acct["today"] > self.last_pl else "down", _money(acct["today"] - self.last_pl)))
            self.last_pl = acct["today"]

    def day_summary(self):
        """Once each trading day, a few minutes after the close: today's result from the scorecard, said out loud and sent like other alerts."""
        from pathlib import Path
        from zoneinfo import ZoneInfo
        import scorecard
        now = datetime.datetime.now(ZoneInfo("America/New_York"))
        if now.weekday() >= 5 or now.hour * 60 + now.minute < 16 * 60 + 5:
            return
        day = now.strftime("%Y-%m-%d")
        mark = Path(__file__).resolve().parent.parent / "memory" / "trading" / ".summary_day"
        try:
            if mark.read_text().strip() == day:
                return
        except OSError:
            pass
        mark.parent.mkdir(parents=True, exist_ok=True)
        mark.write_text(day)
        s = scorecard.fetch()
        try:
            autopilot.review(s, push)   # pauses a losing system, unlocks live after a passing practice run
        except Exception:  # noqa: BLE001
            pass
        if not s["today_trades"]:
            return
        label = "Practice account" if broker.mode() == "paper" else "Live account"
        push("summary", "%s, end of day: %s %s over %d finished trade%s. %s" % (
            label, "up" if s["today"] >= 0 else "down", _money(s["today"]), s["today_trades"], "" if s["today_trades"] == 1 else "s", scorecard.spoken(s)))

    def guard(self, positions, label):
        """Profit guard: sells a position when it hands back too much of its best profit, or falls past the loss limit. It never buys."""
        live = {p["symbol"] for p in positions}
        for k in list(self.peaks):
            if k not in live:
                del self.peaks[k]
        self.closed &= live
        for p in positions:
            sym = p["symbol"]
            if sym in self.closed:
                continue
            self.peaks[sym] = max(self.peaks.get(sym, 0.0), p["pl"])
            why = guard_reason(p, self.peaks[sym])
            if not why:
                continue
            try:
                broker.close_position(sym)
                autopilot.record_close(p, why[1])
                self.closed.add(sym)
                push("guard", "%s: profit guard sold %s. %s. Final result about %s%s. Next step: review what happened in your journal before the next trade." % (label, sym, why[1], "-" if p["pl"] < 0 else "+", _money(p["pl"])))
            except broker.BrokerError as e:
                self.closed.add(sym)
                push("alert", "Profit guard wanted to sell %s (%s) but the broker refused: %s. Please check it yourself." % (sym, why[1], e))

    def scan(self):
        today = datetime.date.today()
        if self.flag_day != today:
            self.flag_day, self.flagged = today, set()
        snaps = broker.snapshots(WATCHLIST)
        frac = session_fraction()
        for sym, d in snaps.items():
            rvol = (d["vol"] / (d["prev_vol"] * frac)) if d["prev_vol"] else 0.0
            key = (sym, d["pct"] > 0)
            if abs(d["pct"]) >= 2.0 and (rvol >= 1.5 or rvol == 0.0) and key not in self.flagged:
                self.flagged.add(key)
                push("signal", signal_text(sym, d, rvol))
                if d["pct"] > 0:
                    autopilot.consider(sym, d, rvol, push)   # only if she switched it on, and live only after the practice run passed

    def sim_step(self):
        """Demo only: makes up a pipeline move so the feed can be seen working. Never touches any account."""
        sym = random.choice(SIM_SYMBOLS)
        rank = random.randint(1, 10)
        size = float(random.choice([10, 15, 20, 25]))
        act = random.choice(["BUY", "BUY", "SELL"])
        now = time.strftime("%H:%M:%S")
        with LOCK:
            pass
        tr = self.tb.trading["trades"]
        tr.insert(0, {"time": now, "symbol": sym, "rank": "Rank #%d" % rank, "action": act, "size": size, "status": "SIMULATED FILL"})
        del tr[12:]
        push("sim", "Simulation only, no real money: Rank %d trader moved. %s %s for %s." % (rank, act.lower(), sym, _money(size)))
