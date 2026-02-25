
  function showToast(msg, ok = true) {
    const t = document.getElementById('toast');
    t.textContent = msg;
    t.className = 'show ' + (ok ? 'ok' : 'err');
    clearTimeout(t._timer);
    t._timer = setTimeout(() => { t.className = ''; }, 3000);
  }

  function setBadge(id, up) {
    const el = document.getElementById(id);
    if (up === null) {
      el.className = 'badge badge-unknown';
      el.innerHTML = '<span class="dot dot-unknown"></span> —';
    } else if (up) {
      el.className = 'badge badge-up';
      el.innerHTML = '<span class="dot dot-up"></span> UP';
    } else {
      el.className = 'badge badge-down';
      el.innerHTML = '<span class="dot dot-down"></span> DOWN';
    }
  }

  function colorMetric(id, value, unit = '') {
    const el = document.getElementById(id);
    if (value === null || value === undefined) {
      el.innerHTML = '<span class="metric-na">n/a</span>';
      return;
    }
    el.textContent = value + unit;
    // colorisation par seuil
    if (id === 'm-erate') {
      el.className = 'metric-value ' + (value < 5 ? 'good' : value < 20 ? 'warn' : 'bad');
    } else {
      el.className = 'metric-value';
    }
  }

  function syntaxHighlight(obj) {
    const json = JSON.stringify(obj, null, 2);
    return json.replace(
      /("(\\u[\da-fA-F]{4}|\\[^u]|[^\\"])*"(\s*:)?|\b(true|false|null)\b|-?\d+(?:\.\d*)?(?:[eE][+\-]?\d+)?)/g,
      (match) => {
        if (/^"/.test(match)) {
          if (/:$/.test(match)) return `<span class="json-key">${match}</span>`;
          return `<span class="json-str">${match}</span>`;
        }
        if (/true|false/.test(match)) return `<span class="json-bool">${match}</span>`;
        if (/null/.test(match)) return `<span class="json-bool">${match}</span>`;
        return `<span class="json-num">${match}</span>`;
      }
    );
  }

  // ── Polling statut ──────────────────────────────────────────────────────────

  async function refreshStatus() {
    try {
      const res = await fetch('/api/status');
      if (!res.ok) throw new Error('HTTP ' + res.status);
      const d = await res.json();

      setBadge('badge-a', d.primary.up);
      setBadge('badge-b', d.secondary.up);

      const dec = d.current_decision;
      document.getElementById('route-target').textContent =
        dec.routed_to ? dec.routed_to : 'Aucun backend sain';
      document.getElementById('route-reason').textContent = dec.reason || '—';

    // Bandeau panne active?
      const injected = d.stimulus && d.stimulus.failure_injected_ts;
      document.getElementById('failure-banner').classList.toggle('hidden', !injected);

      document.getElementById('refresh-ts').textContent =
        'Dernière mise à jour : ' + new Date().toLocaleTimeString('fr-CA');

    } catch (e) {
      document.getElementById('route-reason').textContent = 'Erreur de connexion au superviseur';
    }
  }

  // ── Polling métriques ───────────────────────────────────────────────────────

  async function refreshMetrics() {
    try {
      const res = await fetch('/api/metrics?post_window_s=300');
      if (!res.ok) {
        // Pas encore de panne injectée → réinitialiser
        colorMetric('m-tbascule1', null);
        colorMetric('m-tbascule2', null);
        colorMetric('m-erate', null);
        colorMetric('m-efailed', null);
        document.getElementById('m-logsize').textContent = '—';
        return;
      }
      const d = await res.json();

      const tb = d.Tbascule;
      colorMetric('m-tbascule1',
        tb.tbascule_200_spare_s !== null ? tb.tbascule_200_spare_s : null, ' s');
      colorMetric('m-tbascule2',
        tb.tbascule_from_first_error_s !== null ? tb.tbascule_from_first_error_s : null, ' s');

      const eb = d.Ebascule;
      colorMetric('m-erate',
        eb.error_rate_percent !== null ? eb.error_rate_percent : null, ' %');

      const failed = eb.failed_requests_in_window;
      const total  = eb.total_requests_in_window;
      document.getElementById('m-efailed').textContent =
        (total > 0) ? `${failed} / ${total}` : '—';

      document.getElementById('m-logsize').textContent =
        d.log ? d.log.size : '—';

    } catch (e) {
      console.error('[refreshMetrics]', e);
    }
  }

  // ── Actions stimulus ────────────────────────────────────────────────────────

  async function failPrimary() {
    try {
      const res = await fetch('/api/stimulus/fail-primary?reason=demo', { method: 'POST' });
      const d = await res.json();
      if (res.ok) showToast('Panne injectée sur Service A', true);
      else        showToast('Erreur : ' + JSON.stringify(d), false);
    } catch { showToast('Impossible de joindre le superviseur', false); }
    refreshStatus();
    refreshMetrics();
  }

  async function recoverPrimary() {
    try {
      const res = await fetch('/api/stimulus/recover-primary', { method: 'POST' });
      const d = await res.json();
      if (res.ok) showToast('Service A rétabli', true);
      else        showToast('Erreur : ' + JSON.stringify(d), false);
    } catch { showToast('Impossible de joindre le superviseur', false); }
    refreshStatus();
    refreshMetrics();
  }

  async function resetMetrics() {
    try {
      const res = await fetch('/api/stimulus/reset-metrics', { method: 'POST' });
      const d = await res.json();
      if (res.ok) showToast('Métriques réinitialisées', true);
      else        showToast('Erreur : ' + JSON.stringify(d), false);
    } catch { showToast('Impossible de joindre le superviseur', false); }
    refreshMetrics();
  }

  async function testOrder() {
    const box = document.getElementById('order-response');
    box.textContent = 'Chargement…';
    try {
      const res = await fetch('/api/orders/1003');
      const d = await res.json();
      box.innerHTML = syntaxHighlight(d);
      showToast(res.ok ? 'Réponse reçue (HTTP ' + res.status + ')' : 'Erreur HTTP ' + res.status, res.ok);
    } catch (e) {
      box.textContent = 'Erreur : ' + e.message;
      showToast('Échec de la requête', false);
    }
    refreshMetrics();
  }

  // ── Test de charge ───────────────────────────────────────────────────────────

  async function runLoadTest() {
    const btn = document.getElementById('btn-loadtest');
    btn.disabled = true;

    const progressWrap = document.getElementById('load-progress');
    const progressBar  = document.getElementById('progress-bar');
    const statusText   = document.getElementById('load-status-text');
    const results      = document.getElementById('load-results');

    progressWrap.classList.remove('hidden');
    results.classList.add('hidden');
    progressBar.style.width = '0%';

    const TOTAL = 75;
    let ok = 0, err = 0;

    for (let i = 1; i <= TOTAL; i++) {
      try {
        const res = await fetch('/api/orders/1003');
        if (res.ok) ok++; else err++;
      } catch {
        err++;
      }
      progressBar.style.width = `${(i / TOTAL) * 100}%`;
      statusText.textContent = `${i} / ${TOTAL}`;
      if (i < TOTAL) await new Promise(r => setTimeout(r, 200));
    }

    const erate = TOTAL > 0 ? ((err / TOTAL) * 100).toFixed(1) : '0';
    document.getElementById('lt-ok').textContent   = ok;
    document.getElementById('lt-err').textContent  = err;
    const erEl = document.getElementById('lt-erate');
    erEl.textContent = erate + ' %';
    erEl.className = 'metric-value ' + (err === 0 ? 'good' : err < 10 ? 'warn' : 'bad');

    results.classList.remove('hidden');
    btn.disabled = false;
    showToast(`Test terminé : ${ok} OK / ${err} erreurs`, err === 0);
    refreshMetrics();
    refreshLog();
  }

  // ── Journal ──────────────────────────────────────────────────────────────────

  async function refreshLog() {
    try {
      const res = await fetch('/api/log?limit=100');
      if (!res.ok) return;
      const d = await res.json();

      document.getElementById('log-info').textContent =
        `${d.total} entrée(s) au total (affichage : ${d.entries.length} dernières)`;

      const tbody = document.getElementById('log-tbody');
      tbody.innerHTML = '';

      const entries = [...d.entries].reverse();
      entries.forEach((e, idx) => {
        const tr  = document.createElement('tr');
        const ts  = new Date(e.ts * 1000).toLocaleTimeString('fr-CA', { hour12: false });
        const cls = e.status === 200 ? 'log-ok' : 'log-err';
        tr.innerHTML = `
          <td class="log-num">${d.total - idx}</td>
          <td>${ts}</td>
          <td class="${cls}">${e.status}</td>
          <td>${e.routed_to || '—'}</td>
          <td class="log-note">${e.note || '—'}</td>
        `;
        tbody.appendChild(tr);
      });
    } catch (e) {
      console.error('[refreshLog]', e);
    }
  }

  refreshStatus();
  refreshMetrics();
  refreshLog();
  setInterval(refreshStatus,  2000);
  setInterval(refreshMetrics, 3000);
  setInterval(refreshLog,     5000);

