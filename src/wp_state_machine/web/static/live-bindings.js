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

  // The dummy values that all mockups ship with. The order matters: longest /
  // most-specific patterns first so we do not partially replace a value.
  function buildPatterns(s, wpState) {
    var aussen = fmtTemp(s.aussen, true);
    var ww = fmtTemp(s.warmwasser, false);
    var vl = fmtTemp(s.vorlauf, false);
    var rl = fmtTemp(s.ruecklauf, false);
    var state = (wpState || 'UNKNOWN').toUpperCase();

    // Pattern: literal regex (escaped), replacement string.
    return [
      [/\+5\.2°C\/min/g, aussen + 'C/min'],     // delta hint should not match
      [/\+5\.2°C/g, aussen + 'C'],
      [/\+?5\.2°/g, aussen],
      [/52\.8°C/g, ww + 'C'],
      [/52\.8°/g, ww],
      [/52\.8 C\b/g, ww + 'C'],
      [/36\.4°C/g, vl + 'C'],
      [/36\.4°/g, vl],
      [/36\.4 C\b/g, vl + 'C'],
      [/28\.1°C/g, rl + 'C'],
      [/28\.1°/g, rl],
      [/28\.1 C\b/g, rl + 'C'],
      // wp_state callouts. We are conservative: only the standalone uppercase
      // word, not partial matches like HEIZUNG-PUMP.
      [/\bHEIZUNG\b/g, state]
    ];
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
