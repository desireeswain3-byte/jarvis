#!/bin/sh
# One-time setup so JARVIS can keep the Mac awake during the trading day, even with the lid closed.
# It allows exactly two commands without a password: turning sleep off and back on. Nothing else.
set -e
ME="$(id -un)"
RULE="/etc/sudoers.d/jarvis-pmset"
TMP="$(mktemp)"
printf '%s ALL=(root) NOPASSWD: /usr/bin/pmset -a disablesleep 0, /usr/bin/pmset -a disablesleep 1\n' "$ME" > "$TMP"
echo "Your Mac password is needed once (nothing shows on screen while you type it)."
sudo /usr/sbin/visudo -cf "$TMP" >/dev/null
sudo install -m 0440 -o root -g wheel "$TMP" "$RULE"
rm -f "$TMP"
# Wake the Mac a little before JARVIS's morning research (8:25 New York time, shown here in your own time).
WAKE="$(python3 -c 'import datetime as d; from zoneinfo import ZoneInfo as Z; n=d.datetime.now(Z("America/New_York")).replace(hour=8,minute=25,second=0); print(n.astimezone().strftime("%H:%M:%S"))')"
sudo /usr/bin/pmset repeat wakeorpoweron MTWRF "$WAKE"
if sudo -n /usr/bin/pmset -a disablesleep 0; then
  echo "Done. On weekdays JARVIS keeps the Mac awake from the morning research until after the evening review, even with the lid closed."
  echo "It also wakes the Mac at $WAKE on weekdays. Keep it plugged in."
  echo "To undo all of this: sudo rm $RULE && sudo pmset repeat cancel"
else
  echo "Something did not work. Nothing was changed."
  exit 1
fi
