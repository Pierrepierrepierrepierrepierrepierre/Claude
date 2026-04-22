document.addEventListener('DOMContentLoaded', () => {
  initTooltips();
  loadCLV();
  loadAlerts();
});

async function loadCLV() {
  const strategy = document.getElementById('strat-filter').value;
  const loading = document.getElementById('clv-loading');
  const table = document.getElementById('clv-table');
  const empty = document.getElementById('clv-empty');

  loading.classList.remove('hidden');
  table.classList.add('hidden');
  empty.classList.add('hidden');

  try {
    const data = await API.get(`/api/strategy-c/clv?strategy=${strategy}`);
    loading.classList.add('hidden');
    updateKPIs(data.data);
    renderCLVTable(data.data.bets || []);
  } catch (_) {
    loading.textContent = 'Erreur lors du chargement.';
  }
}

function updateKPIs(d) {
  const clvEl = document.getElementById('kpi-clv-mean');
  clvEl.textContent = (d.clv_mean_pct ?? 0).toFixed(2) + '%';
  clvEl.className = 'kpi-value ' + (d.clv_mean > 0 ? 'positive' : d.clv_mean < 0 ? 'negative' : '');

  const zEl = document.getElementById('kpi-zscore');
  zEl.textContent = (d.z_score ?? 0).toFixed(2);
  zEl.className = 'kpi-value ' + (d.is_significant ? 'positive' : '');

  document.getElementById('kpi-n-bets').textContent = `${d.n_bets} paris résolus`;
  document.getElementById('kpi-interp').textContent = d.interpretation || '—';
  document.getElementById('kpi-significant').textContent = d.is_significant
    ? '✓ Statistiquement significatif'
    : d.n_bets > 0 ? '⚡ Données insuffisantes' : '';
}

function renderCLVTable(bets) {
  const table = document.getElementById('clv-table');
  const empty = document.getElementById('clv-empty');

  if (!bets || bets.length === 0) {
    empty.classList.remove('hidden');
    return;
  }

  const tbody = document.getElementById('clv-body');
  tbody.innerHTML = '';
  for (const b of bets) {
    const clvClass = b.clv > 0 ? 'text-green' : 'text-red';
    const resultLabel = b.result === 1 ? '<span class="badge positive">Gagné</span>'
      : b.result === 0 ? '<span class="badge negative">Perdu</span>'
      : '<span class="badge neutral">?</span>';
    tbody.insertAdjacentHTML('beforeend', `
      <tr>
        <td>${b.resolved_at ? b.resolved_at.slice(0, 10) : '—'}</td>
        <td>${b.market || '—'}</td>
        <td>${b.sport || '—'}</td>
        <td class="odds-val">${b.odds_taken?.toFixed(2) ?? '—'}</td>
        <td class="odds-normal">${b.odds_close?.toFixed(2) ?? '—'}</td>
        <td class="${clvClass} bold">${b.clv_pct?.toFixed(2)}%</td>
        <td>${resultLabel}</td>
        <td>${b.stake?.toFixed(2)} €</td>
      </tr>
    `);
  }
  table.classList.remove('hidden');
}

async function loadAlerts() {
  const threshold = document.getElementById('alert-threshold').value;
  const loading = document.getElementById('alerts-loading');
  const table = document.getElementById('alerts-table');
  const empty = document.getElementById('alerts-empty');

  loading.classList.remove('hidden');
  table.classList.add('hidden');
  empty.classList.add('hidden');

  try {
    const data = await API.get(`/api/strategy-c/alerts?threshold=${threshold}`);
    loading.classList.add('hidden');

    if (!data.data || data.data.length === 0) {
      empty.classList.remove('hidden');
      return;
    }

    const tbody = document.getElementById('alerts-body');
    tbody.innerHTML = '';
    for (const m of data.data) {
      const varClass = m.variation_pct < 0 ? 'text-green' : 'text-red';
      const signal = m.is_sharp
        ? '<span class="badge positive">Sharp ↓</span>'
        : '<span class="badge neutral">Mouvement</span>';
      tbody.insertAdjacentHTML('beforeend', `
        <tr>
          <td>${m.event_name || m.event_id}</td>
          <td>${m.market_type}</td>
          <td>${m.sport || '—'}</td>
          <td class="odds-normal">${m.odds_open?.toFixed(2) ?? '—'}</td>
          <td class="odds-val">${m.odds_current?.toFixed(2) ?? '—'}</td>
          <td class="${varClass} bold">${m.variation_pct > 0 ? '+' : ''}${m.variation_pct?.toFixed(1)}%</td>
          <td>${signal}</td>
        </tr>
      `);
    }
    table.classList.remove('hidden');
  } catch (_) {
    loading.textContent = 'Erreur lors du chargement.';
  }
}
