/* Service worker : coquille d'application hors-ligne.
   Le temps réel (WebSocket) n'est jamais mis en cache.

   Stratégie de navigation : la coquille en cache est affichée instantanément
   pendant que le réseau répond (stale-while-revalidate avec délai court).
   Sur Render, l'instance gratuite s'endort après ~15 min : au réveil, la page
   s'affiche tout de suite depuis le cache au lieu de rester sur un écran blanc. */
const CACHE = "daily-muslim-v4";
const SHELL = ["./", "./manifest.webmanifest", "./api/icon-192.png", "./api/icon-512.png",
               "./assets/mosque-bg.jpg"];
const NAV_TIMEOUT_MS = 2500;

self.addEventListener("install", (e) => {
  self.skipWaiting();
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL).catch(() => {})));
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
  const url = new URL(req.url);
  if (req.method !== "GET") return;
  // Ne jamais intercepter l'API ni les WebSockets.
  if (url.pathname.startsWith("/api/") || url.pathname.startsWith("/ws/")) return;

  // Navigation : cache en secours rapide pendant que le réseau répond.
  if (req.mode === "navigate") {
    e.respondWith(navigationResponse(req));
    return;
  }
  // Autres GET : cache d'abord.
  e.respondWith(
    caches.match(req).then((hit) => hit || fetch(req).then((r) => {
      if (r.ok && url.origin === location.origin) {
        const copy = r.clone();
        caches.open(CACHE).then((c) => c.put(req, copy)).catch(() => {});
      }
      return r;
    }).catch(() => hit))
  );
});

async function navigationResponse(req) {
  const network = fetch(req).then((r) => {
    if (r && r.ok) {
      const copy = r.clone();
      caches.open(CACHE).then((c) => c.put("./", copy)).catch(() => {});
    }
    return r;
  });
  // Réseau rapide → page fraîche ; réseau lent (instance en veille) ou hors-ligne
  // → coquille mise en cache, sans attendre.
  const winner = await Promise.race([
    network,
    new Promise((resolve) => setTimeout(resolve, NAV_TIMEOUT_MS)),
  ]);
  if (winner instanceof Response) return winner;
  const hit = await caches.match("./");
  if (hit) return hit;
  return network; // aucun cache : on attend (ou échoue) le réseau
}
