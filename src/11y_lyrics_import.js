/* ============================================================
   my-jizura (fork) — lyric timing import (Phase 1.5)
   Turns timed lyrics from other tools into LRC text, which the existing 「LRC を読み込む」 path then loads
   (same undo, same rules for lines without a time):
     · LRC (also "enhanced" LRC: inline <mm:ss.xx> word tags are dropped)
     · SRT and WebVTT subtitles (one cue = one line; extra text lines of a cue follow without a time)
     · JSON: Whisper / faster-whisper (segments[].start/end/text), word lists (Suno aligned words
       { word, start_s }, WhisperX / whisper words { word, start }), or simple [{ start|time, text }]
   Section headers such as [Verse] [Chorus] become a blank line (a new part); [Instrumental] / [間奏] stay.
   12_ui.js calls J.lyricsImport.toLrc(text, fileName) in the 「LRC を読み込む」 handler.
   Word times (word lists, enhanced LRC) are kept too: toLrc(...).words = [{ text, start, w: [[seconds, offset], …], p }] —
   one entry per lyric line, offset = where the word starts in the line counted as J.media.normText counts (no spaces / marks),
   p = the lowest alignment confidence of its words (Suno p_align, Whisper probability) when the source has one.
   They let the cuts inside a line change when the word is sung (08m_media_text.js).
   ============================================================ */
(() => {
'use strict';
const LI = (J.lyricsImport = {});

const stamp = t => { t = Math.max(0, +t || 0); const m = Math.floor(t / 60), s = t - m * 60; return `[${String(m).padStart(2, '0')}:${s.toFixed(2).padStart(5, '0')}]`; };
const INTERLUDE = /^\[\s*(?:間奏|间奏|interlude|instrumental|inst|간주)(?![A-Za-z])[^\]]*\]$/i;   // (no \b: it does not work after kana / kanji)
const TIME_TAG = /^\[\d+:\d+(?:[.:]\d+)?\]/;
const META = /^\[(ti|ar|al|by|offset|length|re|ve|au):/i;
// a bracketed line that is not a time, meta or interlude tag: a section header ([Verse 1], [Chorus], [サビ] …)
const isSection = s => /^\[[^\]]{1,40}\]$/.test(s) && !TIME_TAG.test(s) && !META.test(s) && !INTERLUDE.test(s);
const clean = s => String(s == null ? '' : s).replace(/<[^>]*>/g, '').replace(/\{\\[^}]*\}/g, '').replace(/[ \t　]+/g, ' ').trim();
// how far into a line a word starts: the same count as J.media.normText (no spaces, no / * marks)
const normLen = s => [...clean(s).replace(/[\s/*]/g, '')].length;

// the interlude tags JIZURA itself reads (same pattern as 08_planner.js); others ([Instrumental Break], [Inst. solo]) become [間奏]
const STRICT = /^\[\s*(間奏|间奏|interlude|instrumental|inst|간주)(?:\s*[:：]?\s*(\d+(?:\.\d+)?)\s*(?:s|sec|秒|초)?)?\s*\]$/i;
/* one lyric row: a section header → '' (a blank line = a new part), an interlude tag JIZURA does not read → [間奏], else as it is */
const row = (prefix, body) => (isSection(body) ? '' : prefix + (INTERLUDE.test(body) && !STRICT.test(body) ? '[間奏]' : body));

/* LRC text: drop inline word tags (kept as word times) and section headers (→ blank line) */
const tagTime = m => +m[1] * 60 + parseFloat(String(m[2]).replace(':', '.'));
function fromLrc(text, words) {
  const out = [];
  for (const line of text.split('\n')) {
    // enhanced LRC: [00:12.00]<00:12.00>夜明けの<00:13.10>色を — each <time> starts the word after it
    const body0 = line.replace(/^(\[\d+:\d+(?:[.:]\d+)?\])+/, '');
    if (words && /<\d+:\d+(?:[.:]\d+)?>/.test(body0)) {
      const w = []; let acc = '';
      for (const part of body0.split(/(<\d+:\d+(?:[.:]\d+)?>)/)) {
        const m = part.match(/^<(\d+):(\d+(?:[.:]\d+)?)>$/);
        if (m) { w.push([tagTime(m), normLen(acc)]); continue; }
        acc += part;
      }
      const txt = clean(acc), first = line.match(/^\[(\d+):(\d+(?:[.:]\d+)?)\]/);
      if (txt && w.length) words.push({ text: txt, start: first ? tagTime(first) : w[0][0], w: w.filter(x => x[1] < normLen(txt) || x[1] === 0) });
    }
    const s = line.replace(/<\d+:\d+(?:[.:]\d+)?>/g, '').replace(/[ \t]+$/, '');
    const prefix = (s.match(/^(\[\d+:\d+(?:[.:]\d+)?\])+/) || [''])[0], body = s.slice(prefix.length).trim();
    if (prefix && !body) continue;                          // a time with no words (end markers of some players)
    out.push(body ? row(prefix, body) : s);
  }
  return out.join('\n');
}

/* SRT / WebVTT */
const cueTime = s => { const m = String(s).trim().match(/^(?:(\d+):)?(\d{1,2}):(\d{1,2})[.,](\d{1,3})/); return m ? (+(m[1] || 0)) * 3600 + +m[2] * 60 + +m[3] + +('0.' + m[4]) : null; };
function fromCues(text) {
  const out = [];
  const blocks = text.replace(/^WEBVTT[^\n]*\n/, '').split(/\n\s*\n/);
  for (const b of blocks) {
    const rows = b.split('\n').map(r => r.trim()).filter(Boolean);
    const ti = rows.findIndex(r => r.includes('-->'));
    if (ti < 0) continue;                                    // NOTE / STYLE / REGION blocks, headers
    const t = cueTime(rows[ti].split('-->')[0]);
    if (t == null) continue;
    const lines = rows.slice(ti + 1).map(clean).filter(Boolean);
    lines.forEach((l, k) => out.push(row(k === 0 ? stamp(t) : '', l)));
  }
  return out.join('\n');
}

/* words with times → lines: a new line at a newline inside a word, after a pause of 0.9 s,
   or after a sentence end (。！？.!?) followed by a pause of 0.3 s; section headers become a blank line */
const SECTION_IN = /\[[^\]]*\]/g;
function fromWords(words, keep) {
  const out = [];
  let cur = '', t0 = null, lastEnd = null, sentenceEnd = false, ws = [], pmin = null;
  const flush = () => {
    const s = clean(cur);
    if (s) { out.push(stamp(t0) + s); if (keep && ws.length) keep.push({ text: s, start: t0, w: ws, p: pmin }); }
    cur = ''; t0 = null; sentenceEnd = false; ws = []; pmin = null;
  };
  const blank = () => { flush(); if (out.length && out[out.length - 1] !== '') out.push(''); };
  for (const w of words) {
    const raw = String(w.text == null ? '' : w.text), st = w.start, en = w.end != null ? w.end : st;
    if (st == null) continue;
    if (cur && lastEnd != null && (st - lastEnd > 0.9 || (sentenceEnd && st - lastEnd > 0.3))) flush();
    raw.split('\n').forEach((part, k) => {
      if (k > 0) flush();
      const tags = part.match(SECTION_IN) || [];
      let p = part;
      for (const tag of tags) { if (INTERLUDE.test(tag)) { flush(); out.push(stamp(st) + '[間奏]'); } else blank(); p = p.replace(tag, ''); }
      if (!p.trim()) return;
      if (t0 == null) t0 = st;
      ws.push([st, normLen(cur)]);                           // this word starts here in the line
      if (w.p != null) pmin = pmin == null ? w.p : Math.min(pmin, w.p);
      cur += p;
    });
    lastEnd = en;
    sentenceEnd = /[。！？!?]\s*$/.test(raw) || /[A-Za-z]{2,}[.]\s*$/.test(raw);
  }
  flush();
  while (out.length && out[out.length - 1] === '') out.pop();
  return out.join('\n');
}
const num = v => (v == null || v === '' || !isFinite(+v) ? null : +v);
const wordOf = w => ({ text: w.word != null ? w.word : w.text != null ? w.text : w.punctuated_word, start: num(w.start_s != null ? w.start_s : w.start != null ? w.start : w.startTime != null ? w.startTime : w.start_time), end: num(w.end_s != null ? w.end_s : w.end != null ? w.end : w.endTime != null ? w.endTime : w.end_time),
  p: num(w.p_align != null ? w.p_align : w.probability != null ? w.probability : w.confidence != null ? w.confidence : w.score) });

function fromJson(data, keep) {
  if (Array.isArray(data) && data.length && typeof data[0] === 'object') {
    if (data.some(x => x && (x.word != null || x.start_s != null))) return { text: fromWords(data.map(wordOf), keep), kind: 'words' };
    if (data.some(x => x && x.text != null && (x.start != null || x.time != null || x.startTime != null))) return { text: lineList(data), kind: 'lines' };
  }
  if (data && typeof data === 'object') {
    if (Array.isArray(data.aligned_words)) return { text: fromWords(data.aligned_words.map(wordOf), keep), kind: 'words' };
    if (Array.isArray(data.segments) && data.segments.length) {
      if (data.segments.some(s => s && s.text != null && s.text.trim())) return { text: lineList(data.segments), kind: 'segments' };
      const ws = [].concat(...data.segments.map(s => (s && Array.isArray(s.words) ? s.words : [])));
      if (ws.length) return { text: fromWords(ws.map(wordOf), keep), kind: 'words' };
    }
    if (Array.isArray(data.words)) return { text: fromWords(data.words.map(wordOf), keep), kind: 'words' };
    if (Array.isArray(data.lines)) return { text: lineList(data.lines), kind: 'lines' };
    for (const k of ['data', 'result', 'results', 'lyrics']) if (data[k] && typeof data[k] === 'object') { const r = fromJson(data[k], keep); if (r) return r; }
  }
  return null;
}
function lineList(items) {
  const out = [];
  for (const it of items) {
    if (!it) continue;
    const t = num(it.start != null ? it.start : it.time != null ? it.time : it.startTime != null ? it.startTime : it.start_s);
    const rows = String(it.text == null ? '' : it.text).split('\n').map(clean).filter(Boolean);
    rows.forEach((l, k) => out.push(row(k === 0 && t != null ? stamp(t) : '', l)));
  }
  return out.join('\n');
}

/* text of a dropped / chosen file → { text: LRC-style lyrics, kind } (unknown text is returned as it is) */
LI.toLrc = (text, name = '') => {
  const src = String(text || '').replace(/^﻿/, '').replace(/\r\n?/g, '\n');
  const ext = (String(name).match(/\.([a-z0-9]+)$/i) || [])[1] || '';
  const head = src.trimStart();
  const words = [];
  let r = null;
  try {
    if (/^json$/i.test(ext) || /^[[{]/.test(head)) {
      r = fromJson(JSON.parse(head), words);
      if (!(r && r.text.trim())) r = null;
    }
  } catch (e) { r = null; }
  if (!r && (/^vtt$/i.test(ext) || /^WEBVTT/.test(head))) r = { text: fromCues(src), kind: 'vtt' };
  else if (!r && (/^srt$/i.test(ext) || /^\d+\s*\n\s*\d{1,2}:\d{2}:\d{2}[,.]\d{1,3}\s*-->/.test(head))) r = { text: fromCues(src), kind: 'srt' };
  else if (!r) { words.length = 0; r = { text: fromLrc(src, words), kind: 'lrc' }; }
  r.words = words.filter(x => x.w.length);
  LI.last = { text: r.text.trim(), words: r.words };      // the 「LRC を読み込む」 path keeps them once the text is loaded (11z_media_ui.js)
  return r;
};

/* the file input accepts the new formats too (app/body.html stays as upstream ships it) */
if (typeof document !== 'undefined') {
  const inp = document.getElementById('fileLrc');
  if (inp) {
    inp.accept = '.lrc,.txt,.srt,.vtt,.json,text/plain,application/json';
    const lab = inp.closest('label'), ja = /^ja/.test(document.documentElement.lang || 'ja');
    if (lab) lab.title = ja ? 'タイムスタンプ付きの歌詞を読み込み、今の歌詞と置き換えます。LRC のほか、SRT・VTT 字幕、Whisper や Suno の JSON（単語ごとの時刻）も読めます（「元に戻す」で戻せます）'
      : 'Load timed lyrics and replace the current lyrics: LRC, SRT / VTT subtitles, or Whisper / Suno JSON with word times (undo brings the old ones back)';
  }
}
})();
