"""Broker connection (Alpaca). Standard library only.

Safety design:
  * Paper (practice, fake money) is the default. Live needs BOTH ALPACA_MODE=live and ALPACA_ALLOW_LIVE=yes in .env.
  * Nothing here places an order by itself. The model can only PROPOSE one. The order is sent only when the
    person presses Confirm on screen, which calls place() through /api/broker/confirm.
  * Hard limits: a maximum dollar size per order, a maximum number of orders per day, and no new orders once the
    day's loss reaches the circuit breaker.
"""
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

PAPER_URL = "https://paper-api.alpaca.markets"
LIVE_URL = "https://api.alpaca.markets"
SYMBOL = re.compile(r"^[A-Z]{1,5}(\.[A-Z])?$")


class BrokerError(Exception):
    pass


def _key():
    if mode() == "live" and os.environ.get("ALPACA_LIVE_KEY_ID", "").strip():
        return os.environ["ALPACA_LIVE_KEY_ID"].strip()
    return os.environ.get("ALPACA_KEY_ID", "").strip()


def _secret():
    if mode() == "live" and os.environ.get("ALPACA_LIVE_SECRET_KEY", "").strip():
        return os.environ["ALPACA_LIVE_SECRET_KEY"].strip()
    return os.environ.get("ALPACA_SECRET_KEY", "").strip()


def live_keys_saved():
    return bool(os.environ.get("ALPACA_LIVE_KEY_ID", "").strip() and os.environ.get("ALPACA_LIVE_SECRET_KEY", "").strip())


def configured():
    return bool(_key() and _secret())


def mode():
    live = os.environ.get("ALPACA_MODE", "paper").strip().lower() == "live" and os.environ.get("ALPACA_ALLOW_LIVE", "").strip().lower() == "yes"
    return "live" if live else "paper"


def base():
    return (os.environ.get("ALPACA_BASE_URL") or (LIVE_URL if mode() == "live" else PAPER_URL)).rstrip("/")


def _num(name, default):
    try:
        v = float(os.environ.get(name, "") or default)
        return v if v > 0 else default
    except ValueError:
        return default


def max_order():
    return _num("ALPACA_MAX_ORDER", 25.0)


def max_orders_per_day():
    return int(_num("ALPACA_MAX_ORDERS_PER_DAY", 5))


def _req(method, path, body=None, host=None):
    if not configured():
        raise BrokerError("No broker keys. Add ALPACA_KEY_ID and ALPACA_SECRET_KEY to .env")
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request((host or base()) + path, data=data, method=method, headers={
        "APCA-API-KEY-ID": _key(), "APCA-API-SECRET-KEY": _secret(),
        "Content-Type": "application/json", "Accept": "application/json", "User-Agent": "jarvis-local"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            raw = r.read()
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read().decode("utf-8", "replace")).get("message", "")
        except Exception:  # noqa: BLE001
            msg = ""
        if e.code in (401, 403):
            raise BrokerError("The broker refused the keys (%d). Check ALPACA_KEY_ID and ALPACA_SECRET_KEY, and that they match %s mode." % (e.code, mode()))
        raise BrokerError("The broker said %d. %s" % (e.code, msg[:200]))
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise BrokerError("Could not reach the broker: %s" % getattr(e, "reason", e))
    try:
        return json.loads(raw.decode("utf-8")) if raw else {}
    except ValueError:
        raise BrokerError("The broker sent something I could not read.")


def _f(x, default=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def account():
    a = _req("GET", "/v2/account")
    eq, last = _f(a.get("equity")), _f(a.get("last_equity"), _f(a.get("equity")))
    return {"equity": eq, "today": eq - last, "cash": _f(a.get("cash")), "buying_power": _f(a.get("buying_power")),
            "status": str(a.get("status", "")), "blocked": bool(a.get("trading_blocked") or a.get("account_blocked"))}


def positions():
    out = []
    for p in _req("GET", "/v2/positions") or []:
        out.append({"symbol": str(p.get("symbol", "")), "qty": _f(p.get("qty")), "value": _f(p.get("market_value")), "pl": _f(p.get("unrealized_pl")),
                    "entry": _f(p.get("avg_entry_price")), "cost": _f(p.get("cost_basis")) or (_f(p.get("market_value")) - _f(p.get("unrealized_pl")))})
    return out


def orders(limit=8):
    out = []
    for o in _req("GET", "/v2/orders?status=all&direction=desc&limit=%d" % int(limit)) or []:
        when = str(o.get("submitted_at") or o.get("created_at") or "")
        out.append({"id": str(o.get("id", "")), "time": when[11:19] if len(when) >= 19 else when, "symbol": str(o.get("symbol", "")),
                    "side": str(o.get("side", "")).upper(), "size": _f(o.get("notional")) or _f(o.get("filled_avg_price")) * _f(o.get("filled_qty")),
                    "status": str(o.get("status", "")).upper().replace("_", " ")})
    return out


def orders_today():
    n = 0
    today = None
    for o in _req("GET", "/v2/orders?status=all&direction=desc&limit=100") or []:
        t = str(o.get("submitted_at") or o.get("created_at") or "")[:10]
        today = today or t
        if t and t == today:
            n += 1
    return n


def place(symbol, side, notional):
    """Send ONE market order sized in dollars. Only call this after the person confirmed on screen."""
    symbol = (symbol or "").upper().strip()
    side = (side or "").lower().strip()
    if not SYMBOL.match(symbol):
        raise BrokerError("That is not a valid ticker symbol.")
    if side not in ("buy", "sell"):
        raise BrokerError("Buy or sell?")
    n = round(float(notional), 2)
    if n < 1:
        raise BrokerError("The smallest order is $1.")
    if n > max_order():
        raise BrokerError("That is over your per-order limit of $%.2f." % max_order())
    return _req("POST", "/v2/orders", {"symbol": symbol, "side": side, "type": "market", "time_in_force": "day", "notional": "%.2f" % n})


def snapshots(symbols):
    """Price, change and volume for a few symbols. Free IEX data from the same keys. Not a prediction, just where things are."""
    syms = ",".join(sorted({str(x).upper() for x in symbols if str(x).strip()}))
    raw = _req("GET", "/v2/stocks/snapshots?symbols=%s&feed=iex" % syms, host="https://data.alpaca.markets") or {}
    raw = raw.get("snapshots", raw)
    out = {}
    for sym, v in raw.items():
        if not isinstance(v, dict):
            continue
        last = _f((v.get("latestTrade") or {}).get("p")) or _f((v.get("dailyBar") or {}).get("c"))
        prev = _f((v.get("prevDailyBar") or {}).get("c"))
        d = v.get("dailyBar") or {}
        if last and prev:
            out[sym] = {"price": last, "prev": prev, "pct": (last - prev) / prev * 100.0, "open": _f(d.get("o")), "high": _f(d.get("h")), "low": _f(d.get("l")),
                        "vol": _f(d.get("v")), "prev_vol": _f((v.get("prevDailyBar") or {}).get("v"))}
    return out


def open_orders(symbol=None):
    """Orders still waiting at the broker, optionally for one symbol."""
    q = "/v2/orders?status=open&limit=100" + (("&symbols=" + urllib.parse.quote(str(symbol).upper(), safe="")) if symbol else "")
    return [{"id": str(o.get("id", "")), "symbol": str(o.get("symbol", "")), "side": str(o.get("side", "")).lower(), "type": str(o.get("type", "")).lower(),
             "stop": _f(o.get("stop_price")), "qty": _f(o.get("qty"))} for o in (_req("GET", q) or [])]


def cancel_order(order_id):
    return _req("DELETE", "/v2/orders/" + urllib.parse.quote(str(order_id), safe=""))


def place_stop(symbol, qty, stop_price):
    """A safety-net stop loss that sits AT THE BROKER, so it still sells if JARVIS or the Mac is asleep.
    Fractional orders only allow time_in_force=day, so it lasts until today's close. It only ever sells shares already held."""
    symbol = (symbol or "").upper().strip()
    if not SYMBOL.match(symbol):
        raise BrokerError("That is not a valid ticker symbol.")
    q = float(qty)
    if q <= 0:
        raise BrokerError("Nothing to protect.")
    px = float(stop_price)
    price = ("%.2f" % px) if px >= 1 else ("%.4f" % px)
    return _req("POST", "/v2/orders", {"symbol": symbol, "side": "sell", "type": "stop", "time_in_force": "day",
                                       "qty": ("%.9f" % q).rstrip("0").rstrip("."), "stop_price": price})


def close_position(symbol):
    """Sell the whole position. Only ever reduces risk, so the profit guard may do it without asking.
    Waiting orders for the symbol (like a safety-net stop) are cancelled first, because they hold the shares."""
    for o in open_orders(symbol):
        if o["symbol"] == str(symbol).upper():
            try:
                cancel_order(o["id"])
            except BrokerError:
                pass
    sym = urllib.parse.quote(str(symbol).upper(), safe="")
    return _req("DELETE", "/v2/positions/" + sym)


def fills(days=90):
    """Every fill on the account in the last few days, oldest first. Used by the scorecard to rebuild finished trades."""
    import datetime as _dt
    after = (_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=int(days))).strftime("%Y-%m-%dT%H:%M:%SZ")
    out, token = [], None
    for _ in range(20):   # at most 2,000 fills
        q = "/v2/account/activities/FILL?direction=asc&page_size=100&after=" + after + (("&page_token=" + urllib.parse.quote(token, safe="")) if token else "")
        page = _req("GET", q) or []
        for a in page:
            out.append({"id": str(a.get("id", "")), "time": str(a.get("transaction_time", "")), "symbol": str(a.get("symbol", "")),
                        "side": str(a.get("side", "")).lower(), "qty": _f(a.get("qty")), "price": _f(a.get("price"))})
        if len(page) < 100:
            break
        token = str(page[-1].get("id", ""))
    return out


def history(period="1M"):
    """Account value and profit or loss at each day's close, from the broker."""
    h = _req("GET", "/v2/account/portfolio/history?period=%s&timeframe=1D" % urllib.parse.quote(period, safe="")) or {}
    out = []
    for t, eq, pl in zip(h.get("timestamp") or [], h.get("equity") or [], h.get("profit_loss") or []):
        if eq is None:
            continue
        out.append({"t": int(t), "equity": _f(eq), "pl": _f(pl)})
    return out
