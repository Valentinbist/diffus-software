// The service worker: what makes the site installable, and what shows the
// German offline page instead of the browser's own when a page can't load.
//
// It is deliberately narrow. Every page of this app sits behind HTTP Basic
// auth, and main.ts already forbids htmx from snapshotting one into its own
// history cache; the same rule holds here. So:
//
//   - a page navigation goes to the network, always, and only a *failed* one
//     gets the offline page — nothing a page ever returned is stored;
//   - the built, content-hashed files under /static/dist/assets/ are served
//     cache-first (a new build has new names, so a stale entry can't exist);
//   - the rest of /static/ (manifest, icons, offline page) is network-first,
//     falling back to the copy from the last successful fetch;
//   - everything else — htmx partials, /media/…, /healthz, anything cross-
//     origin, any non-GET — is not intercepted at all.
//
// __BUILD_ID__ is baked in by vite.config.ts, so every build is a byte-
// different worker: browsers install it, `activate` drops the previous
// build's cache, and the offline page is precached afresh.
//
// Served at /sw.js by app.py (a worker only controls URLs at or below its
// own path, so from under /static/dist/ it could never see a page).

declare const __BUILD_ID__: string;

const sw = self as unknown as ServiceWorkerGlobalScope;

const CACHE = `diffus-${__BUILD_ID__}`;
const STATIC = "/static/";
const HASHED = "/static/dist/assets/";
const OFFLINE = "/static/dist/offline.html";

sw.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(CACHE)
      .then((cache) => cache.add(OFFLINE))
      .then(() => sw.skipWaiting()),
  );
});

sw.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => sw.clients.claim()),
  );
});

sw.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin !== sw.location.origin) return;

  if (request.mode === "navigate") {
    event.respondWith(fetch(request).catch(offlinePage));
  } else if (url.pathname.startsWith(HASHED)) {
    event.respondWith(cacheFirst(request));
  } else if (url.pathname.startsWith(STATIC)) {
    event.respondWith(networkFirst(request));
  }
});

async function cacheFirst(request: Request): Promise<Response> {
  const cached = await caches.match(request);
  if (cached) return cached;
  const response = await fetch(request);
  await store(request, response);
  return response;
}

async function networkFirst(request: Request): Promise<Response> {
  try {
    const response = await fetch(request);
    await store(request, response);
    return response;
  } catch (err) {
    const cached = await caches.match(request);
    if (cached) return cached;
    throw err;
  }
}

// Only a plain 200: a 206 can't be put into a cache, and a 404 must not be.
async function store(request: Request, response: Response): Promise<void> {
  if (response.status !== 200) return;
  const cache = await caches.open(CACHE);
  await cache.put(request, response.clone());
}

async function offlinePage(): Promise<Response> {
  const cached = await caches.match(OFFLINE);
  if (cached) return cached;
  // Precache gone (evicted, or the install never finished): still say so in
  // words, not with the browser's dinosaur.
  return new Response("Offline.", {
    status: 503,
    headers: { "Content-Type": "text/plain; charset=utf-8" },
  });
}
