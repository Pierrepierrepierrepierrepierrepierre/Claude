let perfChart = null;
let allRecos = [];

document.addEventListener('DOMContentLoaded', () => {
  initTooltips();
  loadDashboard();
  loadRecos();
});

async function loadDashboard() {
  const period = document.getElementById('period-filter')?.value || '0';
  try {
    const data = await API.get(`/api/dashboard?period_days=${period}`);

    // Alerte scraper
    const alertEl = document.getElementById('scraper-alert');
    if (data.scraper_error) {
      alertEl.textContent = `Scraper en erreur : ${data.scraper_error}`;
      alertEl.classList.remove('hidden');
    } else {
      alertEl.classList.add('hidden');
    }

    // KPI cards
    ['A', 'B', 'C'].forEach(s => {
      const p = data.portfolios?.[s];
      if (!p) return;
      const roiCls = p.roi >= 0 ? 'positive' : 'negative';
      const clvCls = p.clv_mean >= 0 ? 'positive' : 'negative';
      document.getElementById(`kpi-${s}`).innerHTML = `
        <h3>Stratégie ${s}</h3>
        <div class="kpi-value ${roiCls}">${p.roi_pct?.toFixed(2)}%</div>
        <div class="kpi-meta">ROI · ${p.n_bets} paris</div>
        <div class="kpi-row">
          <span>Capital</span><strong>${p.capital_current?.toFixed(0)} €</strong>
        </div>
        <div class="kpi-row">
          <span>CLV moy.</span>
          <strong class="${clvCls}">${p.clv_mean_pct?.toFixed(1)}%</strong>
        </div>
        <div class="kpi-row">
          <span>Drawdown max</span>
          <strong class="${p.drawdown_max_pct > 20 ? 'negative' : ''}">${p.drawdown_max_pct?.toFixed(1)}%</strong>
        </div>
        <div class="kpi-row">
          <span>EV+ bets</span><strong>${p.pct_ev_pos?.toFixed(0)}%</strong>
        </div>
      `;
    });

    // Courbe de performance
    if (data.series) {
      renderPerfChart(data.series);
    }

    // Tableau comparatif
    renderCompareTable(data.portfolios);

    // Scrapers
    renderScraperTable(data.scraper_statuses);

  } catch (e) {
    console.error('Dashboard error:', e);
  }
}

function renderPerfChart(series) {
  const ctx = document.getElementById('perf-chart').getContext('2d');
  const colors = { A: '#4f8ef7', B: '#2ecc71', C: '#f1c40f' };

  const datasets = series.map(s => ({
    label: `Stratégie ${s.strategy}`,
    data: s.points.map(p => ({ x: p.x, y: p.y })),
    borderColor: colors[s.strategy] || '#fff',
    backgroundColor: 'transparent',
    tension: 0.3,
    pointRadius: 3,
  }));

  if (perfChart) {
    perfChart.destroy();
  }
  perfChart = new Chart(ctx, {
    type: 'line',
    data: { datasets },
    options: {
      responsive: true,
      plugins: {
        legend: { labels: { color: '#e8eaf0' } },
        tooltip: { mode: 'index', intersect: false },
      },
      scales: {
        x: {
          type: 'category',
          ticks: { color: '#7f8fa6' },
          grid: { color: '#2d3245' },
        },
        y: {
          ticks: {
            color: '#7f8fa6',
            callback: v => v + ' €',
          },
          grid: { color: '#2d3245' },
        },
      },
    },
  });
}

function renderCompareTable(portfolios) {
  if (!portfolios) return;
  const strategies = ['A', 'B', 'C'];
  const sorted = [...strategies].sort(
    (a, b) => (portfolios[b]?.roi || 0) - (portfolios[a]?.roi || 0)
  );

  const tbody = document.getElementById('compare-body');
  tbody.innerHTML = '';
  strategies.forEach(s => {
    const p = portfolios[s];
    if (!p) return;
    const rank = sorted.indexOf(s) + 1;
    const rankLabel = rank === 1 ? '🥇 1er' : rank === 2 ? '🥈 2e' : '🥉 3e';
    const roiCls = p.roi >= 0 ? 'text-green' : 'text-red';
    const bsCls = p.brier_score < 0.22 ? 'text-green' : 'text-red';
    tbody.insertAdjacentHTML('beforeend', `
      <tr>
        <td><strong>Stratégie ${s}</strong></td>
        <td>${p.capital_current?.toFixed(2)} €</td>
        <td class="${roiCls} bold">${p.roi_pct?.toFixed(2)}%</td>
        <td class="${p.clv_mean >= 0 ? 'text-green' : 'text-red'}">${p.clv_mean_pct?.toFixed(1)}%</td>
        <td>${p.pct_ev_pos?.toFixed(0)}%</td>
        <td class="${p.drawdown_max_pct > 20 ? 'text-red' : ''}">${p.drawdown_max_pct?.toFixed(1)}%</td>
        <td class="${bsCls}">${p.brier_score?.toFixed(3)}</td>
        <td>${rankLabel}</td>
      </tr>
    `);
  });
}

// Métadonnées par scraper : ce qu'il fait + fréquence cible + alerte
const SCRAPER_META = {
  betclic: {
    label: 'Betclic',
    covers: 'Cotes live des matchs (foot 1X2 + BTTS, tennis match-winner)',
    target_freq: '1×/jour minimum',
    stale_hours: 24,
    button_label: '🔄 Re-scraper (5 min, ouvre Chromium)',
    confirm: 'Lance un scrape Betclic complet ? Ouvre une fenêtre Chromium pour ~5 min.',
  },
  fbref: {
    label: 'football-data.co.uk',
    covers: 'Calibration Dixon-Coles (équipes top-5 + L2) + corners/cartons',
    target_freq: '1×/semaine',
    stale_hours: 24 * 7,
    button_label: 'Recalibrer (~30 sec)',
    confirm: 'Recalibrer Dixon-Coles depuis les CSVs football-data ? ~30 sec.',
  },
  tennis_abstract: {
    label: 'tennis_atp / wta (Sackmann)',
    covers: 'Ace rate + double fautes par joueur ATP/WTA × surface',
    target_freq: '1×/semaine',
    stale_hours: 24 * 7,
    button_label: 'Recalibrer (~10 sec)',
    confirm: 'Recharger les datasets Sackmann ATP/WTA ? ~10 sec.',
  },
};

function _ageColor(ranIso, staleHours) {
  if (!ranIso) return 'text-red';
  const ageH = (Date.now() - new Date(ranIso)) / 3600000;
  if (ageH > staleHours) return 'text-red';
  if (ageH > staleHours / 2) return 'text-orange';
  return 'text-green';
}

function _ageLabel(ranIso) {
  if (!ranIso) return 'Jamais';
  const ageH = (Date.now() - new Date(ranIso)) / 3600000;
  if (ageH < 1) return `il y a ${Math.round(ageH * 60)} min`;
  if (ageH < 48) return `il y a ${Math.round(ageH)} h`;
  return `il y a ${Math.round(ageH / 24)} j`;
}

function renderScraperTable(statuses) {
  if (!statuses) return;
  const tbody = document.getElementById('scraper-body');
  tbody.innerHTML = '';
  for (const [name, s] of Object.entries(statuses)) {
    const meta = SCRAPER_META[name] || {
      label: name, covers: '', target_freq: '', stale_hours: 24,
      button_label: 'Lancer', confirm: 'Lancer ce scraper ?'
    };
    const ageCls = _ageColor(s.ran_at, meta.stale_hours);
    const ageStr = _ageLabel(s.ran_at);
    const badge = s.status === 'ok'
      ? '<span class="badge positive">OK</span>'
      : s.status === 'jamais'
      ? '<span class="badge neutral">Jamais lancé</span>'
      : '<span class="badge negative">Erreur</span>';
    const tooltip = s.message ? `title="${s.message.replace(/"/g, '&quot;')}"` : '';
    tbody.insertAdjacentHTML('beforeend', `
      <tr ${tooltip}>
        <td><strong>${meta.label}</strong></td>
        <td><small class="text-muted">${meta.covers}</small></td>
        <td><small class="text-muted">${meta.target_freq}</small></td>
        <td class="${ageCls} bold">${ageStr}<br><small class="text-muted">${s.ran_at ? s.ran_at.slice(0,16).replace('T',' ') : ''}</small></td>
        <td>${badge}</td>
        <td><button class="btn-xs" onclick="runScraperConfirm('${name}')">${meta.button_label}</button></td>
      </tr>
    `);
  }
}

function toggleDiag() {
  const c = document.getElementById('diag-content');
  const btn = document.getElementById('diag-toggle');
  const open = !c.classList.contains('hidden');
  c.classList.toggle('hidden', open);
  btn.textContent = open ? '▶ 🔧 Diagnostic & maintenance scrapers' : '▼ 🔧 Diagnostic & maintenance scrapers';
}

async function runScraperConfirm(name) {
  const meta = SCRAPER_META[name] || { confirm: 'Lancer ce scraper ?' };
  if (!confirm(meta.confirm)) return;
  await runScraper(name);
}

async function runScraper(name) {
  try {
    await API.post(`/api/scraper/run?scraper=${name}`, {});
    setTimeout(loadDashboard, 2000);
  } catch (e) {
    alert('Erreur : ' + e.message);
  }
}

// ── Recommandations du jour ────────────────────────────────────────────────

async function loadRecos() {
  const loading = document.getElementById('recos-loading');
  const table = document.getElementById('recos-table');
  const empty = document.getElementById('recos-empty');
  loading.classList.remove('hidden');
  table.classList.add('hidden');
  empty.classList.add('hidden');

  try {
    const data = await API.get('/api/recommendations');
    allRecos = (data.data || []).sort((a, b) => (b.ev || 0) - (a.ev || 0));
    loading.classList.add('hidden');
    renderRecos();
  } catch (e) {
    loading.textContent = 'Erreur lors du chargement des recommandations.';
  }
}

function reloadRecos() {
  // Force rerun pipeline puis reload
  API.post('/api/pipeline/run', {})
    .then(() => loadRecos())
    .catch(() => loadRecos());
}

async function rescrapeBetclic() {
  if (!confirm('Lancer un scrape Betclic complet ? Une fenêtre Chromium va s\'ouvrir pour ~5 min. Ne la ferme pas.')) return;
  try {
    await API.post('/api/scraper/run?scraper=betclic', {});
    const banner = document.createElement('div');
    banner.className = 'alert alert-warn';
    banner.style = 'margin:16px 0';
    banner.innerHTML = '⏳ Scrape Betclic en cours (fenêtre Chromium ouverte)... Reviens dans ~5 min puis clique <strong>↻ Actualiser</strong>.';
    const recosCard = document.querySelector('.card');
    recosCard.parentNode.insertBefore(banner, recosCard);
    setTimeout(() => banner.remove(), 60000);
  } catch (e) {
    alert('Erreur démarrage scraper : ' + e.message);
  }
}

function renderRecos() {
  const sport = document.getElementById('recos-sport').value;
  const strategy = document.getElementById('recos-strategy').value;
  const conf = document.getElementById('recos-conf').value;

  let recos = allRecos;
  if (sport) recos = recos.filter(r => r.sport === sport);
  if (strategy) recos = recos.filter(r => r.strategy === strategy);
  if (conf === 'high') recos = recos.filter(r => r.confidence === 'high');
  else if (conf === 'medium') recos = recos.filter(r => r.confidence !== 'low');

  const table = document.getElementById('recos-table');
  const empty = document.getElementById('recos-empty');
  const tbody = document.getElementById('recos-body');

  if (recos.length === 0) {
    empty.classList.remove('hidden');
    table.classList.add('hidden');
    return;
  }

  tbody.innerHTML = '';
  for (const r of recos) {
    const sportIcon = r.sport === 'football' ? '⚽' : r.sport === 'tennis' ? '🎾' : '•';
    const stratBadge = r.strategy === 'A'
      ? '<span class="badge badge-blue">A</span>'
      : '<span class="badge badge-green">B</span>';
    const evClass = r.ev_pct >= 20 ? 'ev-high' : r.ev_pct >= 8 ? 'ev-ok' : '';
    const valClass = r.value_pct >= 10 ? 'text-green bold' : r.value_pct >= 5 ? 'text-green' : '';
    const confBadge = {
      high:   '<span class="badge positive" title="Tous les params connus">●●●</span>',
      medium: '<span class="badge neutral" title="Params partiels">●●○</span>',
      low:    '<span class="badge negative" title="Match flou ou peu de données">●○○</span>',
    }[r.confidence] || '';

    // Outcome court depuis description : "Nul (PSG - Nantes)" -> "Nul"
    const shortDesc = (r.description || '').split('(')[0].trim() || r.niche;
    const eventName = r.event_name || (r.home_team && r.away_team ? `${r.home_team} - ${r.away_team}` : r.player_a + ' - ' + r.player_b);
    const eventDate = r.event_date ? r.event_date.slice(0, 16).replace('T', ' ') : '—';

    tbody.insertAdjacentHTML('beforeend', `
      <tr>
        <td>${sportIcon} ${stratBadge}</td>
        <td><strong>${eventName}</strong>${r.league ? `<br><small class="text-muted">${r.league}</small>` : ''}</td>
        <td>${shortDesc} ${confBadge}</td>
        <td>${(r.p_estimated * 100).toFixed(1)}%</td>
        <td class="odds-normal">${r.odds_fair?.toFixed(2)}</td>
        <td class="odds-val">${r.odds_betclic?.toFixed(2)}</td>
        <td>${formatVar(r.variation)}</td>
        <td class="${valClass}">+${r.value_pct?.toFixed(1)}%</td>
        <td class="${evClass}">+${r.ev_pct?.toFixed(1)}%</td>
        <td>${r.rf?.toFixed(2)}<br><small class="text-muted">${r.rf_label}</small></td>
        <td><strong>${r.stake?.toFixed(2)} €</strong></td>
        <td><small class="text-muted">${eventDate}</small></td>
        <td><button class="btn-xs btn-primary" onclick='placeBet(${JSON.stringify(r)})'>Parier</button></td>
      </tr>
    `);
  }
  table.classList.remove('hidden');
}

function formatVar(v) {
  if (!v || v.delta_pct == null) return '<span class="text-muted">—</span>';
  const cls = v.delta_pct < 0 ? 'text-green' : v.delta_pct > 0 ? 'text-red' : 'text-muted';
  const sign = v.delta_pct > 0 ? '+' : '';
  const arrow = v.delta_pct < 0 ? '↘' : v.delta_pct > 0 ? '↗' : '→';
  return `<span class="${cls}" title="${v.first} → ${v.last} sur ${v.n_snapshots} snap, ${v.span_hours}h">${arrow} ${sign}${v.delta_pct.toFixed(1)}%</span>`;
}

function placeBet(reco) {
  // Encode l'outcome (home/draw/away) pour que features_json puisse être utilisé au resolve
  const desc = (reco.description || '').toLowerCase();
  let outcome = '';
  if (desc.includes('nul') || desc.includes('draw')) outcome = 'draw';
  else if (desc.includes('domicile') || desc.includes('home')) outcome = 'home';
  else if (desc.includes('extérieur') || desc.includes('away')) outcome = 'away';

  const params = new URLSearchParams({
    strategy: reco.strategy,
    market: (reco.description || reco.niche).slice(0, 60),
    sport: reco.sport,
    odds: reco.odds_betclic,
    stake: reco.stake?.toFixed(2),
    ev: reco.ev,
    p: reco.p_estimated,
    league: reco.league || '',
    event_name: reco.event_name || '',
    event_date: reco.event_date || '',
    outcome: outcome,
  });
  window.location.href = '/simulation?' + params.toString();
}
