/* Service worker: cache della shell per uso offline/PWA.
   Network-first per HTML/JS (cosi' il telefono aggiornato vede sempre
   l'ultima versione anche dopo un refresh), cache-first per asset statici. */
const CACHE = "orchestra-shell-v2";
const SHELL = ["/", "/app.css", "/app.js", "/icon.svg", "/icon-192.png", "/icon-512.png", "/manifest.webmanifest"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).catch(() => {}));
  self.skipWaiting();
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;
  // Non cachare le API: sempre rete.
  if (url.pathname.startsWith("/api/")) return;
  const isShell = url.pathname === "/" || url.pathname.endsWith(".js") || url.pathname.endsWith(".html");
  if (isShell) {
    // Network-first: prova la rete, fallback alla cache.
    e.respondWith(
      fetch(req).then((res) => {
        if (res && res.status === 200 && res.type === "basic") {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(req, copy)).catch(() => {});
        }
        return res;
      }).catch(() => caches.match(req))
    );
  } else {
    // Cache-first per asset statici (immagini, css, manifest).
    e.respondWith(
      caches.match(req).then((cached) => {
        const net = fetch(req).then((res) => {
          if (res && res.status === 200 && res.type === "basic") {
            const copy = res.clone();
            caches.open(CACHE).then((c) => c.put(req, copy)).catch(() => {});
          }
          return res;
        }).catch(() => cached);
        return cached || net;
      })
    );
  }
});
