// ORION desktop shell. This is one more client of the existing FastAPI
// server (api.py) — same as a browser tab — not a separate app or a
// separate brain.
//
// Two modes, chosen by app.isPackaged (never mixed):
//   - Dev (npm start, running from source): spawns/attaches to a LOCAL
//     server, exactly as before — this is the user's own daily-use path.
//   - Packaged (the built .exe, handed to friends): friends' machines
//     have no Python/Ollama install to spawn, so this mode never spawns
//     anything — it only ever connects to the host PC's own server over
//     the network, per orion-remote.json (bundled into the build).

const { app, BrowserWindow, Tray, Menu, nativeImage, session, ipcMain } = require("electron");
const { spawn } = require("child_process");
const path = require("path");
const fs = require("fs");
const http = require("http");

// get_location.ps1 must be spawned as an external process (PowerShell
// can't read files out of app.asar - only Electron's own asar-aware fs
// layer can), so package.json's asarUnpack keeps a real, plain copy
// alongside the archive. That copy lives under app.asar.unpacked/, not
// app.asar/, hence the path rewrite - a no-op in dev mode, where
// __dirname never contains "app.asar" at all.
const LOCATION_SCRIPT_PATH = path.join(__dirname, "get_location.ps1").replace("app.asar", "app.asar.unpacked");
const PRELOAD_PATH = path.join(__dirname, "preload.js");

const HOST = "127.0.0.1";
const PORT = 8000;
const LOCAL_SERVER_URL = `http://${HOST}:${PORT}`;

const PROJECT_ROOT = path.resolve(__dirname, "..");
const PYTHON = path.join(PROJECT_ROOT, ".venv", "Scripts", "python.exe");
const ICON_PATH = path.join(__dirname, "app-icon.png");
const REMOTE_CONFIG_PATH = path.join(__dirname, "orion-remote.json");

let mainWindow = null;
let tray = null;
let serverProcess = null;
let weStartedTheServer = false;
let isQuitting = false;
let remoteRetryTimer = null;

function loadRemoteUrl() {
  try {
    const cfg = JSON.parse(fs.readFileSync(REMOTE_CONFIG_PATH, "utf8"));
    return cfg.remoteUrl || null;
  } catch (err) {
    return null;
  }
}

// Electron's Chromium engine enforces the exact same secure-context
// rule as any browser: geolocation/getUserMedia are simply absent
// (not "ask and deny" - outright missing from `navigator`) outside
// https:// or http://localhost/127.0.0.1. LOCAL_SERVER_URL already
// qualifies natively - loopback addresses are always "potentially
// trustworthy" per the spec, no flag needed. The packaged friends-
// build's remoteUrl (a LAN IP, e.g. http://10.0.0.195:8000) does NOT -
// that's the one real gap between "the web app on localhost" and "the
// desktop app," since a friend's own independent browser can't be
// asked to launch with special flags, but this Electron shell is a
// single-purpose client we fully control end to end. Must run before
// app.whenReady() - Chromium only reads this switch at process launch,
// so it has to happen at require-time, before any other app.* call.
const remoteUrlForSecureContext = loadRemoteUrl();
if (remoteUrlForSecureContext) {
  app.commandLine.appendSwitch("unsafely-treat-insecure-origin-as-secure", remoteUrlForSecureContext);
}

function checkHealth(baseUrl) {
  return new Promise((resolve) => {
    const req = http.get(`${baseUrl}/health`, { timeout: 1500 }, (res) => {
      res.resume();
      resolve(res.statusCode === 200);
    });
    req.on("timeout", () => req.destroy());
    req.on("error", () => resolve(false));
  });
}

async function waitForServer(baseUrl, maxAttempts = 60, intervalMs = 1000) {
  for (let attempt = 0; attempt < maxAttempts; attempt++) {
    if (await checkHealth(baseUrl)) return true;
    await new Promise((r) => setTimeout(r, intervalMs));
  }
  return false;
}

function spawnServer() {
  serverProcess = spawn(
    PYTHON,
    ["-m", "uvicorn", "api:app", "--host", HOST, "--port", String(PORT)],
    {
      cwd: PROJECT_ROOT,
      stdio: ["ignore", "pipe", "pipe"],
      windowsHide: true,
    },
  );
  weStartedTheServer = true;
  serverProcess.stdout.on("data", (d) => process.stdout.write(`[orion-server] ${d}`));
  serverProcess.stderr.on("data", (d) => process.stderr.write(`[orion-server] ${d}`));
  serverProcess.on("exit", (code) => {
    console.log(`ORION server process exited (code ${code})`);
    serverProcess = null;
  });
}

async function ensureLocalServerRunning() {
  if (await checkHealth(LOCAL_SERVER_URL)) {
    console.log("ORION server already running — attaching as a client, not spawning another.");
    return;
  }
  console.log("No ORION server detected — starting one now.");
  spawnServer();
  const up = await waitForServer(LOCAL_SERVER_URL);
  if (!up) console.error("ORION server did not become healthy in time.");
}

// Chromium's own navigator.geolocation fails inside Electron regardless
// of the permission handler below (open-source Electron ships without
// Google's geolocation API key, so its network-based lookup always
// errors out) - see get_location.ps1's header comment. This queries
// Windows' own native location service instead, which needs no API key,
// and is what preload.js's window.orionDesktop.getLocation() calls into
// via IPC. A few hundred ms of WinRT startup overhead per call is fine
// for an on-demand button click; this is never polled continuously.
function getWindowsLocation() {
  return new Promise((resolve, reject) => {
    const proc = spawn("powershell.exe", ["-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", LOCATION_SCRIPT_PATH], {
      windowsHide: true,
    });
    let stdout = "";
    proc.stdout.on("data", (d) => { stdout += d; });
    proc.on("error", reject);
    proc.on("exit", () => {
      try {
        const result = JSON.parse(stdout.trim());
        if (result.ok) resolve({ lat: result.lat, lon: result.lon, accuracy: result.accuracy_m });
        else reject(new Error(result.error || "Windows location lookup failed"));
      } catch (err) {
        reject(new Error("Could not parse Windows location output: " + stdout.slice(0, 200)));
      }
    });
  });
}

ipcMain.handle("get-windows-location", () => getWindowsLocation());

function remoteUnreachablePage(remoteUrl) {
  const html = `<!doctype html><html><body style="margin:0;height:100vh;display:flex;align-items:center;justify-content:center;background:#04080b;color:#cfe9ef;font-family:'JetBrains Mono',monospace;text-align:center">
    <div>
      <div style="font-size:20px;letter-spacing:.3em;color:#eafcff;margin-bottom:18px">ORION</div>
      <div style="font-size:13px;color:#84a6ae;line-height:1.6">Can't reach ORION at<br><span style="color:#4fd6e8">${remoteUrl}</span><br><br>Make sure the host PC is on and<br>you're on the same Wi-Fi network.<br><br>Retrying automatically…</div>
    </div>
  </body></html>`;
  return "data:text/html;charset=utf-8," + encodeURIComponent(html);
}

function createWindow(targetUrl, { isRemote } = {}) {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 820,
    minWidth: 900,
    minHeight: 600,
    backgroundColor: "#05070a",
    autoHideMenuBar: true,
    icon: ICON_PATH,
    webPreferences: {
      contextIsolation: true,
      sandbox: true,
      preload: PRELOAD_PATH,
    },
  });
  Menu.setApplicationMenu(null);

  const attemptLoad = () => mainWindow.loadURL(targetUrl);

  if (isRemote) {
    // The loaded page's own <title>ORION</title> would otherwise win
    // every navigation (Electron syncs window title to document.title
    // by default) — pin it to the friends-build branding instead.
    mainWindow.setTitle("ORION v1.2");
    mainWindow.on("page-title-updated", (event) => {
      event.preventDefault();
      mainWindow.setTitle("ORION v1.2");
    });
    mainWindow.webContents.on("did-fail-load", () => {
      clearTimeout(remoteRetryTimer);
      mainWindow.loadURL(remoteUnreachablePage(targetUrl));
      remoteRetryTimer = setTimeout(attemptLoad, 4000);
    });
  }
  attemptLoad();

  mainWindow.on("close", (event) => {
    if (isQuitting) return;
    event.preventDefault();
    mainWindow.hide();
  });
}

function createTray() {
  const icon = nativeImage.createFromPath(ICON_PATH).resize({ width: 32, height: 32 });
  tray = new Tray(icon);
  tray.setToolTip("ORION");
  tray.setContextMenu(
    Menu.buildFromTemplate([
      {
        label: "Show ORION",
        click: () => {
          mainWindow.show();
          mainWindow.focus();
        },
      },
      { type: "separator" },
      {
        label: "Quit ORION",
        click: () => {
          isQuitting = true;
          app.quit();
        },
      },
    ]),
  );
  tray.on("double-click", () => {
    mainWindow.show();
    mainWindow.focus();
  });
}

// Electron denies geolocation/camera/mic/notification permission
// requests by default unless the app explicitly opts in here — unlike a
// real browser, there's no native OS-style permission bubble to grant,
// so without this handler every getCurrentPosition()/getUserMedia() call
// from the loaded page silently fails every time, no matter what the
// user clicks (there's nothing to click). Safe to allow broadly since
// this window only ever loads ORION's own server (LOCAL_SERVER_URL, a
// configured remoteUrl, or the small inline unreachable-host fallback
// page) — never arbitrary third-party content — and the browser-side
// APIs (navigator.geolocation, getUserMedia) are the same ones already
// used, and already permission-gated, in an ordinary browser tab.
function installPermissionHandler() {
  session.defaultSession.setPermissionRequestHandler((webContents, permission, callback) => {
    callback(["geolocation", "media", "notifications"].includes(permission));
  });
}

app.whenReady().then(async () => {
  installPermissionHandler();
  if (app.isPackaged) {
    // Friends build: never spawn — their machine has no Python/Ollama
    // to spawn. Connect straight to the host PC over the network.
    const remoteUrl = loadRemoteUrl() || LOCAL_SERVER_URL;
    createWindow(remoteUrl, { isRemote: true });
  } else {
    await ensureLocalServerRunning();
    createWindow(LOCAL_SERVER_URL);
  }
  createTray();
});

app.on("window-all-closed", () => {
  // Close-to-tray is the intended behavior (handled in the window's
  // 'close' listener above) — this only fires on a real app quit.
});

app.on("before-quit", () => {
  isQuitting = true;
  clearTimeout(remoteRetryTimer);
  if (weStartedTheServer && serverProcess) {
    serverProcess.kill();
  }
});
