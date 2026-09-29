// ORION's service worker — exists to satisfy PWA installability (most
// browsers require a registered SW with a fetch handler before offering
// "Add to Home Screen"), not to fake offline functionality. This app is
// a client of a live local server; chat, telemetry, and tool results are
// meaningless if served stale from a cache, so only the static app shell
// (this file's own assets) is cached — every API call always goes to the
// real network, never intercepted here.
const SHELL_CACHE = "orion-shell-v1";
const SHELL_ASSETS = ["/", "/manifest.json", "/icon-192.png", "/icon-512.png"];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(SHELL_CACHE).then((cache) => cache.addAll(SHELL_ASSETS)).catch(() => {})
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== SHELL_CACHE).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  const isShellAsset = SHELL_ASSETS.includes(url.pathname);
  if (!isShellAsset || event.request.method !== "GET") return; // let the network handle everything else untouched

  event.respondWith(
    fetch(event.request)
      .then((response) => {
        const copy = response.clone();
        caches.open(SHELL_CACHE).then((cache) => cache.put(event.request, copy));
        return response;
      })
      .catch(() => caches.match(event.request))
  );
});
