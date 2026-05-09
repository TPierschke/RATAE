/* Universal live-data binder for the static mockup pages.
   Polls /state every 5s and replaces the dummy text values that every
   mockup ships with by the real sensor readings. Walks text nodes only,
   so it doesn't touch CSS, attributes, or selectors. */
(function () {
  'use strict';

  // Format helpers
  function fmtTemp(v, prefix) {
    if (v === null || v === undefined) return '---';
    var n = Number(v);
    if (Number.isNaN(n)) return '---';
    var s = (n >= 0 && prefix ? '+' : '') + n.toFixed(1) + '°';
    return s;
  }
  function pad(n) { return n.toString().padStart(2, '0'); }
  function fmtClock(date) {
    return pad(date.getHours()) + ':' + pad(date.getMinutes());
  }

  // The dummy values that all mockups ship with. Patterns are only added if
  // we have a real reading — otherwise the mockup-dummy stays untouched, which
  // is a much friendlier fallback than printing "---" or "UNKNOWN" everywhere.
  function buildPatterns(s, wpState) {
    var patterns = [];
    function add(re, val) { if (val !== null && val !== undefined && val !== '---') patterns.push([re, val]); }
    function fmt(v, signed) {
      if (v === null || v === undefined) return null;
      var n = Number(v);
      if (Number.isNaN(n)) return null;
      return (n >= 0 && signed ? '+' : '') + n.toFixed(1) + '°';
    }

    var aussen = fmt(s.aussen, true);
    var ww = fmt(s.warmwasser, false);
    var vl = fmt(s.vorlauf, false);
    var rl = fmt(s.ruecklauf, false);

    // Order matters: longest / most-specific patterns first.
    if (aussen) {
      add(/\+5\.2°C\/min/g, aussen + 'C/min');
      add(/\+5\.2°C/g, aussen + 'C');
      add(/\+?5\.2°/g, aussen);
    }
    if (ww) {
      add(/52\.8°C/g, ww + 'C');
      add(/52\.8°/g, ww);
      add(/52\.8 C\b/g, ww + 'C');
    }
    if (vl) {
      add(/36\.4°C/g, vl + 'C');
      add(/36\.4°/g, vl);
      add(/36\.4 C\b/g, vl + 'C');
    }
    if (rl) {
      add(/28\.1°C/g, rl + 'C');
      add(/28\.1°/g, rl);
      add(/28\.1 C\b/g, rl + 'C');
    }
    // wp_state: only replace HEIZUNG when we have a known concrete state
    // that is not UNKNOWN. Otherwise keep the dummy text.
    if (wpState && wpState !== 'UNKNOWN') {
      add(/\bHEIZUNG\b/g, wpState.toUpperCase());
    }
    return patterns;
  }

  function walkText(node, fn) {
    if (node.nodeType === 3) {
      fn(node);
      return;
    }
    if (node.nodeType !== 1) return;
    if (node.tagName === 'SCRIPT' || node.tagName === 'STYLE') return;
    if (node.id === 'theme-switcher' || (node.parentElement && node.parentElement.id === 'theme-switcher')) return;
    var children = Array.from(node.childNodes);
    children.forEach(function (c) { walkText(c, fn); });
  }

  // Cache the original text content of every text node on first paint, so we
  // can re-apply patterns idempotently without compounding partial replaces.
  var snapshot = null;
  function captureSnapshot() {
    snapshot = [];
    walkText(document.body, function (n) {
      snapshot.push({ node: n, text: n.nodeValue });
    });
  }

  function applyState(s, wpState) {
    if (!snapshot) return;
    var patterns = buildPatterns(s, wpState);
    snapshot.forEach(function (entry) {
      var t = entry.text;
      patterns.forEach(function (p) { t = t.replace(p[0], p[1]); });
      if (entry.node.nodeValue !== t) entry.node.nodeValue = t;
    });
  }

  function showOffline() {
    // mark a tiny status text in the theme switcher so the user knows we
    // could not reach /state. Non-intrusive.
    var sel = document.getElementById('theme-switcher-select');
    if (sel && sel.parentElement && !sel.parentElement.dataset.warned) {
      sel.parentElement.dataset.warned = '1';
      var lbl = sel.parentElement.querySelector('label');
      if (lbl) lbl.textContent = 'Theme (offline):';
    }
  }

  async function tick() {
    try {
      var r = await fetch('/state', { cache: 'no-store' });
      if (!r.ok) return showOffline();
      var data = await r.json();
      applyState(data.sensoren || {}, data.wp_state);
    } catch (e) {
      showOffline();
    }
  }

  function start() {
    captureSnapshot();
    tick();
    setInterval(tick, 5000);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start);
  } else {
    start();
  }
})();
