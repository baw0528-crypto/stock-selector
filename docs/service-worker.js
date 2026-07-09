/**
 * オフラインでも直近のレポートを開けるようにするための最小限のキャッシュ戦略。
 * キャッシュするのは暗号化済みファイルのみなので、Cache Storage自体に
 * 平文のレポート内容が残ることはない。
 */
const CACHE_NAME = "stock-selector-dashboard-v4";
const SHELL_FILES = [
  "./",
  "index.html",
  "css/style.css",
  "js/app.js",
  "js/crypto.js",
  "manifest.json",
  "icons/icon-192.png",
  "icons/icon-512.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(SHELL_FILES))
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)))
      )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (event.request.method !== "GET" || url.origin !== location.origin) return;

  const isReportData = url.pathname.includes("/reports/");

  if (isReportData) {
    // 暗号化データ: できるだけ最新を取りに行き、オフライン時のみキャッシュを使う
    event.respondWith(
      fetch(event.request)
        .then((res) => {
          const clone = res.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
          return res;
        })
        .catch(() => caches.match(event.request))
    );
    return;
  }

  // アプリシェル: キャッシュ優先、裏で更新
  event.respondWith(
    caches.match(event.request).then((cached) => {
      const fetchPromise = fetch(event.request)
        .then((res) => {
          const clone = res.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
          return res;
        })
        .catch(() => cached);
      return cached || fetchPromise;
    })
  );
});
