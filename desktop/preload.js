// Runs in a sandboxed, isolated context before the page loads. Exposes
// exactly one thing to the page: a real Windows location lookup that
// bypasses Chromium's own broken geolocation (see main.js's
// getWindowsLocation() for why). The page checks for
// window.orionDesktop.getLocation and falls back to plain
// navigator.geolocation when it's absent (i.e. an ordinary browser tab,
// not the desktop app) - see orionGetCurrentPosition() in index.html
// and mobile.html.
const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("orionDesktop", {
  getLocation: () => ipcRenderer.invoke("get-windows-location"),
});
