# JARVIS

A voice-controlled assistant that reads your notes as a graph. Python standard library on the server, vanilla JS in the browser. No packages, no build step.

## Run it

```
cd jarvis
python3 agent/main.py
```

It opens http://localhost:8765. It starts in demo mode with invented data, so it is safe to screen-record. You can type to it with no keys at all.

## Add your keys

```
cp .env.example .env
chmod 600 .env
```

Then edit `.env`:

| Key | What it does | Without it |
| --- | --- | --- |
| `ELEVENLABS_API_KEY` | Speech out (text to speech) and speech in (Scribe) | Voice is off. A red badge says so. Typing still works. |
| `ANTHROPIC_API_KEY` | The model that talks and chooses tools | Routing falls back to scoring your question against the files. A red MODEL MISSING badge shows. |

Both keys stay on the Python server. The browser only ever posts text to `/api/speak` and audio to `/api/listen`.

Using the model and ElevenLabs costs money on your accounts. JARVIS never calls anything else that costs money.

## Make it yours

1. Fill in `CLAUDE.md`. Anything still inside « » is treated as unset.
2. In `.env` set `JARVIS_DEMO=0` and `JARVIS_FOLDERS=/path/one:/path/two` (use `;` between paths on Windows).
3. Optional exports for the inbox, calendar and invoices: put `inbox.json`, `calendar.json` and `ledger.json` in `data/`. The formats match `data/demo/*.json`. Without them those tools say they are not connected. They never invent anything.

Demo mode is on unless `JARVIS_DEMO=0`. That variable is read in one file only, `agent/data.py`.

## Using it

- Press the mic once, then talk. When you go quiet for 900 ms the turn is sent. The constant is `SILENCE_MS` at the top of `ui/app.js`.
- The mic goes deaf while JARVIS speaks. To interrupt: mic button, Space, or Esc.
- Graph: hover to light a node's links, click to open it, shift-click a second node to trace the shortest path, drag the background to pan, scroll to zoom, drag a node to move it.
- Buttons: Mic, Mute, Brief, Plan, Memory, Dock, Roam, Hands.

Try: "what's the retainer price", "brief me", "who's emailed that I don't know", "plan my day".

## Screen control: show me things

JARVIS can put things on screen, scroll them, and move around while it does. Type these or say them:

- **Show:** "show me the studio handbook", "pull up Marlow Bikes", "open INV-1004", "show invoices", "show my inbox". A note opens in a viewer in the middle of the screen, with its links clickable. Opening is read only, and JARVIS does not read the contents aloud, it says what it opened.
- **If the name is not clear:** "show meeting" lists the matches and asks which one. It never opens a near miss. A name that is not in your files is reported as not found.
- **Scroll:** "scroll down", "scroll up a little", "scroll down a lot", "go to the top", "all the way to the bottom". It scrolls the viewer, or the top card, or pans the graph if nothing is open. Arrow keys, Page Up and Page Down, Home and End work too, and the up and down buttons in the viewer scroll while you hold them.
- **Hands:** with Hands on, pinch the note text and drag up or down to scroll it, with a little momentum when you let go. Pinch the viewer's title bar to carry the whole panel.
- **Move JARVIS:** "move to the left", "top right corner", "move to the center", "get out of the way" (docks it), "come back" (home).
- **Close and back:** "close that", "clear the screen", "go back", "forward". Esc closes the viewer.
- **Roam:** by default the orb glides beside whatever it shows, choosing the spot that covers the least, then returns to where it was when you close things. The Roam button turns that off (it then reads Still). If you docked the orb yourself it stays docked.

Scroll, move and close commands are silent. They only act, so you can chain them.

## Orb dock and hand tracking

- **Dock:** drag the orb to a screen edge and it slides to the side, leaving part of it showing. It keeps animating, listening and speaking while docked. Tap it, or press Dock, to slide it back out.
- **Hands:** press Hands, allow the camera, and a ring follows your hand. Pinch thumb to index finger to grab. A pinch presses, drags and releases like a mouse, so it works on the graph nodes, buttons, cards and panels. Pinch with both hands on the graph background and pull apart to zoom.
- The first time you press Hands it downloads the MediaPipe library and hand model from jsdelivr.net and storage.googleapis.com, so it needs internet. Your camera video is processed in the browser and is never sent to any server. If the download fails, a red alert says so.
- **Big screens:** the interface scales up with the screen (up to 2x), and the graph fills the space. The Hand reach slider in the right panel sets how far a small hand movement travels. It starts higher on bigger screens and is remembered in your browser.
- Tuning knobs are in `HANDS_CFG` at the top of `ui/hands.js` (pinch thresholds, smoothing, edge margin).

## Layout

```
jarvis/
  agent/   main.py (server), vault.py, tools.py, data.py, voice.py, memory.py, prompt.md, llm.py
  ui/      index.html, app.js, screen.js (viewer, scrolling, orb moves), graph.js, dock.js, hands.js, styles.css
  data/    generate_demo.py and the demo fixtures it writes
  memory/  one dated markdown file per remembered fact
  CLAUDE.md, .env, README.md
```

`llm.py` is the one file beyond the structure you specified. It holds the model client and the offline router.

## Guardrails

- It never sends anything. There is no send tool.
- It reads your folders and never writes to them. Writes go to `memory/` only.
- Every memory write is said out loud. The code enforces this even if the model forgets.
- Text inside files, emails and web results is wrapped as untrusted data. Anything that looks like an instruction is flagged on screen, not obeyed. The demo data includes two examples.
- A part payment is never called a discount. Invoice lines carry their qualifier.

## Limits worth knowing

- The live caption shows "Listening" and "Hearing you" from the real mic level, then your transcript once Scribe returns it. Word-by-word captions would need a streaming transcriber, which does not fit the standard-library constraint.
- PDF text extraction is best effort and standard library only. Scanned PDFs yield nothing.
- The web tool uses DuckDuckGo's HTML page. It is free, and it can break if that page changes.
- The server binds to 127.0.0.1 and rejects requests whose Host or Origin is not local.

## Voice and accent

The side panel has a Voice menu listing every voice on your ElevenLabs account, British ones first. Pick one and it plays a sample, and the choice is remembered in that browser. For a stronger accent, choose a voice labelled british, then lower `ELEVENLABS_STABILITY` or raise `ELEVENLABS_STYLE` in `.env`. The wording is set in the Manner section of `agent/prompt.md`: plain, warm and dry with a light British lean. The dashboard file has the same menu using your browser's own voices.

## Broker (optional)
JARVIS can read an Alpaca account and line up orders. Practice (paper) is the default. The model can only propose an order; nothing is sent until you press Confirm on screen with a real click. Limits: a dollar cap per order, a cap on orders per day, and no new orders once the day's loss reaches the circuit breaker. Real money needs ALPACA_MODE=live and ALPACA_ALLOW_LIVE=yes in .env. This is software, not investment advice, and trading can lose money.

## Free local voice

JARVIS speaks with, in order: a local neural voice (Kokoro, British male) if you have set it up, then the Mac's own built-in voice, then ElevenLabs.
To set up the local voice, run once: `python3 ~/jarvis/agent/setup_voice.py`. It needs about 115 MB and nothing leaves the Mac.
Force an engine with `VOICE_ENGINE=kokoro`, `mac` or `eleven` in `.env`. Pick the voice in the right-hand panel, or set `KOKORO_VOICE` (bm_george, bm_fable, bm_lewis, bm_daniel) and `KOKORO_SPEED`.

Lighter option: `python3 ~/jarvis/agent/setup_voice.py --piper` sets up Piper (voice: Alan, British male, about 65 MB) in its own private folder. Auto picks Kokoro first, then Piper, then the Mac voice.

## Free listening (no ElevenLabs credits)
In Chrome, the Mic button now uses Chrome's own speech recognition, so listening costs nothing. ElevenLabs is only used as a backup if Chrome's recognition fails to start. To force the old way, run `localStorage.setItem("jarvis.freestt","0")` in the browser console.

## See-through overlay (JARVIS floating over your whole screen)
1. Install Node.js once from https://nodejs.org (LTS).
2. Start JARVIS as usual.
3. Double-click `overlay/start_overlay.command` (right-click, Open the first time). The first run downloads Electron.
JARVIS then floats above everything. Clicks pass through everywhere except on the orb, and you can drag him. Say "move to the top left" or "go to the bottom right" and he glides there. The Mic and voice stay in the Chrome tab, so keep that tab open.

---
Copyright (c) 2026 Desiree Swain. All rights reserved. See LICENSE. Do not copy or reuse without written permission.
