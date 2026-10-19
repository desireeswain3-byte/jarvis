// A transparent window the size of the screen, floating above everything. Clicks pass through it except on the orb.
const { app, BrowserWindow, ipcMain, screen } = require("electron");
const path = require("path");
const URL = process.env.JARVIS_URL || "http://localhost:8765/overlay.html";

app.whenReady().then(() => {
  const d = screen.getPrimaryDisplay().bounds;
  const win = new BrowserWindow({
    x: d.x, y: d.y, width: d.width, height: d.height,
    transparent: true, frame: false, hasShadow: false, resizable: false, movable: false,
    focusable: false, skipTaskbar: true, alwaysOnTop: true,
    webPreferences: { preload: path.join(__dirname, "preload.js"), contextIsolation: true, nodeIntegration: false },
  });
  win.setAlwaysOnTop(true, "screen-saver");
  win.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });
  win.setIgnoreMouseEvents(true, { forward: true });
  ipcMain.on("catch-mouse", (_e, on) => win.setIgnoreMouseEvents(!on, { forward: true }));
  win.loadURL(URL);
  win.webContents.on("did-fail-load", () => setTimeout(() => win.loadURL(URL), 2000));   // JARVIS not started yet: keep trying
});
app.on("window-all-closed", () => app.quit());
if (app.dock) app.dock.hide();
