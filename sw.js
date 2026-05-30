const CACHE = 'vnstock-v1'
const PRECACHE = ['./', './index.html']

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(PRECACHE)))
  self.skipWaiting()
})

self.addEventListener('activate', e => {
  e.waitUntil(caches.keys().then(keys =>
    Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))
  ))
  self.clients.claim()
})

self.addEventListener('fetch', e => {
  if (e.request.method !== 'GET') return
  const url = new URL(e.request.url)
  if (url.origin !== location.origin) return
  e.respondWith(
    fetch(e.request).then(r => {
      const clone = r.clone()
      caches.open(CACHE).then(c => c.put(e.request, clone))
      return r
    }).catch(() => caches.match(e.request))
  )
})
