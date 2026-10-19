const { contextBridge, ipcRenderer } = require("electron");
contextBridge.exposeInMainWorld("jarvisOverlay", { catchMouse: (on) => ipcRenderer.send("catch-mouse", !!on) });
