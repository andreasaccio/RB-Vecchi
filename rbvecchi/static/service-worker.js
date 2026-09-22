"use strict";
const CACHE_NAME = "rb-vecchi-static-v1";
const STATIC_ASSETS = [
  "/static/app.css",
  "/static/app.js",
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
  event.respondWith(caches.match(event.request).then((cached) => cached || fetch(event.request)));
});
