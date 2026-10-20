'use strict';
const SHELL='xh-sync-shell-v3', FILES=['/','/assets/style.css','/assets/app.js','/assets/icon.svg','/assets/voice-mark.svg','/assets/manifest.webmanifest'];
self.addEventListener('install',e=>e.waitUntil(caches.open(SHELL).then(c=>c.addAll(FILES))));
self.addEventListener('activate',e=>e.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(k=>k!==SHELL).map(k=>caches.delete(k))))));
self.addEventListener('fetch',e=>{const u=new URL(e.request.url);if(u.origin!==self.location.origin||e.request.method!=='GET'||!FILES.includes(u.pathname))return;e.respondWith(fetch(e.request).then(r=>{if(r.ok){const copy=r.clone();caches.open(SHELL).then(c=>c.put(e.request,copy));}return r;}).catch(()=>caches.match(e.request)));});
