"""Model client and offline router. Standard library only.

With ANTHROPIC_API_KEY set, the model decides between conversation and tools.
Without it, routing falls back to scoring the question against the files, and
the UI shows a MODEL MISSING badge. That is not the model talking.
"""
import datetime
import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path

import data
import memory
import tools

ROOT = Path(__file__).resolve().parent.parent
API_DEFAULT = "https://api.anthropic.com"


def api_url():
    # ANTHROPIC_BASE_URL lets tests point at a local stand-in. Unset means the real API.
    return os.environ.get("ANTHROPIC_BASE_URL", API_DEFAULT).rstrip("/") + "/v1/messages"
MAX_ROUNDS = 5


class ModelUnavailable(Exception):
    pass


def key():
    return os.environ.get("ANTHROPIC_API_KEY", "").strip()


def model_name():
    return os.environ.get("JARVIS_MODEL", "claude-sonnet-5-5").strip()


def available():
    return bool(key())


def part_of_day(now=None):
    """(name, greeting) for the local time on this Mac. From 10pm to 5am it is Good night."""
    h = (now or datetime.datetime.now()).hour
    if 5 <= h < 12:
        return "morning", "Good morning"
    if 12 <= h < 17:
        return "afternoon", "Good afternoon"
    if 17 <= h < 22:
        return "evening", "Good evening"
    return "night", "Good night"


def build_system(wiring=None):
    parts = [(Path(__file__).parent / "prompt.md").read_text(encoding="utf-8")]
    claude_md = ROOT / "CLAUDE.md"
    if claude_md.exists():
        parts.append("## Who you are working for (CLAUDE.md)\n" + claude_md.read_text(encoding="utf-8"))
    me_md = ROOT / "ME.md"  # her private details; ignored by git, never uploaded
    if me_md.exists():
        parts.append("## About her (ME.md, private)\n" + me_md.read_text(encoding="utf-8"))
    mem = memory.listing()[:30]
    if mem:
        parts.append("## Remembered facts (memory/)\n" + "\n".join("- %s: %s" % (m["file"], m["text"]) for m in mem))
    if wiring:
        parts.append("## Your live setup right now\n" + "\n".join("- %s: %s" % (k, v) for k, v in wiring.items()))
    now = datetime.datetime.now()
    name, greet = part_of_day(now)
    parts.append("## Context\nToday is %s. The local time is %s, which is %s. Mode: %s.\nGreeting for now: \"%s, Madam Swain\". If she is going to bed or signing off, say \"Good night, Madam Swain\"." % (
        now.strftime("%A %d %B %Y"), now.strftime("%I:%M %p").lstrip("0"), name, "demo data, invented" if data.is_demo() else "real data", greet))
    return "\n\n".join(parts)


def _post(body):
    req = urllib.request.Request(
        api_url(), data=json.dumps(body).encode(), method="POST",
        headers={"x-api-key": key(), "anthropic-version": "2023-06-01", "content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read()[:200].decode("utf-8", "replace")
        raise ModelUnavailable("Model API returned %d. %s" % (e.code, detail))
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
        raise ModelUnavailable("Could not reach the model: %s" % e)


def _screen_block(screen):
    """What the page is showing, as data. Text on screen can come from files or mail, so it is untrusted."""
    try:
        body = json.dumps(screen, ensure_ascii=False, indent=1)[:7000]
    except (TypeError, ValueError):
        return ""
    return tools.wrap_data("screen", body) + "\n"


def converse(text, history, toolbox, screen=None, image=None, wiring=None):
    system = build_system(wiring)
    user = [{"type": "text", "text": (_screen_block(screen) if screen else "") + text}]
    if image:
        user.insert(0, {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": image.split(",", 1)[1]}})
        user[-1]["text"] = "(A screenshot of the person's screen is attached, taken just now.)\n" + user[-1]["text"]
    msgs = list(history) + [{"role": "user", "content": user}]
    cards, used, says, refresh, actions = [], [], {}, False, []
    reply = ""
    for _ in range(MAX_ROUNDS):
        r = _post({"model": model_name(), "max_tokens": 700, "system": system,
                   "tools": tools.TOOL_SCHEMAS, "messages": msgs})
        content = r.get("content", [])
        msgs.append({"role": "assistant", "content": content})
        if r.get("stop_reason") != "tool_use":
            reply = "".join(b.get("text", "") for b in content if b.get("type") == "text").strip()
            break
        results = []
        for b in content:
            if b.get("type") != "tool_use":
                continue
            out = toolbox.run(b["name"], b.get("input", {}))
            if out.get("card"):
                cards.append(out["card"])
            actions.extend(out.get("actions", []))
            used.append(b["name"])
            says[b["name"]] = out["say"]
            refresh = refresh or bool(out.get("refresh"))
            payload = out["facts"][:13000] + ("\nDraft spoken line (reuse or tighten): " + out["say"] if out["say"] else "\nNothing to say aloud. The screen already shows the result.")
            results.append({"type": "tool_result", "tool_use_id": b["id"], "content": payload})
        msgs.append({"role": "user", "content": results})
    if not reply:
        reply = says.get(used[-1], "") if used else "I have nothing to add."
    # Guardrail in code: a memory write is always said out loud.
    if "remember" in says and "memory" not in reply.lower():
        reply = says["remember"] + " " + reply
    return {"reply": reply, "cards": cards, "tools": used, "refresh": refresh, "actions": actions}


# ---------- offline routing: score the question against the files ----------
GREET = re.compile(r"^\s*(hi|hello|hey|yo|good (morning|afternoon|evening|night))\b", re.I)
HEAR = re.compile(r"(can|could) you hear me|are you (there|listening)|^\s*(test|testing)\b|check(ing)? (one|1)", re.I)
ADDRESS = re.compile(r"^\s*(?:(?:hi|hello|hey|yo|ok|okay|jarvis|good (?:morning|afternoon|evening))\b[,!.]*\s*)+", re.I)
THANKS = re.compile(r"^\s*(thanks|thank you|cheers|ta)\b", re.I)
ORDER = re.compile(r"^\s*(?:please\s+)?(buy|sell)\s+\$?(\d+(?:\.\d+)?)(?:\s+dollars?)?(?:\s+(?:worth\s+)?of)?\s+(?:shares\s+of\s+)?([A-Za-z]{1,5})\b", re.I)
BROKER = re.compile(r"\b(broker (?:status|account|balance)|my (?:positions|portfolio)|account (?:balance|status)|how(?:'s| is) my (?:account|portfolio))\b", re.I)
TRADING = re.compile(r"\b(circuit breaker|cash sweep|sweep|trading|trade pipeline|trading vault)\b", re.I)
WELL = re.compile(r"\b(quote of the day|focus (?:stream|music|audio|sounds?)|spa (?:relaxation|stream|music|audio)|relaxation (?:stream|music)|stop (?:the )?(?:audio|music|stream)|(?:tea|hydration) reminder|wellness|ambience)\b", re.I)
BRIEF = re.compile(r"\b(brief me|briefing|what'?s on today|my calendar|what slipped)\b", re.I)
PLAN = re.compile(r"\b(plan (my |the )?day|plan today|what should i do today)\b", re.I)
INBOX = re.compile(r"\b(inbox|my email|my mail|unread)\b", re.I)
REMEMBER = re.compile(r"^\s*remember( that)?[:,]?\s+(.+)", re.I | re.S)
WEB = re.compile(r"^\s*(look up|research|search the web for|google)\s+(.+)", re.I | re.S)
SHOW = re.compile(r"^\s*(?:please\s+|can you\s+|could you\s+)?(?:show|open|pull up|bring up|display|put up|find|load|let me see|i want to see|can i see)\b(?:\s+me)?\s+(.+?)[.!?]*\s*$", re.I | re.S)
CLOSE = re.compile(r"^\s*(?:please\s+)?(close|dismiss|hide|clear|put away|get rid of|shut)\b(?:\s+(?:that|this|it|the (?:note|card|cards|window|panel|file|doc|document|screen)|everything|all|the screen))?\s*(?:please)?[.!]?\s*$", re.I)
BACK = re.compile(r"^\s*(?:please\s+)?(?:go\s+)?(back|forward)(?:\s+one)?\s*[.!]?\s*$|^\s*(previous|next)\s+(?:note|one|page)\s*[.!]?\s*$", re.I)
SCROLLY = re.compile(r"\bscroll\b|^\s*(?:page\s+)?(?:up|down)\s*[.!]?\s*$|\bpage (?:up|down)\b|\bto the (?:top|bottom)\b|\bback to the top\b|\ball the way (?:up|down)\b|\b(?:go|move|keep going|head) (?:up|down)\b", re.I)
LAYERY = re.compile(r"\b(?:(?:to|in|at|on) the (?:front|back)\b|in front\b|foreground|background|behind|middle layer|(?:bring|come|step|stay|move|go|get|send|put)\b.*\b(?:forward|front|back layer)\b|send (?:yourself|him|jarvis)\b.*\bback)", re.I)
ORBY = re.compile(r"^\s*(?:please\s+)?(?:(?:can|could) you\s+)?(?:move|go|slide|come|get|swing|float|drift|head|step)\b.*\b(left|right|top|bottom|center|centre|middle|corner|away|aside|back|home|here|out of the way|near|beside)\b", re.I)


def offline(text, history, toolbox):
    out = _offline(text, history, toolbox)
    out.setdefault("actions", [])
    return out


def _offline(text, history, toolbox):
    def tool(name, **kw):
        out = toolbox.run(name, kw)
        return {"reply": out["say"], "cards": [out["card"]] if out.get("card") else [], "tools": [name],
                "refresh": bool(out.get("refresh")), "actions": out.get("actions", [])}

    if HEAR.search(text):
        return {"reply": "Yes, I can hear you. The model is offline, so I'm limited.", "cards": [], "tools": [], "refresh": False}
    rest = ADDRESS.sub("", text).strip()
    if re.match(r"^\s*(?:(?:ok|okay|alright|right)[, ]+)?(good ?night|night night|nighty night|i'?m (?:going|off) to (?:bed|sleep)|heading to bed)\b", text, re.I):
        return {"reply": "Good night, Madam Swain.", "cards": [], "tools": [], "refresh": False}
    if GREET.search(text) and not rest:
        return {"reply": "%s, Madam Swain! The model is offline, but I can still search your files." % part_of_day()[1], "cards": [], "tools": [], "refresh": False}
    if rest:
        text = rest  # "Hey Jarvis, pull up X" routes as "pull up X"
    if THANKS.search(text):
        return {"reply": "Any time.", "cards": [], "tools": [], "refresh": False}
    m = CLOSE.match(text)
    if m:
        every = re.search(r"\b(clear|everything|all|the screen)\b", text, re.I)
        return tool("close_screen", what="all" if every else "top")
    m = BACK.match(text)
    if m:
        word = (m.group(1) or m.group(2) or "").lower()
        return tool("go_back", direction="forward" if word in ("forward", "next") else "back")
    mv = re.match(r"^\s*(?:please\s+)?(?:(?:can|could) you\s+)?(?:find|search(?: for)?|pull up|play|show)(?: me)?(?: a| some| the)?\s+(?:youtube\s+)?videos?\s+(?:on|about|of|for)\s+(.+)$", text, re.I) or \
        re.match(r"^\s*(?:please\s+)?play\s+(?:a\s+)?(?:youtube\s+)?(?:video\s+)?(?:of|on|about)\s+(.+)$", text, re.I)
    if mv:
        return tool("find_videos", query=mv.group(1).strip(" .?"))
    mw = re.match(r"^\s*(?:please\s+)?(?:watch|summari[sz]e)\s+(?:this\s+|that\s+)?(?:video\s+)?(https?://\S+)", text, re.I)
    if mw:
        return tool("watch_video", video=mw.group(1))
    ms = re.search(r"\b(trading|vault|markets?|charts?|desk|notes?|main|center|centre|home|first|second|other|right|left)\s+(?:screen|monitor|display|window)\b", text, re.I)
    if ms and re.search(r"\b(come|go|move|get|bring|appear|jump|head|over|here|show up|be on|meet)\b|jarvis", text, re.I) and not re.search(r"\b(close|open|scroll|show me|what)\b", text, re.I):
        return tool("move_screen", screen=ms.group(1).lower())
    if LAYERY.search(text) and re.search(r"\b(?:you|yourself|him|jarvis|orb)\b|^\s*(?:please\s+)?(?:come|step|stay|go|move|bring|send)", text, re.I) and not re.search(r"\b(?:note|page|card|screen|window)\b", text, re.I):
        low = text.lower()
        lay = "middle" if "middle" in low else "back" if re.search(r"\bback\b|behind|background", low) else "front"
        return tool("orb_layer", layer=lay)
    if ORBY.match(text) and not re.match(r"^\s*(?:please\s+)?go\b", text, re.I):
        return tool("move_orb", where=text)
    if SCROLLY.search(text):
        low = text.lower()
        if re.search(r"\btop\b|all the way up", low):
            d = "top"
        elif re.search(r"\bbottom\b|all the way down", low):
            d = "bottom"
        elif re.search(r"\bup\b", low):
            d = "up"
        else:
            d = "down"
        amt = "some"
        if re.search(r"a little|a bit|slightly|\bbit\b", low):
            amt = "little"
        elif re.search(r"a lot|\bfar\b|way more|much", low):
            amt = "lot"
        elif re.search(r"\bpage\b|screen ?full", low):
            amt = "page"
        return tool("scroll_screen", direction=d, amount=amt)
    if ORBY.match(text):
        return tool("move_orb", where=text)
    m = REMEMBER.match(text)
    if m:
        return tool("remember", fact=m.group(2).strip())
    mo = ORDER.match(text)
    if mo:
        return tool("broker", action="propose", side=mo.group(1).lower(), amount=float(mo.group(2)), symbol=mo.group(3).upper())
    mb = BROKER.search(text)
    if mb:
        return tool("broker", action="positions" if "position" in mb.group(1).lower() or "portfolio" in mb.group(1).lower() else "status")
    if TRADING.search(text):
        amt = re.search(r"\$?\s*(\d+(?:\.\d+)?)", text)
        low = text.lower()
        if amt and re.search(r"\b(change|set|make|raise|lower|update|to)\b", low) and "breaker" in low:
            return tool("trading", action="set_breaker", amount=float(amt.group(1)))
        if amt and re.search(r"\b(change|set|make|raise|lower|update|to)\b", low) and "sweep" in low:
            return tool("trading", action="set_sweep", amount=float(amt.group(1)))
        return tool("trading", action="status" if re.search(r"\bstatus\b", low) else "show")
    mw = WELL.search(text)
    if mw:
        w = mw.group(1).lower()
        act = "focus" if w.startswith("focus") else "spa" if w.startswith(("spa", "relaxation")) else "stop" if w.startswith("stop") else "tea" if ("tea" in w or "hydration" in w) else "quote"
        return tool("wellness", action=act)
    if PLAN.search(text):
        return tool("plan_day")
    if BRIEF.search(text):
        return tool("brief_me")
    if INBOX.search(text):
        return tool("read_inbox")
    m = WEB.match(text)
    if m:
        return tool("research_web", query=m.group(2).strip())
    m = SHOW.match(text)
    if m:
        return tool("show_on_screen", what=m.group(1).strip())
    hits = toolbox.vault.search(text, 3)
    if hits and hits[0]["coverage"] >= 0.5 and hits[0]["score"] >= 1.5:
        return tool("search_brain", query=text)
    return {"reply": "Model's offline, so I can't reason about that. Nothing in the files either.", "cards": [], "tools": [], "refresh": False}
