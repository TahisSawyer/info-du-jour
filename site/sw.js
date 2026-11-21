// Service worker : l'application s'ouvre hors ligne et affiche la dernière édition téléchargée.
const VERSION = "batnews-v4";
const COQUILLE = ["./", "index.html", "style.css", "app.js", "manifest.webmanifest", "icones/favicon-32.png", "icones/icone-192.png", "icones/apple-touch-icon.png"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(VERSION).then((c) => c.addAll(COQUILLE)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((cles) => Promise.all(cles.filter((k) => k !== VERSION).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== location.origin) return;
  const donnees = url.pathname.includes("/donnees/") || url.pathname.endsWith("config.json");
  if (donnees) {
    // réseau d'abord (édition fraîche), cache en secours (lecture hors ligne)
    const cle = url.origin + url.pathname;
    e.respondWith(fetch(e.request).then((r) => {
      if (r.ok && !url.pathname.endsWith(".mp3")) {
        const copie = r.clone();
        caches.open(VERSION).then((c) => c.put(cle, copie));
      }
      return r;
    }).catch(() => caches.match(cle).then((r) => r || new Response("{}", { status: 503, headers: { "Content-Type": "application/json" } }))));
    return;
  }
  // fichiers de l'application : cache d'abord, mise à jour en arrière-plan
  e.respondWith(caches.match(e.request).then((enCache) => {
    const reseau = fetch(e.request).then((r) => {
      if (r.ok) { const copie = r.clone(); caches.open(VERSION).then((c) => c.put(e.request, copie)); }
      return r;
    }).catch(() => enCache);
    return enCache || reseau;
  }));
});
