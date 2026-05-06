// WP State Machine — Frontend App (Alpine.js)
// SSE-basierter Live-Refresh + Chart.js Mini-Sparklines

document.addEventListener('alpine:init', () => {
  Alpine.data('wpApp', () => ({
    // State
    state: 'UNKNOWN',
    dryRun: true,
    connected: false,
    lastUpdate: null,

    // Sensoren
    vorlauf: null,
    ruecklauf: null,
    warmwasser: null,
    aussen: null,
    heissgas: null,
    verdichter: false,
    ventilWW: false,
    heizstabHz: false,
    heizstabWW: false,
    alarm: false,
    betriebsart: null,

    // Sparkline-Daten (letzte 20 Werte)
    vorlaufHistory: [],
    aussenHistory: [],
    wwHistory: [],

    // UI State
    showConfirm: false,
    confirmAction: null,
    confirmTitle: '',
    confirmText: '',
    statusMessage: '',
    statusOk: true,

    // Betriebsart-Auswahl
    selectedBetriebsart: 3,
    betriebsartNames: {
      1: 'Standby', 2: 'Zeit/Auto', 3: 'Normal',
      4: 'Abgesenkt', 5: 'Party', 6: 'Urlaub', 7: 'Feiertag'
    },

    // SSE-Source
    _sse: null,
    _charts: {},

    init() {
      this.startSSE();
      this.$nextTick(() => this.initCharts());
    },

    startSSE() {
      if (this._sse) this._sse.close();
      this._sse = new EventSource('/stream');

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
        // Reconnect nach 5s
        setTimeout(() => this.startSSE(), 5000);
      };
    },

    applyUpdate(data) {
      this.state = data.state ?? this.state;
      this.dryRun = data.dry_run ?? this.dryRun;
      this.lastUpdate = data.ts ? new Date(data.ts).toLocaleTimeString('de-DE') : null;

      if (data.vorlauf !== undefined) {
        this.vorlauf = data.vorlauf;
        this.pushHistory(this.vorlaufHistory, data.vorlauf);
        this.updateChart('vorlauf', this.vorlaufHistory);
      }
      if (data.aussen !== undefined) {
        this.aussen = data.aussen;
        this.pushHistory(this.aussenHistory, data.aussen);
        this.updateChart('aussen', this.aussenHistory);
      }
      if (data.warmwasser !== undefined) {
        this.warmwasser = data.warmwasser;
        this.pushHistory(this.wwHistory, data.warmwasser);
        this.updateChart('ww', this.wwHistory);
      }
      if (data.verdichter !== undefined) this.verdichter = data.verdichter;
      if (data.alarm !== undefined) this.alarm = data.alarm;
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
        'WW-Bereitung starten',
        `Startet Warmwasser-Bereitung via F:9 WW_ANF.2. ${this.dryRun ? '[DRY-RUN — kein echter CMI-Call]' : 'LIVE: Echter CMI-Call!'}`,
        () => this.startWW()
      );
    },

    async startWW() {
      try {
        const resp = await fetch('/functions/F9/start', {method: 'POST'});
        const data = await resp.json();
        if (data.success) {
          this.showStatus(`WW-Bereitung gestartet${data.dry_run ? ' (DRY-RUN)' : ''}`, true);
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
      const chartDefs = [
        {id: 'chart-vorlauf', key: 'vorlauf', color: '#38bdf8', label: 'Vorlauf'},
        {id: 'chart-aussen', key: 'aussen', color: '#94a3b8', label: 'Aussen'},
        {id: 'chart-ww', key: 'ww', color: '#22c55e', label: 'WW'},
      ];
      for (const def of chartDefs) {
        const el = document.getElementById(def.id);
        if (!el) continue;
        this._charts[def.key] = new Chart(el, {
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
              y: {display: false}
            },
            animation: {duration: 300}
          }
        });
      }
    },

    updateChart(key, data) {
      const chart = this._charts[key];
      if (!chart) return;
      const padded = [...Array(20 - data.length).fill(null), ...data];
      chart.data.datasets[0].data = padded;
      chart.update('quiet');
    },

    destroy() {
      if (this._sse) this._sse.close();
    },
  }));
});
