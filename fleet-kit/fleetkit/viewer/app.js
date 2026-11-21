(function () {
"use strict";
const M = JSON.parse(document.getElementById("data").textContent);
const $ = (id) => document.getElementById(id);
const W = M.world, TM = M.time, link = M.link, plan = M.plan;
const hasPlan = !!plan;
const acById = {}; M.aircraft.forEach((a) => { acById[a.id] = a; });
const coById = {}; W.contacts.forEach((c) => { coById[c.id] = c; });
const N = hasPlan ? M.tracks[M.aircraft[0].id].p.length : 1;
const state = { t: 0, playing: false, speed: 8, sel: null, hover: null, labels: true, trails: "all", dark: false,
  show: { zones: true, protect: true, ranges: false, homes: true, routes: true, links: true, marks: true }, layers: {} };
(M.layers || []).forEach((l, i) => { state.layers[i] = l.visible !== false; });
let view = { cx: 0, cy: 0, k: 1 };
let dirty = true;
const css = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();

// ---------- data access ----------
function fidx(t) { return Math.min(Math.max(t / TM.dt, 0), N - 1); }
function posAt(id, t) {
  const tr = M.tracks[id]; if (!tr) return null;
  const f = fidx(t), i = Math.floor(f), j = Math.min(i + 1, N - 1), a = tr.p[i], b = tr.p[j];
  if (!a && !b) return null; if (!a) return b; if (!b) return a;
  const u = f - i; return [a[0] + (b[0] - a[0]) * u, a[1] + (b[1] - a[1]) * u, a[2] + (b[2] - a[2]) * u];
}
const statusAt = (id, t) => (M.tracks[id] ? M.tracks[id].s[Math.min(Math.floor(fidx(t)), N - 1)] : "g");
const energyAt = (id, t) => (M.tracks[id] ? M.tracks[id].e[Math.min(Math.floor(fidx(t)), N - 1)] : 0);
const STATUS = { g: "on the ground", f: "flying", o: "observing", x: "engaged (consumed)", l: "landed", h: "holding", r: "returning", L: "lost (battery)", F: "failed" };
const typeKey = (a) => (a.type === "scout" ? "scout" : a.sub === "heavy" ? "heavy" : "light");
const typeLabel = (a) => (a.type === "scout" ? "scout" : a.sub + " effector");
const reclassAt = (cid, t) => !!(link && link.events.some((e) => e.kind === "reclassify" && e.contact === cid && e.t <= t));

// ---------- canvas plumbing ----------
function fitCanvas(cv) {
  const r = cv.getBoundingClientRect(), dpr = window.devicePixelRatio || 1;
  const w = Math.max(1, Math.round(r.width * dpr)), h = Math.max(1, Math.round(r.height * dpr));
  if (cv.width !== w || cv.height !== h) { cv.width = w; cv.height = h; }
  const ctx = cv.getContext("2d"); ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  return { ctx, w: r.width, h: r.height };
}
function fitView() {
  const b = W.bounds, cv = $("map").getBoundingClientRect();
  const bw = Math.max(b[1] - b[0], 200), bh = Math.max(b[3] - b[2], 200);
  view.k = Math.min(cv.width / (bw * 1.16), cv.height / (bh * 1.16));
  view.cx = (b[0] + b[1]) / 2; view.cy = (b[2] + b[3]) / 2; dirty = true;
}
const sx = (x, w) => (x - view.cx) * view.k + w / 2;
const sy = (y, h) => h / 2 - (y - view.cy) * view.k;

// ---------- shapes ----------
function shape(ctx, kind, x, y, r) {
  ctx.beginPath();
  if (kind === "diamond") { ctx.moveTo(x, y - r); ctx.lineTo(x + r, y); ctx.lineTo(x, y + r); ctx.lineTo(x - r, y); ctx.closePath(); }
  else if (kind === "square") ctx.rect(x - r * 0.85, y - r * 0.85, r * 1.7, r * 1.7);
  else ctx.arc(x, y, r, 0, Math.PI * 2);
}
function chevron(ctx, x, y, r, ang) {
  ctx.save(); ctx.translate(x, y); ctx.rotate(ang);
  ctx.beginPath(); ctx.moveTo(r * 1.15, 0); ctx.lineTo(-r * 0.8, r * 0.8); ctx.lineTo(-r * 0.35, 0); ctx.lineTo(-r * 0.8, -r * 0.8); ctx.closePath();
  ctx.restore();
}
function hatch() {
  const c = document.createElement("canvas"); c.width = c.height = 8; const g = c.getContext("2d");
  g.strokeStyle = css("--zone"); g.globalAlpha = 0.5; g.lineWidth = 1.2; g.beginPath(); g.moveTo(-2, 10); g.lineTo(10, -2); g.moveTo(-2, 6); g.lineTo(6, -2); g.moveTo(2, 10); g.lineTo(10, 2); g.stroke();
  return c;
}

// ---------- map ----------
function niceStep(span) { const raw = span / 6, p = Math.pow(10, Math.floor(Math.log10(raw))); const m = raw / p; return (m < 1.5 ? 1 : m < 3.5 ? 2 : m < 7.5 ? 5 : 10) * p; }
function drawMap() {
  const { ctx, w, h } = fitCanvas($("map"));
  ctx.clearRect(0, 0, w, h);
  const t = state.t;
  // grid
  const step = niceStep(w / view.k), x0 = view.cx - w / 2 / view.k, x1 = view.cx + w / 2 / view.k, y0 = view.cy - h / 2 / view.k, y1 = view.cy + h / 2 / view.k;
  ctx.lineWidth = 1; ctx.strokeStyle = css("--grid"); ctx.fillStyle = css("--muted"); ctx.font = "10.5px 'Space Grotesk', system-ui, sans-serif"; ctx.beginPath();
  for (let x = Math.ceil(x0 / step) * step; x < x1; x += step) { const X = Math.round(sx(x, w)) + 0.5; ctx.moveTo(X, 0); ctx.lineTo(X, h); }
  for (let y = Math.ceil(y0 / step) * step; y < y1; y += step) { const Y = Math.round(sy(y, h)) + 0.5; ctx.moveTo(0, Y); ctx.lineTo(w, Y); }
  ctx.stroke();
  for (let x = Math.ceil(x0 / step) * step; x < x1; x += step) ctx.fillText(Math.round(x) + " m", sx(x, w) + 3, h - 5);
  for (let y = Math.ceil(y0 / step) * step; y < y1; y += step) ctx.fillText(Math.round(y) + " m", 4, sy(y, h) - 3);
  const R = W.rules;
  // zones
  const pat = ctx.createPattern(hatch(), "repeat");
  const zones = W.zones.map((z) => ({ ...z, t0: 0 }));
  if (link) link.events.filter((e) => e.kind === "popup_zone").forEach((e, i) => zones.push({ id: "NEW" + (i + 1), x: e.center[0], y: e.center[1], r: e.radius_m, top: e.top_m, t0: e.t, fresh: true }));
  if (state.show.zones) zones.forEach((z) => {
    if (z.t0 > t) return;
    const X = sx(z.x, w), Y = sy(z.y, h), r = z.r * view.k;
    ctx.beginPath(); ctx.arc(X, Y, r, 0, 6.2832); ctx.fillStyle = pat; ctx.fill();
    ctx.strokeStyle = css("--zone"); ctx.lineWidth = z.fresh ? 2.5 : 1.5; ctx.setLineDash(z.fresh ? [] : [5, 3]); ctx.stroke(); ctx.setLineDash([]);
    if (z.fresh && t - z.t0 < 6) { ctx.beginPath(); ctx.arc(X, Y, r + (t - z.t0) * 8, 0, 6.2832); ctx.globalAlpha = 0.5 * (1 - (t - z.t0) / 6); ctx.stroke(); ctx.globalAlpha = 1; }
    ctx.fillStyle = css("--zone"); ctx.font = "600 11px 'Space Grotesk', system-ui, sans-serif"; ctx.fillText(z.id + " · up to " + Math.round(z.top) + " m", X - r * 0.6, Y - r - 5);
  });
  // protected areas and ranges
  W.contacts.forEach((c) => {
    const X = sx(c.x, w), Y = sy(c.y, h), cls = reclassAt(c.id, t) ? "friendly" : c.cls;
    if (state.show.protect && (cls === "friendly" || cls === "civilian")) {
      ctx.beginPath(); ctx.arc(X, Y, R.protect * view.k, 0, 6.2832); ctx.strokeStyle = css("--" + cls); ctx.globalAlpha = 0.55; ctx.setLineDash([3, 3]); ctx.lineWidth = 1.2; ctx.stroke(); ctx.setLineDash([]); ctx.globalAlpha = 1;
      if (state.show.ranges) { ctx.beginPath(); ctx.arc(X, Y, R.collateral * view.k, 0, 6.2832); ctx.globalAlpha = 0.3; ctx.stroke(); ctx.globalAlpha = 1; }
    }
    if (state.show.ranges && (c.cls === "hostile" || c.cls === "unknown")) {
      ctx.beginPath(); ctx.arc(X, Y, R.R_obs * view.k, 0, 6.2832); ctx.strokeStyle = css("--" + c.cls); ctx.globalAlpha = 0.35; ctx.setLineDash([2, 4]); ctx.lineWidth = 1; ctx.stroke(); ctx.setLineDash([]); ctx.globalAlpha = 1;
    }
  });
  // homes
  if (state.show.homes) M.aircraft.forEach((a) => { const X = sx(a.home[0], w), Y = sy(a.home[1], h); ctx.strokeStyle = css("--muted"); ctx.globalAlpha = 0.5; ctx.lineWidth = 1; ctx.strokeRect(X - 3, Y - 3, 6, 6); ctx.globalAlpha = 1; });
  // user layers
  (M.layers || []).forEach((l, i) => { if (state.layers[i]) drawLayer(ctx, w, h, l, t); });
  // routes and trails
  if (hasPlan && state.show.routes) M.aircraft.forEach((a) => {
    const tr = M.tracks[a.id]; if (!tr) return;
    const isSel = state.sel === a.id;
    if (state.trails === "none" && !isSel) return;
    if (state.trails === "selected" && !isSel && state.hover !== a.id) return;
    const col = css("--" + typeKey(a));
    const full = isSel;
    const from = full ? 0 : Math.max(0, Math.floor(fidx(t - 60)));
    const to = Math.floor(fidx(t));
    ctx.beginPath(); let started = false;
    for (let i = from; i <= to; i++) { const p = tr.p[i]; if (!p) continue; const X = sx(p[0], w), Y = sy(p[1], h); if (!started) { ctx.moveTo(X, Y); started = true; } else ctx.lineTo(X, Y); }
    const cur = posAt(a.id, t); if (cur && started) ctx.lineTo(sx(cur[0], w), sy(cur[1], h));
    ctx.strokeStyle = col; ctx.lineWidth = isSel ? 2 : 1.2; ctx.globalAlpha = isSel ? 0.9 : 0.45; ctx.stroke(); ctx.globalAlpha = 1;
    if (isSel) { // the part still to fly, faint
      ctx.beginPath(); let s2 = false;
      for (let i = to + 1; i < N; i++) { const p = tr.p[i]; if (!p) continue; const X = sx(p[0], w), Y = sy(p[1], h); if (!s2) { if (cur) ctx.moveTo(sx(cur[0], w), sy(cur[1], h)); else ctx.moveTo(X, Y); s2 = true; } ctx.lineTo(X, Y); }
      ctx.setLineDash([4, 4]); ctx.globalAlpha = 0.45; ctx.lineWidth = 1.5; ctx.stroke(); ctx.setLineDash([]); ctx.globalAlpha = 1;
    }
  });
  // contacts
  W.contacts.forEach((c) => {
    const X = sx(c.x, w), Y = sy(c.y, h), re = reclassAt(c.id, t), cls = re ? "friendly" : c.cls, col = css("--" + cls);
    const kind = cls === "hostile" ? "diamond" : cls === "friendly" ? "square" : "circle";
    shape(ctx, kind, X, Y, cls === "hostile" ? 8 : 6.5);
    ctx.fillStyle = cls === "unknown" ? "transparent" : col; ctx.globalAlpha = 0.9; ctx.fill(); ctx.globalAlpha = 1;
    ctx.strokeStyle = col; ctx.lineWidth = 2; ctx.stroke();
    if (cls === "unknown") { ctx.fillStyle = col; ctx.font = "700 10px 'Space Grotesk', system-ui, sans-serif"; ctx.textAlign = "center"; ctx.fillText("?", X, Y + 3.5); ctx.textAlign = "left"; }
    if (re) { ctx.strokeStyle = css("--bad"); ctx.lineWidth = 1.5; ctx.beginPath(); ctx.arc(X, Y, 12, 0, 6.2832); ctx.stroke(); }
    const sv = M.served[c.id];
    if (sv !== undefined && sv <= t) { ctx.strokeStyle = css("--ok"); ctx.lineWidth = 2; ctx.beginPath(); ctx.arc(X, Y, 12.5, 0, 6.2832); ctx.stroke(); }
    if (state.labels && view.k * 400 > 40) { ctx.fillStyle = css("--text"); ctx.font = "11px 'Space Grotesk', system-ui, sans-serif"; ctx.fillText(c.id + (c.points ? " · " + c.points : "") + (re ? " (reclassified)" : ""), X + 11, Y + 4); }
  });
  // marks: observation beams, engagement flashes
  if (state.show.marks) M.marks.forEach((m) => {
    const c = coById[m.contact]; if (!c) return;
    const X = sx(c.x, w), Y = sy(c.y, h);
    if (m.kind === "observe" && t >= m.t0 && t <= m.t1) {
      const p = posAt(m.aid, t); if (p) { ctx.beginPath(); ctx.moveTo(sx(p[0], w), sy(p[1], h)); ctx.lineTo(X, Y); ctx.strokeStyle = css("--scout"); ctx.setLineDash([2, 3]); ctx.lineWidth = 1.5; ctx.stroke(); ctx.setLineDash([]); }
    }
    if (m.kind === "engage" && t >= m.t && t - m.t < 4) {
      const u = (t - m.t) / 4; ctx.beginPath(); ctx.arc(X, Y, 8 + u * 26, 0, 6.2832); ctx.strokeStyle = css("--hostile"); ctx.globalAlpha = 1 - u; ctx.lineWidth = 3; ctx.stroke(); ctx.globalAlpha = 1;
    }
  });
  // message links
  if (link && state.show.links && t >= link.t_loss) {
    const sec = Math.floor(t);
    (linkBySec[sec] || []).forEach((l) => {
      const a = posAt(l[1], t), b = posAt(l[2], t); if (!a || !b) return;
      ctx.beginPath(); ctx.moveTo(sx(a[0], w), sy(a[1], h)); ctx.lineTo(sx(b[0], w), sy(b[1], h));
      ctx.strokeStyle = l[3] ? css("--ok") : css("--muted"); ctx.globalAlpha = l[3] ? 0.5 : 0.35; ctx.lineWidth = l[3] ? 1.2 : 1; ctx.setLineDash(l[3] ? [] : [2, 4]); ctx.stroke(); ctx.setLineDash([]); ctx.globalAlpha = 1;
    });
  }
  // violations
  if (hasPlan) plan.violations.forEach((v) => {
    if (v.t === null || v.t === undefined || Math.abs(t - v.t) > 4) return;
    const ids = v.pair || (v.aircraft ? [v.aircraft] : []);
    const ps = ids.map((id) => posAt(id, v.t)).filter(Boolean);
    const u = Math.abs(t - v.t) / 4;
    ps.forEach((p) => { ctx.beginPath(); ctx.arc(sx(p[0], w), sy(p[1], h), 14 + u * 6, 0, 6.2832); ctx.strokeStyle = css("--bad"); ctx.lineWidth = 2.5; ctx.globalAlpha = 1 - u; ctx.stroke(); ctx.globalAlpha = 1; });
    if (ps.length === 2) { ctx.beginPath(); ctx.moveTo(sx(ps[0][0], w), sy(ps[0][1], h)); ctx.lineTo(sx(ps[1][0], w), sy(ps[1][1], h)); ctx.strokeStyle = css("--bad"); ctx.lineWidth = 2; ctx.stroke(); }
  });
  // aircraft
  M.aircraft.forEach((a) => {
    const st = statusAt(a.id, t), p = posAt(a.id, t); if (!p || st === "x") return;
    if (!hasPlan) return;
    const X = sx(p[0], w), Y = sy(p[1], h), col = css("--" + typeKey(a));
    const q = posAt(a.id, t + 1.5), q0 = posAt(a.id, t - 1.5);
    let ang = -Math.PI / 2;
    if (q && q0 && (Math.abs(q[0] - q0[0]) + Math.abs(q[1] - q0[1])) > 0.5) ang = Math.atan2(-(q[1] - q0[1]), q[0] - q0[0]);
    const size = a.type === "scout" ? 7 : a.sub === "heavy" ? 8.5 : 6.5;
    if (st === "g" || st === "l") { ctx.globalAlpha = 0.55; }
    chevron(ctx, X, Y, size, ang); ctx.fillStyle = col; ctx.fill(); ctx.strokeStyle = css("--map"); ctx.lineWidth = 1.2; ctx.stroke(); ctx.globalAlpha = 1;
    if (st === "o") { ctx.beginPath(); ctx.arc(X, Y, size + 5, 0, 6.2832); ctx.strokeStyle = col; ctx.lineWidth = 1.5; ctx.stroke(); }
    if (st === "h") { ctx.beginPath(); ctx.arc(X, Y, size + 5, 0, 6.2832); ctx.strokeStyle = css("--warn"); ctx.lineWidth = 2.2; ctx.stroke(); ctx.fillStyle = css("--warn"); ctx.fillRect(X - 3, Y - size - 11, 2, 7); ctx.fillRect(X + 1, Y - size - 11, 2, 7); }
    if (st === "r") { ctx.beginPath(); ctx.arc(X, Y, size + 5, 0, 6.2832); ctx.strokeStyle = css("--civilian"); ctx.lineWidth = 2; ctx.setLineDash([3, 3]); ctx.stroke(); ctx.setLineDash([]); }
    if (st === "L" || st === "F") { ctx.strokeStyle = css("--bad"); ctx.lineWidth = 2.5; ctx.beginPath(); ctx.moveTo(X - 7, Y - 7); ctx.lineTo(X + 7, Y + 7); ctx.moveTo(X + 7, Y - 7); ctx.lineTo(X - 7, Y + 7); ctx.stroke(); }
    if (state.sel === a.id || state.hover === a.id) { ctx.beginPath(); ctx.arc(X, Y, size + 9, 0, 6.2832); ctx.strokeStyle = css("--text"); ctx.lineWidth = 1.5; ctx.stroke(); }
    if (state.labels && (state.sel === a.id || view.k * 400 > 120)) { ctx.fillStyle = css("--text"); ctx.font = "10.5px 'Space Grotesk', system-ui, sans-serif"; ctx.fillText(a.id, X + 9, Y - 8); }
  });
  // scale bar
  const sb = niceStep(120 / view.k), len = sb * view.k;
  ctx.strokeStyle = css("--text"); ctx.fillStyle = css("--text"); ctx.lineWidth = 2; ctx.beginPath(); ctx.moveTo(w - 16 - len, h - 16); ctx.lineTo(w - 16, h - 16); ctx.stroke();
  ctx.font = "11px 'Space Grotesk', system-ui, sans-serif"; ctx.textAlign = "right"; ctx.fillText(sb >= 1000 ? sb / 1000 + " km" : sb + " m", w - 16, h - 22); ctx.textAlign = "left";
}
function drawLayer(ctx, w, h, l, t) {
  if (l.t0 !== null && l.t0 !== undefined && t < l.t0) return; if (l.t1 !== null && l.t1 !== undefined && t > l.t1) return;
  const col = l.color || "#ff7b72";
  l.items.forEach((it) => {
    if (it.t0 !== undefined && it.t0 !== null && t < it.t0) return; if (it.t1 !== undefined && it.t1 !== null && t > it.t1) return;
    const c = it.color || col; ctx.strokeStyle = c; ctx.fillStyle = c; ctx.lineWidth = it.width || 1.8;
    if (it.kind === "point") { ctx.beginPath(); ctx.arc(sx(it.x, w), sy(it.y, h), it.r || 4, 0, 6.2832); ctx.fill(); if (it.label) { ctx.font = "11px 'Space Grotesk', system-ui, sans-serif"; ctx.fillText(it.label, sx(it.x, w) + 7, sy(it.y, h) - 6); } }
    else if (it.kind === "line") { ctx.beginPath(); it.pts.forEach((p, i) => (i ? ctx.lineTo(sx(p[0], w), sy(p[1], h)) : ctx.moveTo(sx(p[0], w), sy(p[1], h)))); ctx.globalAlpha = it.alpha || 0.85; ctx.stroke(); ctx.globalAlpha = 1; }
    else if (it.kind === "circle") { ctx.beginPath(); ctx.arc(sx(it.x, w), sy(it.y, h), it.r * view.k, 0, 6.2832); ctx.globalAlpha = 0.9; ctx.stroke(); ctx.globalAlpha = 0.08; ctx.fill(); ctx.globalAlpha = 1; }
    else if (it.kind === "label") { ctx.font = "12px 'Space Grotesk', system-ui, sans-serif"; ctx.fillText(it.label, sx(it.x, w), sy(it.y, h)); }
  });
}

// ---------- timeline and altitude strip ----------
const T0 = TM.t0, T1 = Math.max(TM.t1, TM.t0 + 1);
const tx = (t, w, pad) => pad + ((t - T0) / (T1 - T0)) * (w - 2 * pad);
function drawTimeline() {
  const { ctx, w, h } = fitCanvas($("tl")); ctx.clearRect(0, 0, w, h);
  const pad = 8, y = h / 2;
  ctx.fillStyle = css("--panel2"); ctx.fillRect(pad, y - 3, w - 2 * pad, 6);
  ctx.fillStyle = css("--accent"); ctx.globalAlpha = 0.5; ctx.fillRect(pad, y - 3, tx(state.t, w, pad) - pad, 6); ctx.globalAlpha = 1;
  if (link) { const X = tx(link.t_loss, w, pad); ctx.strokeStyle = css("--bad"); ctx.setLineDash([3, 3]); ctx.beginPath(); ctx.moveTo(X, 2); ctx.lineTo(X, h - 2); ctx.stroke(); ctx.setLineDash([]); ctx.fillStyle = css("--bad"); ctx.font = "10px 'Space Grotesk', system-ui, sans-serif"; ctx.fillText("cut", X + 3, 10);
    link.events.forEach((e) => { const x = tx(e.t, w, pad); ctx.beginPath(); ctx.moveTo(x, y - 8); ctx.lineTo(x + 5, y); ctx.lineTo(x, y + 8); ctx.lineTo(x - 5, y); ctx.closePath(); ctx.fillStyle = css("--warn"); ctx.fill(); }); }
  M.marks.forEach((m) => { const x = tx(m.kind === "engage" ? m.t : m.t1, w, pad); ctx.beginPath();
    if (m.kind === "engage") { ctx.strokeStyle = css("--hostile"); ctx.lineWidth = 2; ctx.moveTo(x - 3, y - 11); ctx.lineTo(x + 3, y - 5); ctx.moveTo(x + 3, y - 11); ctx.lineTo(x - 3, y - 5); ctx.stroke(); }
    else { ctx.arc(x, y - 8, 2.8, 0, 6.2832); ctx.fillStyle = css("--scout"); ctx.fill(); } });
  if (hasPlan) plan.violations.forEach((v) => { if (v.t === null || v.t === undefined) return; const x = tx(v.t, w, pad); ctx.fillStyle = css("--bad"); ctx.beginPath(); ctx.moveTo(x, y + 4); ctx.lineTo(x - 4, y + 12); ctx.lineTo(x + 4, y + 12); ctx.closePath(); ctx.fill(); });
  const X = tx(state.t, w, pad); ctx.fillStyle = css("--text"); ctx.fillRect(X - 1, 3, 2, h - 6);
}
function drawAlt() {
  const { ctx, w, h } = fitCanvas($("alt")); ctx.clearRect(0, 0, w, h);
  const padL = 34, padR = 8, padT = 6, padB = 16, zmax = Math.max(W.rules.z_max * 1.15, 40);
  const X = (t) => padL + ((t - T0) / (T1 - T0)) * (w - padL - padR), Y = (z) => h - padB - (z / zmax) * (h - padT - padB);
  ctx.fillStyle = css("--warn"); ctx.globalAlpha = 0.07; ctx.fillRect(padL, Y(W.rules.z_min), w - padL - padR, Y(0) - Y(W.rules.z_min)); ctx.fillRect(padL, padT, w - padL - padR, Y(W.rules.z_max) - padT); ctx.globalAlpha = 1;
  ctx.strokeStyle = css("--grid"); ctx.fillStyle = css("--muted"); ctx.font = "10px 'Space Grotesk', system-ui, sans-serif"; ctx.lineWidth = 1;
  [0, W.rules.z_min, W.rules.z_max].forEach((z) => { ctx.beginPath(); ctx.moveTo(padL, Y(z)); ctx.lineTo(w - padR, Y(z)); ctx.stroke(); ctx.fillText(Math.round(z) + " m", 2, Y(z) + 3); });
  if (!hasPlan) { ctx.fillText("no plan loaded", padL + 8, h / 2); return; }
  const to = Math.floor(fidx(T1));
  M.aircraft.forEach((a) => {
    const tr = M.tracks[a.id], isSel = state.sel === a.id; ctx.beginPath(); let go = false;
    for (let i = 0; i <= to; i++) { const p = tr.p[i]; if (!p) { go = false; continue; } const x = X(i * TM.dt), y = Y(p[2]); if (!go) { ctx.moveTo(x, y); go = true; } else ctx.lineTo(x, y); }
    ctx.strokeStyle = css("--" + typeKey(a)); ctx.lineWidth = isSel ? 2.4 : 1; ctx.globalAlpha = state.sel ? (isSel ? 1 : 0.18) : 0.55; ctx.stroke(); ctx.globalAlpha = 1;
  });
  ctx.fillStyle = css("--muted"); ctx.fillText("altitude over time" + (state.sel ? " · " + state.sel + " highlighted" : ""), padL + 4, padT + 9);
  ctx.fillStyle = css("--text"); ctx.fillRect(X(state.t) - 1, padT, 2, h - padT - padB);
}

// ---------- side panel ----------
const TABS = [["aircraft", "Aircraft"], ["contacts", "Contacts"], ["issues", "Issues"]];
if (link) TABS.push(["link", "Link"]);
TABS.push(["layers", "Layers"]);
let curTab = hasPlan ? (plan.violations.length ? "issues" : "aircraft") : "contacts";
function esc(s) { return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])); }
function buildCard() {
  const c = $("card"); let h = "";
  if (!hasPlan) {
    const n = (k) => W.contacts.filter((x) => x.cls === k).length;
    h = `<div class="big">${M.aircraft.length} aircraft</div><div class="sub">${n("hostile")} hostile · ${n("unknown")} unknown · ${n("friendly")} friendly · ${n("civilian")} civilian · ${W.zones.length} zones. No plan loaded.</div>`;
  } else if (link) {
    const r = link.retention, ok = !link.failed.length;
    h = `<span class="pill ${ok ? "ok" : "bad"}">${ok ? "run completed without failure" : "RUN FAILED: retention 0"}</span>
      <div class="big" style="margin-top:6px">${r === null ? "–" : Math.round(r * 100) + "%"} <span class="sub" style="font-size:13px;font-weight:400">retention</span></div>
      <div class="bar"><i style="width:${r === null ? 0 : r * 100}%;background:var(--${ok ? "ok" : "bad"})"></i></div>
      <div class="parts"><span>points <b>${link.points}</b> of <b>${link.oracle_points === null ? "–" : link.oracle_points}</b> (oracle)</span><span><b>${link.messages}</b> messages · <b>${link.per_min}</b> per aircraft-min</span><span>${link.setting[0]} m · ${link.setting[1]} B/s</span></div>
      ${link.failed.slice(0, 3).map((f) => `<div class="sub" style="color:var(--bad);margin-top:4px">${esc(f)}</div>`).join("")}`;
  } else if (plan.valid) {
    const p = plan.score_parts;
    h = `<span class="pill ok">valid</span><div class="big" style="margin-top:6px">${plan.score}</div><div class="sub">score</div>
      <div class="parts"><span>points <b>${p.points}</b></span><span>energy <b>−${p.energy_cost}</b> (${plan.energy} Wh)</span><span>effectors <b>−${p.effector_cost}</b> (${plan.effectors})</span></div>`;
  } else {
    h = `<span class="pill bad">INVALID</span><div class="big" style="margin-top:6px">0</div><div class="sub">${plan.violations.length} violation${plan.violations.length === 1 ? "" : "s"}: an invalid plan scores 0. See Issues.</div>`;
  }
  c.innerHTML = h;
}
function buildTabs() {
  $("tabs").innerHTML = TABS.map(([k, n]) => `<button role="tab" data-t="${k}" class="${k === curTab ? "on" : ""}">${n}${k === "issues" && hasPlan ? " (" + plan.violations.length + ")" : ""}</button>`).join("");
  $("tabs").onclick = (e) => { const b = e.target.closest("button"); if (!b) return; curTab = b.dataset.t; buildTabs(); showPanel(); };
}
function showPanel() { document.querySelectorAll(".panel").forEach((p) => p.classList.toggle("on", p.id === "p-" + curTab)); }
function buildPanels() {
  const P = $("panels"); P.innerHTML = "";
  const mk = (id, html) => { const d = document.createElement("div"); d.className = "panel"; d.id = "p-" + id; d.innerHTML = html; P.appendChild(d); return d; };
  // aircraft
  mk("aircraft", `<table><thead><tr><th>Aircraft</th><th>Status</th><th>Alt</th><th>Energy</th></tr></thead><tbody>${M.aircraft.map((a) => `<tr class="row" data-a="${a.id}"><td><span class="dot" style="background:var(--${typeKey(a)})"></span>${a.id}</td><td data-s></td><td data-z></td><td><span class="ebar"><i data-e></i></span></td></tr>`).join("")}</tbody></table>`).onclick = (e) => { const r = e.target.closest("tr[data-a]"); if (r) select(r.dataset.a === state.sel ? null : r.dataset.a); };
  mk("contacts", `<table><thead><tr><th>Contact</th><th>Points</th><th>Needs</th><th>Window</th><th>Served</th></tr></thead><tbody>${W.contacts.map((c) => `<tr class="row" data-c="${c.id}"><td><span class="dot" style="background:var(--${c.cls})"></span>${c.id} <span class="sub">${c.cls}</span></td><td>${c.points || ""}</td><td>${Object.entries(c.needs || {}).filter((x) => x[1] > 0).map((x) => x[1] + " " + x[0][0].toUpperCase()).join(" ")}</td><td>${c.window ? Math.round(c.window[0]) + "–" + Math.round(c.window[1]) + " s" : ""}</td><td data-sv></td></tr>`).join("")}</tbody></table>`).onclick = (e) => { const r = e.target.closest("tr[data-c]"); if (r) { const sv = M.served[r.dataset.c]; if (sv !== undefined) setT(sv); } };
  const issues = hasPlan ? plan.violations : [];
  mk("issues", issues.length ? issues.map((v, i) => `<div class="issue" data-i="${i}"><b>${esc(v.rule)}</b> ${esc(v.msg.replace(/^R\d+ \([^)]*\)\s*/, ""))}${v.t !== null && v.t !== undefined ? ` <span class="sub">· t = ${Math.round(v.t)} s</span>` : ""}</div>`).join("") : `<div class="empty">${hasPlan ? (link ? "No rule broken in this run." : "No violation: the plan is valid.") : "Load a plan to see its verdict."}</div>`).onclick = (e) => {
    const r = e.target.closest(".issue"); if (!r) return; const v = issues[+r.dataset.i]; if (v.t !== null && v.t !== undefined) setT(Math.max(0, v.t - 2)); const id = (v.pair && v.pair[0]) || v.aircraft; if (id) select(id); };
  if (link) mk("link", `<div class="sub" style="padding:6px">Cut at t = ${link.t_loss} s. Events (click to seek):</div>${link.events.map((e) => `<div class="issue" data-t="${e.t}"><b style="color:var(--warn)">${e.kind}</b> t = ${e.t}${e.contact ? " · " + e.contact : ""}${e.aircraft ? " · " + e.aircraft : ""}${e.radius_m ? " · r " + e.radius_m + " m" : ""}</div>`).join("")}
    <div class="sub" style="padding:8px 6px 2px">Messages sent up to now (last 12), grey = not delivered to anyone:</div><div class="log" id="msglog"></div>`).onclick = (e) => { const r = e.target.closest(".issue"); if (r) setT(Math.max(0, +r.dataset.t - 3)); };
  const flags = [["zones", "No-fly zones"], ["protect", "Protected areas"], ["ranges", "Observation and collateral ranges"], ["homes", "Home pads"], ["routes", "Trails and routes"], ["marks", "Observation beams and engagement flashes"]];
  if (link) flags.push(["links", "Message links"]);
  const L = mk("layers", `<div class="layers"><h4>Map</h4>${flags.map(([k, n]) => `<label><input type="checkbox" data-f="${k}" ${state.show[k] ? "checked" : ""}> ${n}</label>`).join("")}
    <h4>Trails</h4><label><input type="radio" name="tr" value="all" checked> all aircraft (last 60 s)</label><label><input type="radio" name="tr" value="selected"> selected or hovered only</label><label><input type="radio" name="tr" value="none"> none</label>
    ${(M.layers || []).length ? "<h4>Your layers</h4>" + M.layers.map((l, i) => `<label><input type="checkbox" data-l="${i}" ${state.layers[i] ? "checked" : ""}><span class="swatch" style="background:${esc(l.color)}"></span> ${esc(l.name)} <span class="sub">(${l.items.length})</span></label>`).join("") : '<h4>Your layers</h4><div class="sub" style="padding:2px 6px">None yet. <code>Viewer(...).layer("name", points=[...], lines=[...])</code> draws your own.</div>'}</div>`);
  L.onchange = (e) => { const t = e.target; if (t.dataset.f) state.show[t.dataset.f] = t.checked; if (t.dataset.l) state.layers[t.dataset.l] = t.checked; if (t.name === "tr") state.trails = t.value; dirty = true; };
  showPanel();
}
const rows = {};
function updatePanels() {
  const t = state.t;
  document.querySelectorAll("#p-aircraft tr[data-a]").forEach((r) => {
    const id = r.dataset.a, st = statusAt(id, t), p = posAt(id, t), e = energyAt(id, t), wh = acById[id].wh;
    r.querySelector("[data-s]").textContent = hasPlan ? STATUS[st] || st : "";
    r.querySelector("[data-z]").textContent = p && st !== "x" ? Math.round(p[2]) + " m" : "";
    const bar = r.querySelector("[data-e]"); bar.style.width = (wh ? (100 * e) / wh : 0) + "%"; bar.style.background = e / wh < 0.2 ? "var(--bad)" : "var(--ok)";
    r.classList.toggle("sel", state.sel === id);
  });
  document.querySelectorAll("#p-contacts tr[data-c]").forEach((r) => {
    const sv = M.served[r.dataset.c]; const td = r.querySelector("[data-sv]");
    td.textContent = sv === undefined ? (hasPlan ? "–" : "") : (sv <= t ? "✓ " : "· ") + Math.round(sv) + " s"; td.style.color = sv !== undefined && sv <= t ? "var(--ok)" : "var(--muted)";
  });
  if (link) { const el = $("msglog"); if (el) el.innerHTML = link.sent.filter((s) => s[0] <= t).slice(-12).map((s) => `<div class="${linkDelivered[s[0] + ":" + s[1]] ? "" : "lost"}">${s[0]} ${s[1]} ${esc(s[2])}</div>`).join(""); }
}

// ---------- link lookup ----------
const linkBySec = {}, linkDelivered = {};
if (link) link.links.forEach((l) => { const s = Math.floor(l[0]) + 1; (linkBySec[s] = linkBySec[s] || []).push(l); if (l[3]) linkDelivered[l[0] + ":" + l[1]] = true; });

// ---------- controls ----------
function select(id) { state.sel = id; dirty = true; updatePanels(); }
function setT(v) { state.t = Math.min(Math.max(v, T0), T1); dirty = true; updateClock(); updatePanels(); }
function updateClock() { $("clock").textContent = `t = ${state.t.toFixed(1)} s / ${Math.round(T1)} s`; if (link) { const cut = state.t >= link.t_loss; const b = $("banner"); b.textContent = cut ? "LINK CUT · policy in command" : "link up · following the plan"; b.className = cut ? "cut" : ""; } else $("banner").style.display = "none"; }
function togglePlay() { if (!hasPlan) return; if (state.t >= T1 - 0.01) state.t = T0; state.playing = !state.playing; $("play").textContent = state.playing ? "❚❚" : "▶"; last = performance.now(); }
let last = performance.now();
function frame(now) {
  const dtm = Math.min((now - last) / 1000, 0.1); last = now;
  if (state.playing) { state.t += dtm * state.speed; if (state.t >= T1) { state.t = T1; state.playing = false; $("play").textContent = "▶"; } dirty = true; updateClock(); }
  if (dirty) { dirty = false; drawMap(); drawTimeline(); drawAlt(); if (!state.playing || Math.floor(now / 100) !== frame.lastPanel) { frame.lastPanel = Math.floor(now / 100); updatePanels(); } }
  requestAnimationFrame(frame);
}
function seekFromEvent(cv, e, pad) { const r = cv.getBoundingClientRect(); const u = (e.clientX - r.left - pad) / (r.width - 2 * pad); setT(T0 + Math.min(Math.max(u, 0), 1) * (T1 - T0)); }
function bindScrub(cv, pad) { let down = false; cv.addEventListener("pointerdown", (e) => { down = true; cv.setPointerCapture(e.pointerId); seekFromEvent(cv, e, pad); }); cv.addEventListener("pointermove", (e) => { if (down) seekFromEvent(cv, e, pad); }); cv.addEventListener("pointerup", () => { down = false; }); }
function bindMap() {
  const cv = $("map"); let drag = null;
  cv.addEventListener("wheel", (e) => { e.preventDefault(); const r = cv.getBoundingClientRect(); const mx = e.clientX - r.left, my = e.clientY - r.top, w = r.width, h = r.height;
    const wx = (mx - w / 2) / view.k + view.cx, wy = (h / 2 - my) / view.k + view.cy; view.k *= Math.exp(-e.deltaY * 0.0012); view.cx = wx - (mx - w / 2) / view.k; view.cy = wy - (h / 2 - my) / view.k; dirty = true; }, { passive: false });
  cv.addEventListener("pointerdown", (e) => { drag = { x: e.clientX, y: e.clientY, cx: view.cx, cy: view.cy, moved: false }; cv.setPointerCapture(e.pointerId); cv.classList.add("drag"); });
  cv.addEventListener("pointermove", (e) => {
    const r = cv.getBoundingClientRect();
    if (drag) { const dx = e.clientX - drag.x, dy = e.clientY - drag.y; if (Math.abs(dx) + Math.abs(dy) > 3) drag.moved = true; view.cx = drag.cx - dx / view.k; view.cy = drag.cy + dy / view.k; dirty = true; }
    const h = nearest(e.clientX - r.left, e.clientY - r.top, r.width, r.height);
    if (!drag) { if (h && h.id !== state.hover) { state.hover = h.kind === "a" ? h.id : null; dirty = true; } if (!h && state.hover) { state.hover = null; dirty = true; } }
    const tip = $("tip"); if (h && !drag) { tip.style.display = "block"; tip.innerHTML = h.html; const tw = tip.offsetWidth; tip.style.left = Math.min(e.clientX - r.left + 14, r.width - tw - 6) + "px"; tip.style.top = Math.max(e.clientY - r.top - tip.offsetHeight - 8, 4) + "px"; } else tip.style.display = "none";
  });
  cv.addEventListener("pointerup", (e) => { cv.classList.remove("drag"); if (drag && !drag.moved) { const r = cv.getBoundingClientRect(); const h = nearest(e.clientX - r.left, e.clientY - r.top, r.width, r.height); select(h && h.kind === "a" ? (h.id === state.sel ? null : h.id) : null); } drag = null; });
  cv.addEventListener("pointerleave", () => { $("tip").style.display = "none"; if (state.hover) { state.hover = null; dirty = true; } });
}
function nearest(mx, my, w, h) {
  let best = null, bd = 14;
  if (hasPlan) M.aircraft.forEach((a) => { const p = posAt(a.id, state.t); const st = statusAt(a.id, state.t); if (!p || st === "x") return; const d = Math.hypot(sx(p[0], w) - mx, sy(p[1], h) - my); if (d < bd) { bd = d; const e = energyAt(a.id, state.t); best = { kind: "a", id: a.id, html: `<b>${a.id}</b> · ${typeLabel(a)}<br>${STATUS[st] || st} · alt ${Math.round(p[2])} m<br>energy ${Math.round(e)} of ${Math.round(a.wh)} Wh` }; } });
  W.contacts.forEach((c) => { const d = Math.hypot(sx(c.x, w) - mx, sy(c.y, h) - my); if (d < bd) { bd = d; const sv = M.served[c.id]; best = { kind: "c", id: c.id, html: `<b>${c.id}</b> · ${reclassAt(c.id, state.t) ? "reclassified: now friendly" : c.cls}${c.points ? "<br>" + c.points + " points" : ""}${Object.keys(c.needs || {}).length ? "<br>needs " + Object.entries(c.needs).filter((x) => x[1] > 0).map((x) => x[1] + " " + x[0]).join(", ") : ""}${c.window ? "<br>window " + Math.round(c.window[0]) + "–" + Math.round(c.window[1]) + " s" : ""}${sv !== undefined ? "<br>served at " + Math.round(sv) + " s" : ""}` }; } });
  return best;
}
function legend() {
  const sw = (cls, txt) => `<span><i style="background:var(--${cls});border-radius:${cls === "civilian" || cls === "scout" ? "50%" : "2px"}"></i>${txt}</span>`;
  $("legend").innerHTML = hasPlan ? `${sw("scout", "scout")}${sw("light", "light effector")}${sw("heavy", "heavy effector")}${sw("hostile", "hostile")}${sw("unknown", "unknown")}${sw("friendly", "friendly")}${sw("civilian", "civilian")}<span style="color:var(--warn)">○ hold</span>` : `${sw("hostile", "hostile")}${sw("unknown", "unknown")}${sw("friendly", "friendly")}${sw("civilian", "civilian")}`;
}
function theme(dark) { state.dark = dark; document.documentElement.setAttribute("data-theme", dark ? "dark" : "light"); try { localStorage.setItem("fleetkit-theme", dark ? "dark" : "light"); } catch (e) { /* no storage */ } dirty = true; }
function init() {
  let dark = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
  try { const s = localStorage.getItem("fleetkit-theme"); if (s) dark = s === "dark"; } catch (e) { /* no storage */ }
  theme(dark);
  $("title").textContent = M.meta.title;
  $("chips").innerHTML = [M.meta.level, "seed " + M.meta.seed, M.aircraft.length + " aircraft", W.contacts.length + " contacts"].map((c) => `<span class="chip">${c}</span>`).join("");
  $("foot-info").textContent = link ? "link-loss replay" : hasPlan ? "plan replay" : "scenario";
  $("speeds").innerHTML = [1, 2, 4, 8, 16, 32].map((s) => `<button data-s="${s}" class="${s === state.speed ? "on" : ""}">${s}×</button>`).join("");
  $("speeds").onclick = (e) => { const b = e.target.closest("button"); if (!b) return; state.speed = +b.dataset.s; document.querySelectorAll("#speeds button").forEach((x) => x.classList.toggle("on", x === b)); };
  $("play").onclick = togglePlay; $("theme").onclick = () => theme(!state.dark); $("help").onclick = () => { $("modal").hidden = false; }; $("close").onclick = () => { $("modal").hidden = true; };
  $("modal").onclick = (e) => { if (e.target === $("modal")) $("modal").hidden = true; };
  if (!hasPlan) { $("transport").style.display = "none"; $("alt").style.display = "none"; }
  buildCard(); buildTabs(); buildPanels(); legend(); bindMap(); bindScrub($("tl"), 8); bindScrub($("alt"), 0);
  document.addEventListener("keydown", (e) => {
    if (e.target.tagName === "INPUT") return; const k = e.key;
    if (k === " ") { e.preventDefault(); togglePlay(); } else if (k === "ArrowRight") setT(state.t + (e.shiftKey ? 10 : 1)); else if (k === "ArrowLeft") setT(state.t - (e.shiftKey ? 10 : 1));
    else if (k === "Home") setT(T0); else if (k === "End") setT(T1); else if (k === "f" || k === "F") fitView(); else if (k === "l" || k === "L") { state.labels = !state.labels; dirty = true; }
    else if (k === "t" || k === "T") theme(!state.dark); else if (k === "Escape") { select(null); $("modal").hidden = true; } else if (k === "?") $("modal").hidden = false;
  });
  window.addEventListener("resize", () => { dirty = true; });
  new ResizeObserver(() => { dirty = true; }).observe($("mapwrap"));
  fitView(); updateClock(); updatePanels();
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(() => { dirty = true; });
  window.__viewer = { setT, select, state, view, M, fitView, togglePlay, draw: () => { drawMap(); drawTimeline(); drawAlt(); updatePanels(); } };
  requestAnimationFrame(frame);
}
init();
})();
