#!/bin/sh
# One-time setup so JARVIS can keep the Mac awake during the trading day, even with the lid closed.
# It allows exactly two commands without a password: turning sleep off and back on. Nothing else.
# The password is asked for in the Mac's normal password box (with dots), not in Terminal.
set -e
ME="$(id -un)"
RULE="/etc/sudoers.d/jarvis-pmset"
TMP="$(mktemp /tmp/jarvis-pmset.XXXXXX)"
printf '%s ALL=(root) NOPASSWD: /usr/bin/pmset -a disablesleep 0, /usr/bin/pmset -a disablesleep 1\n' "$ME" > "$TMP"
# Wake the Mac a little before JARVIS's morning research (8:25 New York time, in your own time).
WAKE="$(python3 -c 'import datetime as d; from zoneinfo import ZoneInfo as Z; n=d.datetime.now(Z("America/New_York")).replace(hour=8,minute=25,second=0); print(n.astimezone().strftime("%H:%M:%S"))')"
CMD="/usr/sbin/visudo -cf $TMP && /usr/bin/install -m 0440 -o root -g wheel $TMP $RULE && /usr/bin/pmset repeat wakeorpoweron MTWRF $WAKE"
echo "A password box will pop up. Type your Mac password there and click OK."
if ! osascript -e "do shell script \"$CMD\" with prompt \"JARVIS needs your Mac password once, so he can stay awake during the trading day.\" with administrator privileges" >/dev/null; then
  rm -f "$TMP"
  echo "It was cancelled or the password was not accepted. Nothing was changed. Run this again to retry."
  exit 1
fi
rm -f "$TMP"
if sudo -n /usr/bin/pmset -a disablesleep 0; then
  echo "Done. On weekdays JARVIS keeps the Mac awake from the morning research until after the evening review, even with the lid closed."
  echo "It also wakes the Mac at $WAKE on weekdays. Keep it plugged in."
  echo "To undo all of this: sudo rm $RULE && sudo pmset repeat cancel"
else
  echo "Something did not work. Send JARVIS's builder a photo of this window."
  exit 1
fi
