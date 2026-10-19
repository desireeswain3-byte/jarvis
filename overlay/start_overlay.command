#!/bin/bash
# Double-click this to show JARVIS floating over your whole screen. Close it with Control-C or by closing this Terminal window.
cd "$(dirname "$0")"
if ! command -v node >/dev/null 2>&1; then
  echo "Node.js is not installed. Get the free installer at https://nodejs.org (choose LTS), install it, then double-click this file again."
  read -p "Press Return to close." x; exit 1
fi
if [ ! -d node_modules ]; then echo "First time only: downloading the overlay (about 1 minute)..."; npm install --no-audit --no-fund || { echo "Install failed."; read -p "Press Return." x; exit 1; }; fi
echo "JARVIS overlay is starting. Make sure JARVIS itself is running."
npm start
