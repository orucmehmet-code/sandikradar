/* Çevrimdışı kabuk — göreli yollar (GitHub Pages alt dizini için şart).
   Strateji: ağ öncelikli, ağ yoksa önbellek. data/ istekleri 60 sn'lik taze
   önbellekten gelir ki panel çevrimdışıyken son listeyi gösterebilsin. */
const CACHE = "sandikradar-v1";
const SHELL = ["./", "index.html", "app.js", "styles.css", "manifest.webmanifest", "icon.svg"];

self.addEventListener("install", e => {
  e.waitUntil(caches.open(CACHE)
    .then(c => c.addAll(SHELL).catch(() => {}))
    .then(() => self.skipWaiting()));
});

self.addEventListener("activate", e => {
  e.waitUntil(caches.keys()
    .then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener("fetch", e => {
  const req = e.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== location.origin) return;           // köprü/TikTok isteklerine dokunma
  if (url.pathname.includes("/api/")) return;
  e.respondWith(
    fetch(req).then(res => {
      const copy = res.clone();
      caches.open(CACHE).then(c => c.put(req, copy)).catch(() => {});
      return res;
    }).catch(() => caches.match(req).then(r => r || caches.match("index.html")))
  );
});
