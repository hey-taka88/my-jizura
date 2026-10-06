/* ============================================================
   my-jizura (fork) — media layer: video clips (Phase 2)
   · a clip is kept as its file (Blob → object URL) and shown through one muted <video> element
   · preview  : M.syncPreview() lets the element play and nudges playbackRate to follow the song (a seek only on a
                jump: a loop seam, a bar restart, ping-pong backwards, scrubbing). Shared uses at different times
                are copied with the same decoder, keeping the last complete pictures while preparing the next ones.
   · export   : M.prepareFrame() seeks every needed clip to its exact time for each output frame (awaited by the
                MP4 / PNG loops); when one clip is needed at two times (a loop seam), the other time is copied first
   · at most MAX_LIVE elements hold a decoder; the least recently used ones are unloaded (src removed)
   ============================================================ */
(() => {
'use strict';
const M = (J.media = J.media || {});
const MAX_LIVE = 3;
const VIDEO_EXT = /\.(mp4|m4v|webm|mov|ogv)$/i;
M.isVideoFile = f => !!f && (/^video\//.test(f.type || '') || VIDEO_EXT.test(f.name || ''));

const once = (el, ev, ms, signal, ready) => new Promise((res, rej) => {
  if (signal && signal.aborted) { rej(new Error('aborted')); return; }
  let timer = 0;
  const done = (ok, e) => { clearTimeout(timer); el.removeEventListener(ev, onEv); el.removeEventListener('error', onErr); if (signal) signal.removeEventListener('abort', onAbort); ok ? res() : rej(e); };
  const onEv = () => { if (!ready || ready()) done(true); }, onErr = () => done(false, new Error('video error ' + (el.error ? el.error.code : ''))), onAbort = () => done(false, new Error('aborted'));
  el.addEventListener(ev, onEv); el.addEventListener('error', onErr);
  if (signal) signal.addEventListener('abort', onAbort);
  timer = setTimeout(() => done(false, new Error('timeout ' + ev)), ms);
});
const mkEl = () => { const v = document.createElement('video'); v.muted = true; v.defaultMuted = true; v.playsInline = true; v.preload = 'auto'; v.setAttribute('muted', ''); v.setAttribute('playsinline', ''); return v; };

/* a stored clip → a media asset (throws when this browser cannot show its picture) */
M.videoAsset = async (id, meta, blob) => {
  const url = URL.createObjectURL(blob);
  const el = mkEl();
  try {
    el.src = url;
    await once(el, 'loadedmetadata', 20000);
    if (!el.videoWidth || !(el.duration > 0) || !isFinite(el.duration)) throw new Error('no picture');
    // a frame for the list (and proof that this browser can decode it)
    el.currentTime = Math.min(1, el.duration * 0.3);
    await once(el, 'seeked', 15000);
    const th = document.createElement('canvas'); th.width = 160; th.height = 90;
    const x = th.getContext('2d'), k = Math.max(160 / el.videoWidth, 90 / el.videoHeight);
    x.drawImage(el, (160 - el.videoWidth * k) / 2, (90 - el.videoHeight * k) / 2, el.videoWidth * k, el.videoHeight * k);
    return { id, type: 'video', name: meta.name, w: el.videoWidth, h: el.videoHeight, sw: el.videoWidth, sh: el.videoHeight, duration: el.duration,
      blob, url, el, live: true, lastUse: performance.now(), thumb: th, caps: [] };
  } catch (e) {
    el.removeAttribute('src'); try { el.load(); } catch (e2) {}
    URL.revokeObjectURL(url);
    throw e;
  }
};
M.releaseVideo = a => {
  if (!a || a.type !== 'video') return;
  try { a.el.pause(); a.el.removeAttribute('src'); a.el.load(); } catch (e) {}
  if (a.url) URL.revokeObjectURL(a.url);
  a.live = false; a.caps = []; a.preview = null;
};

/* decoder budget */
function live(a) {
  a.lastUse = performance.now();
  if (a.live) return;
  delete a.el.frameCheckFailedAt;
  a.el.src = a.url; a.live = true;
  try { a.el.load(); } catch (e) {}
}
function trim(keep, limit = MAX_LIVE) {
  const vids = [...J.mediaAssets.values()].filter(a => a.type === 'video' && a.live && !keep.has(a.id)).sort((p, q) => p.lastUse - q.lastUse);
  let n = [...J.mediaAssets.values()].filter(a => a.type === 'video' && a.live).length;
  for (const a of vids) { if (n <= limit) break; try { a.el.pause(); a.el.removeAttribute('src'); a.el.load(); } catch (e) {} a.live = false; n--; }
}
M.liveVideos = () => [...J.mediaAssets.values()].filter(a => a.type === 'video' && a.live).length;

/* the video cuts showing at t (and the one before during a cross-fade) → Map assetId → [{ c, vt }] */
function needed(plan, t) {
  const out = new Map(), next = new Set();
  for (const k of M.TRACKS) {
    const P = plan.media && plan.media[k];
    if (!P || !P.cuts.length) continue;
    const c = M.cutAt(plan, t, k);
    const add = cut => { if (!cut || cut.type !== 'video') return; const vt = M.videoTimes(plan, cut, t); if (!vt) return; if (!out.has(cut.assetId)) out.set(cut.assetId, []); out.get(cut.assetId).push({ c: cut, vt }); };
    if (k === 'front') { for (const x of M.cutsAt(plan, t, k)) add(x); }   // layers: every clip showing
    else add(c);
    if (c && c.index > 0 && c.join && c.join !== 'cut' && t - c.start < c.inDur) add(P.cuts[c.index - 1]);   // the picture it takes over from
    const nx = c ? P.cuts[c.index + 1] : P.cuts.find(x => x.start > t);
    if (nx && nx.type === 'video' && nx.start - t < 2) next.add(nx.assetId);
  }
  return { out, next };
}

/* preview: follow the song with as few seeks as possible */
let sampling = 0;
let exportUntil = 0;                          // an export owns the clips while it runs (the preview must not seek them)
let previewJob = null;
M.cancelPreview = () => { if (previewJob) { previewJob.latest = null; previewJob.controller.abort(); } };
M.syncPreview = (plan, t, playing, redraw) => {
  if (!plan || !plan.media || sampling || performance.now() < exportUntil) return;
  if (previewJob) {
    previewJob.latest = { plan, t, playing, redraw };
    let obsolete = plan !== previewJob.plan || playing !== previewJob.playing || (!playing && t !== previewJob.t);
    if (!obsolete && playing) {
      const current = needed(plan, t).out;
      // Coalesce ordinary progression, but never let a stalled job trail the song by over a second or retain an ended use.
      obsolete = Math.abs(t - previewJob.t) > 1 || previewJob.shared.some(({ a, uses }) => {
        const now = current.get(a.id) || [];
        return now.length !== uses.length || now.some((u, i) => u.c !== uses[i].c || (u.vt.alt != null) !== (uses[i].vt.alt != null));
      });
    }
    if (obsolete) previewJob.controller.abort();
    return;
  }
  for (const a of J.mediaAssets.values()) if (a.type === 'video' && (a.at != null || (a.caps && a.caps.length))) { a.at = null; a.caps = []; }   // export copies are stale now
  const { out, next } = needed(plan, t);
  const shared = [];
  for (const a of J.mediaAssets.values()) if (a.type === 'video') a.previewNeeded = false;
  for (const [id, uses] of out) {
    const a = J.mediaAssets.get(id);
    if (!a || a.type !== 'video') continue;
    live(a);
    // One element cannot show different clip times at once. Keep a picture for each use, with no extra decoder.
    if (new Set(uses.flatMap(({ vt }) => vt.alt == null ? [capKey(vt.main)] : [capKey(vt.main), capKey(vt.alt)])).size > 1) {
      a.previewNeeded = true;
      const key = uses.map(({ c, vt }) => [c.id, capKey(vt.main), vt.alt == null ? null : capKey(vt.alt)].join(':')).join('|');
      if (!a.preview || a.preview.plan !== plan || a.preview.key !== key) shared.push({ a, uses, key });
      continue;
    }
    const { c, vt } = uses[0], el = a.el;
    const target = vt.alt != null && vt.k > 0.5 ? vt.alt : vt.main;
    // can the element simply play forward from here? (not at a seam, not backwards, not held on the last frame)
    const ahead = M.videoTimes(plan, c, t + 0.1);
    const smooth = playing && ahead && Math.abs((ahead.main - vt.main) - 0.1 * c.v.rate) < 0.02;
    if (smooth) {
      const drift = el.currentTime - target;
      if (el.paused || Math.abs(drift) > 0.25) {
        if (!el.seeking && Math.abs(drift) > 0.25) el.currentTime = target;
        el.playbackRate = c.v.rate;
        if (el.paused) { const p = el.play(); if (p && p.catch) p.catch(() => {}); }
      } else el.playbackRate = J.clamp(c.v.rate * (1 - drift * 0.8), 0.25, 4);
    } else {
      if (!el.paused) el.pause();
      if (Math.abs(el.currentTime - target) > 0.02 && !el.seeking && el.readyState >= 1) {
        el.currentTime = target;
        if (redraw) el.addEventListener('seeked', redraw, { once: true });
      }
    }
  }
  for (const a of J.mediaAssets.values()) if (a.type === 'video' && !out.has(a.id) && a.el && !a.el.paused) a.el.pause();
  for (const id of next) { const a = J.mediaAssets.get(id); if (a && a.type === 'video' && !a.live && M.liveVideos() < MAX_LIVE) live(a); }
  trim(new Set([...out.keys(), ...next]));
  if (shared.length) queuePreview(plan, t, playing, shared, redraw);
};
M.pauseVideos = () => { for (const a of J.mediaAssets.values()) if (a.type === 'video' && a.el && !a.el.paused) a.el.pause(); };

/* the frame the element shows now ({ ts, dur } in s), or null when this browser cannot tell (no WebCodecs, no frame yet) */
function shown(el) {
  if (typeof VideoFrame !== 'function' || el.readyState < 2) return null;
  try { const f = new VideoFrame(el), r = { ts: f.timestamp / 1e6, dur: (f.duration || 0) / 1e6 }; f.close(); return r; } catch (e) { return null; }
}
/* export: every clip needed for the frame at t is at its exact time before the frame is drawn */
async function seekExact(el, time, signal) {
  if (el.readyState < 1) await once(el, 'loadedmetadata', 20000, signal);
  if (signal && signal.aborted) throw new Error('aborted');
  if (el.frameCheckFailedAt != null) {
    const frame = shown(el);
    if (!frame || Math.abs(frame.ts - el.frameCheckFailedAt) < 1e-6) throw new Error('video presentation is still stalled');
    delete el.frameCheckFailedAt; // presentation advanced since the timeout: exact reads can be tried again
  }
  const tt = J.clamp(time, 0, Math.max(0, el.duration - 1 / 240));
  if (!el.paused) el.pause();
  if (Math.abs(el.currentTime - tt) < 1e-4 && el.readyState >= 2 && !el.seeking) return;
  const before = shown(el), jump = Math.abs(tt - el.currentTime);
  // A seeked event from a previous seek may already be queued. Only the completed requested seek is readable: setting
  // currentTime turns seeking on at once, so !seeking tells. Some browsers report the time on the clip's own time grid
  // (e.g. 1/600 s), so the time itself is only compared loosely.
  const settled = once(el, 'seeked', 15000, signal, () => !el.seeking && el.readyState >= 2 && Math.abs(el.currentTime - tt) < 0.01);
  el.currentTime = tt;
  await settled;
  // 'seeked' can precede presentation. Even a short seek across the shown frame's timestamp interval needs a new frame.
  // Without its duration, retain the conservative long-jump check. Slow decoding gets the normal seek timeout.
  if (!before) return;
  if (before.dur > 0 ? tt >= before.ts && tt < before.ts + before.dur : jump <= 0.5) return;
  const deadline = performance.now() + 15000;
  while (performance.now() < deadline) {
    const now = shown(el);
    if (!now || Math.abs(now.ts - before.ts) > 1e-6) return;
    await new Promise(r => setTimeout(r, 4));
    if (signal && signal.aborted) throw new Error('aborted');
  }
  el.frameCheckFailedAt = before.ts;
  throw new Error('timeout presenting video frame at ' + tt);
}
const capKey = time => Math.round(time * 1000);
function warnSeek(a, error) {
  const stalled = a.el.frameCheckFailedAt;
  if (stalled == null || a.reportedFrameTimeout !== stalled) console.warn('media: clip seek failed', a.name, error);
  a.reportedFrameTimeout = stalled;
}
// A shared decoder cannot seek for two frame preparations at once (export, or a user sample).
let frameQueue = Promise.resolve();
// Double-buffer the copied pictures: a seek must not change a frame the renderer is still using.
function queuePreview(plan, t, playing, shared, redraw) {
  const job = previewJob = { plan, t, playing, shared, latest: null, controller: new AbortController() };
  const signal = job.controller.signal;
  const prepared = frameQueue.then(async () => {
    if (signal.aborted || sampling || performance.now() < exportUntil) return;
    for (const { a, uses, key } of shared) {
      if (J.mediaAssets.get(a.id) !== a) continue;
      const bank = a.preview && a.preview.bank === 0 ? 1 : 0;
      const banks = a.previewPools || (a.previewPools = [[], []]), pool = banks[bank], copies = new Map();
      try {
        for (const { vt } of uses) for (const time of [vt.main, vt.alt]) {
          if (time == null || copies.has(capKey(time))) continue;
          await seekExact(a.el, time, signal);
          const i = copies.size, cv = pool[i] || (pool[i] = document.createElement('canvas'));
          const k = Math.min(1, 1920 / Math.max(a.sw, a.sh)), w = Math.round(a.sw * k), h = Math.round(a.sh * k);
          if (cv.width !== w || cv.height !== h) { cv.width = w; cv.height = h; }
          cv.getContext('2d').drawImage(a.el, 0, 0, w, h);
          copies.set(capKey(time), cv);
        }
        if (signal.aborted) return;
        if (J.mediaAssets.get(a.id) !== a) continue;
        const frames = new Map(uses.map(({ c, vt }) => [c, { main: copies.get(capKey(vt.main)), alt: vt.alt == null ? null : copies.get(capKey(vt.alt)) }]));
        a.preview = { plan, key, bank, frames };
      } catch (e) { if (signal.aborted) return; warnSeek(a, e); }
    }
  });
  frameQueue = prepared.catch(() => {});
  frameQueue.finally(() => {
    previewJob = null;
    if (job.latest) { const r = job.latest; M.syncPreview(r.plan, r.t, r.playing, r.redraw); }
    if (redraw) redraw();
  });
}
M.prepareFrame = (plan, t, signal, sampleCut) => {
  M.cancelPreview(); // explicit sampling/export takes precedence over an obsolete preview request
  const prepared = frameQueue.then(() => prepareFrame(plan, t, signal, sampleCut));
  frameQueue = prepared.catch(() => {});
  return prepared;
};
// Preserve a direct promise so the caller reads its capture before the next queued preparation starts.
M.prepareCut = (plan, c, t, signal) => plan && c && c.type === 'video'
  ? M.prepareFrame(plan, t, signal, c) : Promise.resolve(null);
M.releaseVideos = () => { exportUntil = 0; };
// sampleCut prepares the selected cut even outside its interval, without the export cooldown.
async function prepareFrame(plan, t, signal, sampleCut) {
  if (!plan || !plan.media) return;
  if (signal && signal.aborted) throw new Error('aborted');
  if (sampleCut) sampling++; else exportUntil = performance.now() + 2000;
  try {
    M.pauseVideos();
    const vt = sampleCut && M.videoTimes(plan, sampleCut, t);
    const out = sampleCut ? new Map(vt ? [[sampleCut.assetId, [{ c: sampleCut, vt }]]] : []) : needed(plan, t).out;
    for (const a of J.mediaAssets.values()) if (a.type === 'video') { a.caps = []; a.at = null; }
    for (const [id, uses] of out) {
      const a = J.mediaAssets.get(id);
      if (!a || a.type !== 'video') continue;
      if (sampleCut && !a.live) trim(new Set([id]), MAX_LIVE - 1); // borrow a slot before reopening an inactive cut
      live(a);
      const times = [];
      for (const { vt } of uses) { times.push(vt.main); if (vt.alt != null) times.push(vt.alt); }
      const uniq = [...new Set(times.map(capKey))].map(k => k / 1000);
      try {
        // all but the last time are copied out; the element itself stays on the last one
        for (let i = 0; i < uniq.length; i++) {
          await seekExact(a.el, uniq[i], signal);
          if (i < uniq.length - 1) {
            const pool = a.pool || (a.pool = []);
            const cv = pool[i] || (pool[i] = document.createElement('canvas'));
            const k = Math.min(1, 1920 / Math.max(a.sw, a.sh));
            cv.width = Math.round(a.sw * k); cv.height = Math.round(a.sh * k);
            cv.getContext('2d').drawImage(a.el, 0, 0, cv.width, cv.height);
            a.caps.push({ key: capKey(uniq[i]), cv });
          }
        }
        a.at = capKey(uniq[uniq.length - 1]);
      } catch (e) {
        a.caps = []; a.at = null; // do not label partial or stale pictures as the requested export/sample frame
        if (signal && signal.aborted) throw e;
        warnSeek(a, e);
      }
    }
    trim(new Set(out.keys()));
    return sampleCut ? vt : undefined;
  } finally {
    if (sampleCut) sampling--; else exportUntil = performance.now() + 2000;
  }
}

/* an exact copy made for this export frame, or null */
M.videoCap = (a, time) => {
  const k = capKey(time);
  for (const c of a.caps || []) if (c.key === k) return c.cv;
  return a.at === k && a.live && a.el.readyState >= 2 ? a.el : null;      // the time the element itself was left on
};
/* what to draw for a clip at clip time `time`: an exact copy, the element, or null (nothing decoded yet) */
M.videoFrame = (a, time, cut, alt = false) => {
  if (sampling || performance.now() < exportUntil) return M.videoCap(a, time);
  if (a.previewNeeded) {
    const frame = a.preview && a.preview.frames.get(cut);
    return frame ? (alt ? frame.alt : frame.main) : null;
  }
  if (alt) return M.videoCap(a, time);
  const k = capKey(time);
  for (const c of a.caps || []) if (c.key === k) return c.cv;
  if (!a.live || a.el.readyState < 2) return null;
  return a.el;
};
})();
