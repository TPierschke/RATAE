/* Universal DOM bindings for the static UI.
   Contract:
   - Poll `/state` every 5 seconds.
   - Use `data-bind`, `data-bind-bool`, `data-bind-alarm`, and `data-bind-state`
     attributes as the single source of truth for live updates.
   - Never throw, never block on fetch errors, and keep the last good values.
   - Accept server state as either `wp_state` or legacy `state`. */
(function () {
  'use strict';

  var POLL_INTERVAL_MS = 5000;
  var MODE_NAMES = {
    1: 'Standby',
    2: 'Zeit/Auto',
    3: 'Normal',
    4: 'Abgesenkt',
    5: 'Party',
    6: 'Urlaub',
    7: 'Feiertag'
  };
  var KNOWN_KEYS = [
    'aussen',
    'vorlauf',
    'ruecklauf',
    'warmwasser',
    'heissgas',
    'fluessigkeit',
    'saugleitung',
    'vorlauf_soll',
    'traum1',
    'betr_std_verdichter',
    'schaltungen_verdichter',
    'betr_std_heizstab_fb',
    'betr_std_heizstab_ww',
    'message_fb',
    'message_ww',
    'betriebsart',
    'wp_state'
  ];
  var KNOWN_KEY_SET = new Set(KNOWN_KEYS.concat(['state']));
  var STATE_CLASSES = [
    'state-heizung',
    'state-warmwasser',
    'state-bereit',
    'state-standby',
    'state-unknown'
  ];

  var logged404 = false;
  var inFlight = false;
  var lastGoodState = null;

  function hasOwn(obj, key) {
    return !!obj && Object.prototype.hasOwnProperty.call(obj, key);
  }

  function isNil(value) {
    return value === null || value === undefined;
  }

  function toNumber(value) {
    var n = Number(value);
    return Number.isFinite(n) ? n : null;
  }

  function normalizeBool(value) {
    if (value === true || value === false) return value;
    if (value === 1 || value === '1') return true;
    if (value === 0 || value === '0') return false;
    if (typeof value === 'string') {
      var v = value.trim().toLowerCase();
      if (v === 'true') return true;
      if (v === 'false') return false;
    }
    return null;
  }

  function formatTemp(value, withSign) {
    var n = toNumber(value);
    if (n === null) return '---';
    return (withSign && n >= 0 ? '+' : '') + n.toFixed(1) + '°';
  }

  function formatValue(value, format) {
    if (isNil(value)) return '---';

    switch (format) {
      case 'temp':
        return formatTemp(value, true);
      case 'temp-no-sign':
        return formatTemp(value, false);
      case 'int': {
        var n = toNumber(value);
        return n === null ? '---' : String(Math.trunc(n));
      }
      case 'bool-de': {
        var b = normalizeBool(value);
        return b === null ? '---' : (b ? 'an' : 'aus');
      }
      case 'bool-onoff': {
        var b2 = normalizeBool(value);
        return b2 === null ? '---' : (b2 ? 'ON' : 'OFF');
      }
      case 'mode': {
        var mode = toNumber(value);
        if (mode === null) return '---';
        mode = Math.trunc(mode);
        return String(mode) + ' — ' + (MODE_NAMES[mode] || '?');
      }
      case 'state':
        return String(value).toUpperCase();
      default:
        return String(value);
    }
  }

  function normalizeState(payload) {
    var data = payload && typeof payload === 'object' ? payload : {};
    var sensors = data.sensoren && typeof data.sensoren === 'object' ? data.sensoren : {};
    var state = {};

    KNOWN_KEYS.forEach(function (key) {
      if (key === 'wp_state') return;
      state[key] = hasOwn(sensors, key) ? sensors[key] : null;
    });

    state.wp_state = !isNil(data.wp_state) ? data.wp_state : (!isNil(data.state) ? data.state : null);
    state.state = state.wp_state;

    return state;
  }

  function getBoundValue(state, key) {
    var resolvedKey = key === 'state' ? 'wp_state' : key;
    if (!KNOWN_KEY_SET.has(key) && !KNOWN_KEY_SET.has(resolvedKey)) {
      return { known: false, value: null };
    }
    return { known: true, value: hasOwn(state, resolvedKey) ? state[resolvedKey] : null };
  }

  function setBinaryClasses(el, value, alarmMode) {
    el.classList.remove('is-on', 'is-off', 'is-unknown', 'is-alarm');
    if (value === true) {
      el.classList.add(alarmMode ? 'is-alarm' : 'is-on');
    } else if (value === false) {
      el.classList.add('is-off');
    } else {
      el.classList.add('is-unknown');
    }
  }

  function applyTextBindings(state) {
    document.querySelectorAll('[data-bind]').forEach(function (el) {
      var key = el.getAttribute('data-bind') || '';
      var result = getBoundValue(state, key);
      if (!result.known) {
        el.textContent = '---';
        return;
      }
      el.textContent = formatValue(result.value, el.getAttribute('data-bind-format') || '');
    });
  }

  function applyBinaryBindings(state, attrName, alarmMode) {
    document.querySelectorAll('[' + attrName + ']').forEach(function (el) {
      var key = el.getAttribute(attrName) || '';
      var result = getBoundValue(state, key);
      var value = result.known ? normalizeBool(result.value) : null;
      setBinaryClasses(el, value, alarmMode);
    });
  }

  function applyStateBindings(state) {
    document.querySelectorAll('[data-bind-state]').forEach(function (el) {
      var rawState = !isNil(state.wp_state) ? String(state.wp_state).toUpperCase() : '---';
      var stateClass = rawState === 'HEIZUNG' || rawState === 'WARMWASSER' ||
        rawState === 'BEREIT' || rawState === 'STANDBY'
        ? 'state-' + rawState.toLowerCase()
        : 'state-unknown';

      el.textContent = rawState;
      el.classList.remove.apply(el.classList, STATE_CLASSES);
      el.classList.add(stateClass);
    });
  }

  function applyState(state) {
    applyTextBindings(state);
    applyBinaryBindings(state, 'data-bind-bool', false);
    applyBinaryBindings(state, 'data-bind-alarm', true);
    applyStateBindings(state);
  }

  function log404Once() {
    if (logged404) return;
    logged404 = true;
    if (window.console && typeof window.console.warn === 'function') {
      window.console.warn('live-bindings: /state returned 404; keeping last good values');
    }
  }

  function tick() {
    if (inFlight) return;
    inFlight = true;

    fetch('/state', { cache: 'no-store' })
      .then(function (response) {
        if (!response.ok) {
          if (response.status === 404) log404Once();
          return null;
        }
        return response.json();
      })
      .then(function (data) {
        if (!data) return;
        lastGoodState = normalizeState(data);
        applyState(lastGoodState);
      })
      .catch(function () {})
      .finally(function () {
        inFlight = false;
      });
  }

  function start() {
    tick();
    window.setInterval(tick, POLL_INTERVAL_MS);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start);
  } else {
    start();
  }
})();
