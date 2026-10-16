/* HarnessGuard behaviour collector (SPEC section 5).
 * Privacy rules are mandatory: never record key values, input values or
 * passwords -- only timings, key classes and value lengths.
 * No external libraries. Included on every portal page via base.html.
 */
(function () {
  "use strict";

  var meta = document.querySelector('meta[name="hg-session"]');
  if (!meta || !meta.content) return;

  var SESSION_ID = meta.content;
  var PAGE_LOAD_ID = (window.crypto && crypto.randomUUID)
    ? crypto.randomUUID()
    : "pl-" + Date.now() + "-" + Math.random().toString(16).slice(2);
  var PATH = location.pathname;
  var ENDPOINT = "/api/events";

  var FLUSH_MS = 2000;        // batch cadence
  var SUBMIT_FLUSH_MS = 800;  // max wait before a form submit
  var MOVE_MS = 50;           // mousemove throttle
  var SCROLL_MS = 100;        // scroll throttle

  // Per-session monotonic counter. Keyed by session id and kept in
  // localStorage so it survives navigation AND is shared by every tab of the
  // same session (the server drops duplicate (session_id, seq) pairs, so a
  // counter that restarted in a new tab would silently lose events).
  var SEQ_KEY = "hg_seq:" + SESSION_ID;
  var store = (function () {
    try { localStorage.setItem("hg_t", "1"); localStorage.removeItem("hg_t"); return localStorage; }
    catch (e) { return sessionStorage; }
  })();
  var seq = 0;
  var buf = [];
  var lastSentSeq = 0;

  function nextSeq() {
    var stored = 0;
    try { stored = parseInt(store.getItem(SEQ_KEY) || "0", 10) || 0; } catch (e) {}
    seq = Math.max(seq, stored) + 1;
    try { store.setItem(SEQ_KEY, String(seq)); } catch (e) {}
    return seq;
  }

  function push(type, data) {
    buf.push({
      seq: nextSeq(),
      t: performance.now(),
      wall: Date.now(),
      type: type,
      page: PATH,
      data: data || {}
    });
  }

  function takeBatch() {
    if (!buf.length) return null;
    var events = buf.splice(0, buf.length);
    return JSON.stringify({
      session_id: SESSION_ID,
      page_load_id: PAGE_LOAD_ID,
      sent_at: Date.now(),
      events: events
    });
  }

  function markSent(events) {
    if (events.length) lastSentSeq = Math.max(lastSentSeq, events[events.length - 1].seq);
  }

  // Periodic flush; keepalive lets it complete during navigation too.
  // force=true (form submit) sends even while a periodic batch is in flight.
  var inFlight = false;
  function flush(force) {
    if (!buf.length || (inFlight && !force)) return Promise.resolve();
    var events = buf.splice(0, buf.length);
    var body = JSON.stringify({
      session_id: SESSION_ID,
      page_load_id: PAGE_LOAD_ID,
      sent_at: Date.now(),
      events: events
    });
    inFlight = true;
    return fetch(ENDPOINT, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      keepalive: true,
      body: body
    }).then(function (r) {
      inFlight = false;
      if (r.ok) markSent(events);
      else buf = events.concat(buf);
    }).catch(function () {
      inFlight = false;
      buf = events.concat(buf);
    });
  }

  function beaconFlush() {
    var body = takeBatch();
    if (!body) return;
    var sent = false;
    try {
      sent = navigator.sendBeacon(
        ENDPOINT, new Blob([body], { type: "application/json" }));
    } catch (e) { sent = false; }
    if (sent) markSent(JSON.parse(body).events);
    else buf = JSON.parse(body).events.concat(buf); // next flush retries
  }

  function stampLastSeq() {
    var inputs = document.querySelectorAll('input[name="hg_last_seq"]');
    for (var i = 0; i < inputs.length; i++) inputs[i].value = String(lastSentSeq);
  }

  // ------------------------------------------------------------- events

  function fingerprint() {
    var renderer = "";
    try {
      var c = document.createElement("canvas");
      var gl = c.getContext("webgl") || c.getContext("experimental-webgl");
      if (gl) {
        var ext = gl.getExtension("WEBGL_debug_renderer_info");
        renderer = ext ? String(gl.getParameter(ext.UNMASKED_RENDERER_WEBGL)) : "";
      }
    } catch (e) {}
    push("fingerprint", {
      webdriver: !!navigator.webdriver,
      ua: navigator.userAgent || "",
      languages_count: (navigator.languages || []).length,
      plugins_count: navigator.plugins ? navigator.plugins.length : 0,
      hardware_concurrency: navigator.hardwareConcurrency || 0,
      device_memory: navigator.deviceMemory || 0,
      screen_w: screen.width, screen_h: screen.height,
      inner_w: window.innerWidth, inner_h: window.innerHeight,
      outer_w: window.outerWidth, outer_h: window.outerHeight,
      dpr: window.devicePixelRatio || 1,
      timezone: (Intl.DateTimeFormat().resolvedOptions() || {}).timeZone || "",
      touch_points: navigator.maxTouchPoints || 0,
      has_chrome_obj: !!window.chrome,
      webgl_renderer: renderer,
      notification_permission:
        ("Notification" in window) ? Notification.permission : ""
    });
  }

  function referrerPath() {
    try { return document.referrer ? new URL(document.referrer).pathname : ""; }
    catch (e) { return ""; }
  }

  function fieldId(t) {
    return (t && t.id) ? String(t.id) : "";
  }

  function keyClass(k) {
    if (k === "Backspace") return "backspace";
    if (k === "Tab") return "tab";
    if (k === "Enter") return "enter";
    if (k && k.length === 1) return /[0-9]/.test(k) ? "digit" : "char";
    return "other";
  }

  var lastMove = 0, lastScroll = 0;

  function install() {
    push("page", { path: PATH, referrer_path: referrerPath() });
    fingerprint();

    document.addEventListener("mousemove", function (e) {
      var now = performance.now();
      if (now - lastMove < MOVE_MS) return;
      lastMove = now;
      push("mousemove", { x: Math.round(e.clientX), y: Math.round(e.clientY) });
    }, { passive: true });

    document.addEventListener("click", function (e) {
      var t = e.target, rect = {};
      if (t && t.getBoundingClientRect) {
        var r = t.getBoundingClientRect();
        rect = { x: Math.round(r.x), y: Math.round(r.y),
                 w: Math.round(r.width), h: Math.round(r.height) };
      }
      push("click", {
        x: Math.round(e.clientX), y: Math.round(e.clientY),
        target_id: fieldId(t),
        target_tag: (t && t.tagName) ? t.tagName.toLowerCase() : "",
        target_rect: rect,
        is_trusted: !!e.isTrusted,
        button: e.button
      });
    }, { passive: true });

    function keyHandler(type) {
      return function (e) {
        push(type, {
          key_class: keyClass(e.key),  // class only, never the key value
          field_id: fieldId(e.target),
          is_trusted: !!e.isTrusted
        });
      };
    }
    document.addEventListener("keydown", keyHandler("keydown"), { passive: true });
    document.addEventListener("keyup", keyHandler("keyup"), { passive: true });

    document.addEventListener("input", function (e) {
      var v = e.target && e.target.value;
      push("input", {
        field_id: fieldId(e.target),
        value_length: (typeof v === "string") ? v.length : 0  // length only
      });
    }, { passive: true });

    document.addEventListener("paste", function (e) {
      push("paste", { field_id: fieldId(e.target) });
    }, { passive: true });

    document.addEventListener("focusin", function (e) {
      push("focus", { field_id: fieldId(e.target) });
    }, { passive: true });

    document.addEventListener("focusout", function (e) {
      push("blur", { field_id: fieldId(e.target) });
    }, { passive: true });

    window.addEventListener("scroll", function () {
      var now = performance.now();
      if (now - lastScroll < SCROLL_MS) return;
      lastScroll = now;
      push("scroll", { scroll_y: Math.round(window.scrollY) });
    }, { passive: true });

    document.addEventListener("visibilitychange", function () {
      push("visibility", { state: document.visibilityState });
      if (document.visibilityState === "hidden") beaconFlush();
    });

    window.addEventListener("pagehide", beaconFlush);

    // Flush pending events before any form submits (max 800 ms), then stamp
    // hg_last_seq so the scorer knows which seq the decision must cover.
    document.addEventListener("submit", function (e) {
      var form = e.target;
      if (!form || form.__hgFlushed) return;
      e.preventDefault();
      push("submit", { form_id: fieldId(form) });
      // The decision must cover every event up to and including this submit,
      // including any batch that is still in flight: stamp the highest seq
      // pushed so far (the scorer waits up to 1.5 s for it to arrive).
      var target = seq;
      var inputs = form.querySelectorAll('input[name="hg_last_seq"]');
      for (var i = 0; i < inputs.length; i++) inputs[i].value = String(target);
      var done = false;
      function finish() {
        if (done) return;
        done = true;
        form.__hgFlushed = true;
        form.submit(); // native submit: skips re-firing the submit event
      }
      var timer = setTimeout(finish, SUBMIT_FLUSH_MS);
      flush(true).then(function () { clearTimeout(timer); finish(); })
                 .catch(function () { clearTimeout(timer); finish(); });
    }, true);

    setInterval(flush, FLUSH_MS);
    stampLastSeq();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", install);
  } else {
    install();
  }
})();
