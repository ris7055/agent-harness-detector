/* HarnessGuard console helpers: event timelines + mouse-path replay.
 * Loaded on every console page (base.html). */

"use strict";

function hgEsc(s) {
  return String(s ?? "").replace(/[&<>"']/g,
    c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
}

/* One-line human summary of a telemetry event (privacy-safe: data only
 * ever contains timings, key classes and lengths). */
function hgEventSummary(e) {
  const d = e.data || {};
  switch (e.type) {
    case "page": return `→ ${d.path || e.page}`;
    case "fingerprint": return `webdriver=${d.webdriver}, ${d.inner_w}×${d.inner_h}, ${(d.ua || "").slice(0, 40)}…`;
    case "mousemove": return `(${d.x}, ${d.y})`;
    case "click": return `(${d.x}, ${d.y}) ${d.target_tag || ""}${d.target_id ? "#" + d.target_id : ""}${d.is_trusted === false ? " · untrusted" : ""}`;
    case "keydown": case "keyup":
      return `${d.key_class || "?"} ${d.field_id ? "in " + d.field_id : ""}${d.is_trusted === false ? " · untrusted" : ""}`;
    case "input": return `${d.field_id || "?"} len=${d.value_length}`;
    case "paste": return `field ${d.field_id || "?"}`;
    case "focus": case "blur": return d.field_id || "";
    case "scroll": return `y=${d.scroll_y}`;
    case "visibility": return d.state || "";
    case "submit": return `form ${d.form_id || "?"}`;
    default: return "";
  }
}

const HG_TYPE_CLASS = {
  page: "text-indigo-700 font-medium",
  fingerprint: "text-purple-600",
  click: "text-slate-900 font-medium",
  keydown: "text-slate-700", keyup: "text-slate-400",
  input: "text-slate-700",
  submit: "text-red-700 font-medium",
  mousemove: "text-slate-400",
};

/* Render a compact chronological timeline into `el`. */
function hgRenderTimeline(el, events) {
  if (!events || !events.length) {
    el.innerHTML = '<div class="px-4 py-6 text-center text-slate-400 text-sm">No events recorded for this session.</div>';
    return;
  }
  const t0 = events[0].wall_ms || events[0].wall || 0;
  const rows = events.map(e => {
    const wall = e.wall_ms ?? e.wall ?? 0;
    const rel = ((wall - t0) / 1000).toFixed(1);
    const cls = HG_TYPE_CLASS[e.type] || "text-slate-500";
    return `<tr class="border-b border-slate-100">
      <td class="px-3 py-1 font-mono text-xs text-slate-400 w-20">+${rel}s</td>
      <td class="px-3 py-1 text-xs ${cls} w-24">${hgEsc(e.type)}</td>
      <td class="px-3 py-1 text-xs text-slate-400 w-24">${hgEsc(e.page)}</td>
      <td class="px-3 py-1 text-xs text-slate-500">${hgEsc(hgEventSummary(e))}</td>
    </tr>`;
  }).join("");
  el.innerHTML = `<table class="w-full"><tbody>${rows}</tbody></table>`;
}

/* ------------------------------------------------------------------ *
 * Mouse-path replay.
 * mount({canvas, ticks, pageSelect, playBtn, events}) — draws the
 * mousemove trajectory per page over a box scaled to the recorded
 * inner_w×inner_h, clicks as dots, keydowns as ticks underneath.
 * ------------------------------------------------------------------ */
function hgMountReplay(opts) {
  const canvas = opts.canvas, ctx = canvas.getContext("2d");
  const ticks = opts.ticks, tctx = ticks ? ticks.getContext("2d") : null;
  const events = (opts.events || []).slice().sort((a, b) => a.seq - b.seq);

  const fp = [...events].reverse().find(e => e.type === "fingerprint");
  const dim = {
    w: (fp && fp.data && fp.data.inner_w) || 1280,
    h: (fp && fp.data && fp.data.inner_h) || 720,
  };
  canvas.width = dim.w; canvas.height = dim.h;
  canvas.style.aspectRatio = `${dim.w} / ${dim.h}`;
  if (ticks) { ticks.width = 800; ticks.height = 26; }

  const pages = [...new Set(events.filter(e => e.type === "page")
    .map(e => (e.data && e.data.path) || e.page))];
  const select = opts.pageSelect;
  if (select) {
    select.innerHTML = (pages.length ? pages : ["(no page events)"])
      .map(p => `<option value="${hgEsc(p)}">${hgEsc(p)}</option>`).join("");
  }

  function eventsForPage(page) {
    return events.filter(e => e.page === page);
  }

  function drawFrame(pageEvs, uptoWall) {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.strokeStyle = "#cbd5e1";
    ctx.strokeRect(0.5, 0.5, canvas.width - 1, canvas.height - 1);

    const moves = pageEvs.filter(e => e.type === "mousemove" && e.wall_ms <= uptoWall);
    if (moves.length) {
      ctx.beginPath();
      ctx.strokeStyle = "#2563eb";
      ctx.lineWidth = 2;
      ctx.moveTo(moves[0].data.x, moves[0].data.y);
      for (const m of moves) ctx.lineTo(m.data.x, m.data.y);
      ctx.stroke();
      const last = moves[moves.length - 1];
      ctx.beginPath();
      ctx.fillStyle = "#2563eb";
      ctx.arc(last.data.x, last.data.y, 5, 0, Math.PI * 2);
      ctx.fill();
    }
    for (const c of pageEvs) {
      if (c.type !== "click" || c.wall_ms > uptoWall) continue;
      ctx.beginPath();
      ctx.fillStyle = "#dc2626";
      ctx.arc(c.data.x, c.data.y, 6, 0, Math.PI * 2);
      ctx.fill();
      ctx.strokeStyle = "#ffffff";
      ctx.stroke();
    }
    if (!pageEvs.some(e => e.type === "mousemove")) {
      ctx.fillStyle = "#94a3b8";
      ctx.font = "20px sans-serif";
      ctx.fillText("no mouse movement recorded on this page", 24, 40);
    }
  }

  function drawTicks(pageEvs, span) {
    if (!tctx) return;
    tctx.clearRect(0, 0, ticks.width, ticks.height);
    if (!span || span[1] <= span[0]) return;
    for (const e of pageEvs) {
      if (e.type !== "keydown" && e.type !== "submit") continue;
      const x = ((e.wall_ms - span[0]) / (span[1] - span[0])) * ticks.width;
      tctx.strokeStyle = e.type === "submit" ? "#dc2626" : "#64748b";
      tctx.beginPath();
      tctx.moveTo(x, e.type === "submit" ? 2 : 8);
      tctx.lineTo(x, ticks.height - 2);
      tctx.stroke();
    }
  }

  let playing = null;
  function showPage() {
    const page = select ? select.value : (pages[0] || "");
    const pageEvs = eventsForPage(page);
    const walls = pageEvs.map(e => e.wall_ms);
    const span = walls.length ? [Math.min(...walls), Math.max(...walls)] : null;
    drawTicks(pageEvs, span);
    drawFrame(pageEvs, span ? span[1] : Infinity);
    if (opts.playBtn) {
      opts.playBtn.onclick = () => {
        if (playing) cancelAnimationFrame(playing);
        if (!span) return;
        const dur = Math.min(8000, Math.max(2000, (span[1] - span[0]) / 4));
        const t0 = performance.now();
        const frame = now => {
          const frac = Math.min(1, (now - t0) / dur);
          drawFrame(pageEvs, span[0] + frac * (span[1] - span[0]));
          if (frac < 1) playing = requestAnimationFrame(frame);
        };
        playing = requestAnimationFrame(frame);
      };
    }
  }
  if (select) select.onchange = showPage;
  showPage();
}

window.hgEsc = hgEsc;
window.hgRenderTimeline = hgRenderTimeline;
window.hgMountReplay = hgMountReplay;
