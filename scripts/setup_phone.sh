#!/bin/sh
# Lets JARVIS open on her iPhone through Tailscale: a private, encrypted link between only her own devices.
# Before running: install Tailscale on this Mac and on the iPhone, and sign in to both with the same account.
cd "$(dirname "$0")/.." || exit 1
TS="$(command -v tailscale || true)"
[ -z "$TS" ] && [ -x /Applications/Tailscale.app/Contents/MacOS/Tailscale ] && TS=/Applications/Tailscale.app/Contents/MacOS/Tailscale
if [ -z "$TS" ]; then
  echo "Tailscale is not installed on this Mac yet. Get it from https://tailscale.com/download/mac (or the Mac App Store), sign in, then run this again."
  exit 1
fi
NAME="$("$TS" status --json 2>/dev/null | python3 -c 'import json,sys; print(json.load(sys.stdin)["Self"]["DNSName"].rstrip("."))' 2>/dev/null)"
if [ -z "$NAME" ]; then
  echo "Tailscale is installed but not signed in. Open Tailscale from the menu bar, sign in, then run this again."
  exit 1
fi
echo "Sharing JARVIS privately with your own devices (Tailscale may ask you to approve HTTPS once; follow the link it shows)..."
"$TS" serve --bg 8765 || { echo "Tailscale could not share JARVIS. Copy what it said above and send it to me."; exit 1; }
touch .env
grep -v '^JARVIS_ALLOWED_HOSTS=' .env > .env.tmp && mv .env.tmp .env
echo "JARVIS_ALLOWED_HOSTS=$NAME" >> .env
chmod 600 .env
PL="$HOME/Library/LaunchAgents/com.jarvis.plist"
[ -f "$PL" ] && launchctl unload "$PL" 2>/dev/null; [ -f "$PL" ] && launchctl load "$PL"
echo ""
echo "Done. On your iPhone (with Tailscale switched on), open Safari and go to:"
echo ""
echo "   https://$NAME"
echo ""
echo "Then tap Share, then Add to Home Screen, so JARVIS opens like an app."
echo "To stop sharing: $TS serve --https=443 off"
