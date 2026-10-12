"use strict";
// CSS e JS arrivano con ?v=<impronta di static/> (impronta_static in web.py):
// una versione nuova è un URL nuovo, quindi la cache può servire per prima.
// Icone e manifest non hanno versione: se cambiano, cambiare CACHE_NAME.
const CACHE_NAME = "rb-vecchi-static-v10";
const STATIC_ASSETS = [
  "/static/icon-180.png",
  "/static/icon-192.png",
  "/static/icon-512.png",
  "/manifest.webmanifest"
];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE_NAME).then((cache) => cache.addAll(STATIC_ASSETS)));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))))
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (event.request.method !== "GET" || url.origin !== self.location.origin) return;
  if (!url.pathname.startsWith("/static/") && url.pathname !== "/manifest.webmanifest") return;
  event.respondWith(caches.open(CACHE_NAME).then(async (cache) => {
    const cached = await cache.match(event.request);
    if (cached) return cached;
    const response = await fetch(event.request);
    if (response.ok && url.searchParams.has("v")) cache.put(event.request, response.clone());
    return response;
  }));
});
