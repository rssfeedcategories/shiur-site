/* Caches the shell so the site opens instantly and works offline.
   Episode data is always fetched fresh, then falls back to cache. */
const SHELL = "ba-shell-v4";
const DATA  = "ba-data-v1";
const ASSETS = ["./", "./index.html", "./manifest.json"];

self.addEventListener("install", e => {
  e.waitUntil(caches.open(SHELL).then(c => c.addAll(ASSETS)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", e => {
  e.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.filter(k => k !== SHELL && k !== DATA).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", e => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== location.origin) return;

  // Audio is large and range-requested — let the browser handle it
  if (/\.(mp3|m4a)$/i.test(url.pathname)) return;

  if (url.pathname.includes("/data/")) {
    e.respondWith(
      fetch(e.request)
        .then(r => { const copy = r.clone(); caches.open(DATA).then(c => c.put(e.request, copy)); return r; })
        .catch(() => caches.match(e.request))
    );
    return;
  }

  e.respondWith(caches.match(e.request).then(hit => hit || fetch(e.request)));
});
