// 서비스 워커: 앱 셸만 네트워크 우선으로 캐시한다(오프라인 시 마지막 셸 표시).
// 오디오(/audio/)와 타 도메인 요청은 건드리지 않는다 → Safari의 Range 요청 재생이 깨지지 않음.
const V = "miradio-v1";
const SHELL = ["./", "index.html", "style.css", "app.js", "icon-192.png"];
self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(V).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});
self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((ks) => Promise.all(ks.filter((k) => k !== V).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});
self.addEventListener("fetch", (e) => {
  const u = new URL(e.request.url);
  if (e.request.method !== "GET" || u.origin !== location.origin ||
      u.pathname.includes("/audio/") || u.pathname.endsWith("manifest.json")) return;
  e.respondWith(
    fetch(e.request)
      .then((r) => { if (r.ok) { const c = r.clone(); caches.open(V).then((x) => x.put(e.request, c)); } return r; })
      .catch(() => caches.match(e.request))
  );
});
