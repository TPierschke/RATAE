// WP State Machine — Frontend App (Alpine.js)
// SSE-basierter Live-Refresh + Chart.js Mini-Sparklines

document.addEventListener('alpine:init', () => {
  Alpine.data('wpApp', () => ({
    // State
    state: 'UNKNOWN',
    dryRun: true,
    connected: false,
    lastUpdate: null,

    // Sensoren — flache Felder fuer existierende Cards
    vorlauf: null,
    ruecklauf: null,
    warmwasser: null,
    aussen: null,
    heissgas: null,
    fluessigkeit: null,
    saugleitung: null,
    verdichter: false,
    ventilWW: false,
    heizstabHz: false,
    heizstabWW: false,
    pumpeZirku: false,
    pumpeHzkr: false,
    ladepumpe: false,
    phasenwaechter: false,
    verdichterFreigabe: false,
    ndSchalter1: false,
    hdSchalter: false,
    ndSchalter2: false,
    alarm: false,
    betriebsart: null,
    source: 'unknown',  // modbus | web_scraper | json_api | unknown

    // Zaehler / Counter / Messages (Modbus M10..M16)
    betrStdVerdichter: null,
    schaltungenVerdichter: null,
    betrStdHeizstabFb: null,
    betrStdHeizstabWw: null,
    messageFb: null,
    messageWw: null,
    vorlaufSoll: null,
    traum1: null,

    // Sparkline-Daten (letzte 20 Werte)
    vorlaufHistory: [],
    aussenHistory: [],
    wwHistory: [],
    ruecklaufHistory: [],

    // UI State
    showConfirm: false,
    confirmAction: null,
    confirmTitle: '',
    confirmText: '',
    statusMessage: '',
    statusOk: true,
    scraping: false,
    activeTab: 'dashboard',  // 'dashboard' | 'all'

    // Betriebsart-Auswahl
    selectedBetriebsart: 3,
    betriebsartNames: {
      1: 'Standby', 2: 'Zeit/Auto', 3: 'Normal',
      4: 'Abgesenkt', 5: 'Party', 6: 'Urlaub', 7: 'Feiertag'
    },

    // Versions (Footer)
    frontendVersion: '0.1.5-fe-20260506-11',
    backendVersion: 'lade...',

    // SSE-Source
    _sse: null,
    _charts: {},

    init() {
      this.loadBackendVersion();
      this.fetchState();          // Sofort einmal alle Werte holen
      this.startSSE();             // Live-Updates
      this.startPollFallback();    // Sicherheitsnetz alle 15s falls SSE schlaeft
      this.$nextTick(() => this.initCharts());
    },

    async fetchState() {
      try {
        const resp = await fetch('/state', {cache: 'no-store'});
        if (resp.ok) {
          const data = await resp.json();
          this.applyUpdate(data);
        }
      } catch (e) { /* ignorieren, SSE oder Poll versucht's wieder */ }
    },

    startPollFallback() {
      // Wenn SSE laenger als 10s nicht connected ist, holen wir /state per Fetch
      setInterval(() => {
        if (!this.connected) this.fetchState();
      }, 15000);
    },

    async loadBackendVersion() {
      try {
        const resp = await fetch('/api/version');
        if (resp.ok) {
          const data = await resp.json();
          const build = data.build ? ` (${data.build})` : '';
          this.backendVersion = (data.backend || '?') + build;
        } else {
          this.backendVersion = 'http ' + resp.status;
        }
      } catch (e) {
        this.backendVersion = 'fehler';
      }
    },

    _reconnectTimer: null,

    startSSE() {
      // Alte Verbindung wirklich schliessen, sonst Connection-Storm auf iOS
      if (this._sse) {
        try { this._sse.close(); } catch (e) {}
        this._sse = null;
      }
      if (this._reconnectTimer) {
        clearTimeout(this._reconnectTimer);
        this._reconnectTimer = null;
      }

      this._sse = new EventSource('/stream');

      this._sse.onopen = () => {
        this.connected = true;
      };

      this._sse.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          this.applyUpdate(data);
          this.connected = true;
        } catch (e) {
          console.error('SSE parse error:', e);
        }
      };

      this._sse.onerror = () => {
        this.connected = false;
        // Sauber close + EIN Retry, kein Stack
        try { this._sse.close(); } catch (e) {}
        this._sse = null;
        if (!this._reconnectTimer) {
          this._reconnectTimer = setTimeout(() => {
            this._reconnectTimer = null;
            this.startSSE();
          }, 5000);
        }
      };
    },

    applyUpdate(data) {
      if (window.DEBUG_SSE === true) {
        console.log('[SSE]', data);
      }
      this.state = data.state ?? this.state;
      this.dryRun = data.dry_run ?? this.dryRun;
      this.lastUpdate = data.ts ? new Date(data.ts).toLocaleTimeString('de-DE') : null;

      // Neues SSE-Format liefert kompletten Sensoren-Block.
      const s = data.sensoren ?? data;

      if (s.vorlauf !== undefined && s.vorlauf !== null) {
        this.vorlauf = s.vorlauf;
        this.pushHistory(this.vorlaufHistory, s.vorlauf);
        this.updateChart('vorlauf', this.vorlaufHistory);
      }
      if (s.aussen !== undefined && s.aussen !== null) {
        this.aussen = s.aussen;
        this.pushHistory(this.aussenHistory, s.aussen);
        this.updateChart('aussen', this.aussenHistory);
      }
      if (s.warmwasser !== undefined && s.warmwasser !== null) {
        this.warmwasser = s.warmwasser;
        this.pushHistory(this.wwHistory, s.warmwasser);
        this.updateChart('ww', this.wwHistory);
      }
      if (s.ruecklauf !== undefined && s.ruecklauf !== null) {
        this.ruecklauf = s.ruecklauf;
        this.pushHistory(this.ruecklaufHistory, s.ruecklauf);
        this.updateChart('ruecklauf', this.ruecklaufHistory);
      }
      if (s.heissgas !== undefined) this.heissgas = s.heissgas;
      if (s.fluessigkeit !== undefined) this.fluessigkeit = s.fluessigkeit;
      if (s.saugleitung !== undefined) this.saugleitung = s.saugleitung;
      if (s.verdichter !== undefined) this.verdichter = s.verdichter;
      if (s.ventil_ww !== undefined) this.ventilWW = s.ventil_ww;
      if (s.heizstab_hz !== undefined) this.heizstabHz = s.heizstab_hz;
      if (s.heizstab_ww !== undefined) this.heizstabWW = s.heizstab_ww;
      if (s.pumpe_zirku !== undefined) this.pumpeZirku = s.pumpe_zirku;
      if (s.pumpe_hzkr !== undefined) this.pumpeHzkr = s.pumpe_hzkr;
      if (s.ladepumpe !== undefined) this.ladepumpe = s.ladepumpe;
      if (s.phasenwaechter !== undefined) this.phasenwaechter = s.phasenwaechter;
      if (s.verdichter_freigabe !== undefined) this.verdichterFreigabe = s.verdichter_freigabe;
      if (s.nd_schalter1 !== undefined) this.ndSchalter1 = s.nd_schalter1;
      if (s.hd_schalter !== undefined) this.hdSchalter = s.hd_schalter;
      if (s.nd_schalter2 !== undefined) this.ndSchalter2 = s.nd_schalter2;
      if (s.alarm !== undefined) this.alarm = s.alarm;
      if (s.betriebsart !== undefined) this.betriebsart = s.betriebsart;
      if (s.source !== undefined) this.source = s.source;

      // Counter / Messages / Soll
      if (s.betr_std_verdichter !== undefined) this.betrStdVerdichter = s.betr_std_verdichter;
      if (s.schaltungen_verdichter !== undefined) this.schaltungenVerdichter = s.schaltungen_verdichter;
      if (s.betr_std_heizstab_fb !== undefined) this.betrStdHeizstabFb = s.betr_std_heizstab_fb;
      if (s.betr_std_heizstab_ww !== undefined) this.betrStdHeizstabWw = s.betr_std_heizstab_ww;
      if (s.message_fb !== undefined) this.messageFb = s.message_fb;
      if (s.message_ww !== undefined) this.messageWw = s.message_ww;
      if (s.vorlauf_soll !== undefined) this.vorlaufSoll = s.vorlauf_soll;
      if (s.traum1 !== undefined) this.traum1 = s.traum1;
    },

    pushHistory(arr, value) {
      if (value === null || value === undefined) return;
      arr.push(parseFloat(value.toFixed(1)));
      if (arr.length > 20) arr.shift();
    },

    get stateLabel() {
      const labels = {
        'HEIZUNG': 'Heizung aktiv',
        'WARMWASSER': 'Warmwasser',
        'BEREIT': 'Bereit',
        'STANDBY': 'Standby',
        'UNKNOWN': 'Unbekannt',
      };
      return labels[this.state] || this.state;
    },

    get stateColor() {
      if (this.alarm) return 'alarm';
      if (this.state === 'HEIZUNG' || this.state === 'WARMWASSER') return 'active';
      return '';
    },

    get stateIcon() {
      if (this.alarm) return '⚠';
      if (this.state === 'HEIZUNG') return '♨';
      if (this.state === 'WARMWASSER') return '💧';
      if (this.state === 'STANDBY') return '⏸';
      if (this.state === 'BEREIT') return '✓';
      return '?';
    },

    formatTemp(val) {
      if (val === null || val === undefined) return '---';
      return val.toFixed(1) + '°C';
    },

    // Aktionen

    confirmSetBetriebsart() {
      const name = this.betriebsartNames[this.selectedBetriebsart] || this.selectedBetriebsart;
      this.showConfirmDialog(
        `Betriebsart setzen: ${name}`,
        `Setzt F:1 FBHEIZ auf "${name}" (Wert ${this.selectedBetriebsart}). ${this.dryRun ? '[DRY-RUN — kein echter CMI-Call]' : 'LIVE-MODUS: Echter CMI-Schreibzugriff!'}`,
        () => this.setBetriebsart()
      );
    },

    async setBetriebsart() {
      try {
        const resp = await fetch('/functions/F1/betriebsart', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({betriebsart: parseInt(this.selectedBetriebsart)})
        });
        const data = await resp.json();
        if (data.success) {
          this.showStatus(`Betriebsart gesetzt: ${this.betriebsartNames[this.selectedBetriebsart]}${data.dry_run ? ' (DRY-RUN)' : ''}`, true);
        } else {
          this.showStatus(`Fehler: ${data.reason}`, false);
        }
      } catch (e) {
        this.showStatus(`API-Fehler: ${e.message}`, false);
      }
    },

    confirmStartWW() {
      this.showConfirmDialog(
        'Legionellenschutz starten',
        `Startet Legionellenschutz via F:9 WW_ANF.2 (Soll 70 °C). ${this.dryRun ? '[DRY-RUN — kein echter CMI-Call]' : 'LIVE: Echter CMI-Call!'}`,
        () => this.startWW()
      );
    },

    async manualScrape() {
      if (this.scraping) return;
      this.scraping = true;
      try {
        const resp = await fetch('/scrape/run', {method: 'POST'});
        const data = await resp.json();
        if (resp.ok && data.ok) {
          const n = Object.keys(data.values || {}).length;
          this.showStatus(`Webcrawler: ${n} Werte geholt`, true);
        } else {
          this.showStatus(`Scrape-Fehler: ${data.detail || 'unbekannt'}`, false);
        }
      } catch (e) {
        this.showStatus(`Scrape-Fehler: ${e.message}`, false);
      } finally {
        this.scraping = false;
      }
    },

    async startWW() {
      try {
        const resp = await fetch('/functions/F9/start', {method: 'POST'});
        const data = await resp.json();
        if (data.success) {
          this.showStatus(`Legionellenschutz gestartet${data.dry_run ? ' (DRY-RUN)' : ''}`, true);
        } else {
          this.showStatus(`Fehler: ${data.reason}`, false);
        }
      } catch (e) {
        this.showStatus(`API-Fehler: ${e.message}`, false);
      }
    },

    showConfirmDialog(title, text, action) {
      this.confirmTitle = title;
      this.confirmText = text;
      this.confirmAction = action;
      this.showConfirm = true;
    },

    executeConfirm() {
      if (this.confirmAction) {
        this.confirmAction();
        this.confirmAction = null;
      }
      this.showConfirm = false;
    },

    showStatus(msg, ok) {
      this.statusMessage = msg;
      this.statusOk = ok;
      setTimeout(() => { this.statusMessage = ''; }, 5000);
    },

    // Chart.js Sparklines

    initCharts() {
      // Chart.js wird durch Alpine's Reactive-Proxy gestoert (Canvas already-in-use,
      // RangeError max stack). Wir halten die Chart-Instanzen daher AUSSERHALB von
      // Alpine, in einer non-reactive Map auf window.__charts.
      window.__charts = window.__charts || {};
      // Y-Min/Max je Sensor: stabile Skala statt Auto-Scale.
      // Sonst springen die Sparklines unsinnig wenn Werte sich kaum aendern.
      const chartDefs = [
        {id: 'chart-vorlauf',   key: 'vorlauf',   color: '#38bdf8', yMin: 20, yMax: 60},
        {id: 'chart-aussen',    key: 'aussen',    color: '#94a3b8', yMin: -10, yMax: 30},
        {id: 'chart-ww',        key: 'ww',        color: '#22c55e', yMin: 30, yMax: 80},
        {id: 'chart-ruecklauf', key: 'ruecklauf', color: '#f59e0b', yMin: 20, yMax: 50},
      ];
      for (const def of chartDefs) {
        const el = document.getElementById(def.id);
        if (!el) continue;
        // Idempotent: alte Instanz erst zerstoeren
        if (window.__charts[def.key]) {
          try { window.__charts[def.key].destroy(); } catch (e) {}
        }
        try {
          window.__charts[def.key] = new Chart(el, {
            type: 'line',
            data: {
              labels: Array(20).fill(''),
              datasets: [{
                data: Array(20).fill(null),
                borderColor: def.color,
                backgroundColor: def.color + '22',
                borderWidth: 1.5,
                tension: 0.4,
                pointRadius: 0,
                fill: true,
              }]
            },
            options: {
              responsive: true,
              maintainAspectRatio: false,
              plugins: {legend: {display: false}, tooltip: {enabled: false}},
              scales: {
                x: {display: false},
                y: {display: false, min: def.yMin, max: def.yMax}
              },
              animation: false,  // Animationen aus — verhindert Update-Loops
            }
          });
        } catch (e) {
          console.warn('Chart-Init fehlgeschlagen fuer', def.key, e);
        }
      }
    },

    updateChart(key, data) {
      // try-catch: Chart-Fehler darf NIE den applyUpdate-Pfad abbrechen.
      try {
        const chart = window.__charts && window.__charts[key];
        if (!chart) return;
        const padded = [...Array(20 - data.length).fill(null), ...data];
        chart.data.datasets[0].data = padded;
        chart.update('none');
      } catch (e) {
        // stumm — Charts sind nice-to-have, Werte sind wichtiger
      }
    },

    destroy() {
      if (this._sse) this._sse.close();
    },
  }));
});
