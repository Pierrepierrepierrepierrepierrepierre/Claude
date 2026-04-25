// État global : tous les paris du dernier backtest pour tri/filtre client-side
let allBets = [];

document.addEventListener('DOMContentLoaded', () => {
  initTooltips();
  loadAvailableMonths();
  loadLastBacktest();
});

// Charge la liste des mois disponibles dans football-data.co.uk
async function loadAvailableMonths() {
  try {
    const r = await API.get('/api/backtest/months');
    if (r.status !== 'ok') return;
    const sel = document.getElementById('bt-months');
    const labels = {
      '01':'janv', '02':'févr', '03':'mars', '04':'avr', '05':'mai', '06':'juin',
      '07':'juil', '08':'août', '09':'sept', '10':'oct', '11':'nov', '12':'déc',
    };
    sel.innerHTML = r.months.map(m => {
      const [y, mo] = m.split('-');
      const n = r.n_per_month[m] || 0;
      return `<option value="${m}">${labels[mo]} ${y}  (${n} matchs)</option>`;
    }).join('');
    document.getElementById('bt-months-help').textContent =
      `${r.months.length} mois disponibles. Le calcul saute automatiquement les mois sans assez de données d'entraînement (août/septembre).`;
  } catch (_) {}
}

// Charge le dernier backtest s'il y en a un en cache
async function loadLastBacktest() {
  try {
    const r = await API.get('/api/backtest/last');
    if (r.status === 'ok') renderResults(r.data);
  } catch (_) {}
}

async function runBacktest(e) {
  e.preventDefault();
  const ev = parseFloat(document.getElementById('bt-ev').value) || 0.10;
  const stake = parseFloat(document.getElementById('bt-stake').value) || 10;
  const months  = Array.from(document.getElementById('bt-months').selectedOptions).map(o => o.value).join(',');
  const leagues = Array.from(document.getElementById('bt-leagues').selectedOptions).map(o => o.value).join(',');

  // Estimation durée
  const nMois = months ? months.split(',').length : 9;
  document.getElementById('bt-loading').textContent =
    `Backtest en cours sur ${nMois} mois… Estimation ~${Math.max(30, nMois * 60)} sec. ` +
    `Le calcul tourne en arrière-plan, tu peux quitter cette page sans risque.`;
  document.getElementById('bt-loading').classList.remove('hidden');
  document.getElementById('bt-results').classList.add('hidden');
  document.getElementById('bt-submit').disabled = true;
  document.getElementById('bt-submit').textContent = '⏳ Calcul en cours...';

  try {
    const params = new URLSearchParams({ ev_threshold: ev, flat_stake: stake });
    if (months)  params.set('months', months);
    if (leagues) params.set('leagues', leagues);
    const res = await API.post('/api/backtest/run?' + params.toString(), {});
    renderResults(res.data);
  } catch (err) {
    alert('Erreur backtest : ' + (err.message || err));
  } finally {
    document.getElementById('bt-loading').classList.add('hidden');
    document.getElementById('bt-submit').disabled = false;
    document.getElementById('bt-submit').textContent = '▶ Lancer le backtest';
  }
}

function renderResults(data) {
  if (!data || !data.totals) return;
  document.getElementById('bt-results').classList.remove('hidden');
  const t = data.totals;

  // KPIs
  document.getElementById('bt-n').textContent = t.n_bets;
  document.getElementById('bt-months-tested').textContent = `sur ${t.n_months_tested} mois`;
  const roiEl = document.getElementById('bt-roi');
  roiEl.textContent = (t.roi_pct >= 0 ? '+' : '') + t.roi_pct + '%';
  roiEl.className = 'kpi-value ' + (t.roi_pct >= 0 ? 'positive' : 'negative');
  document.getElementById('bt-roi-meta').textContent =
    t.roi_pct >= 5 ? '✓ edge prouvé' :
    t.roi_pct >= 0 ? 'positif mais marge faible' : '✗ négatif — pas d\'edge';
  const profitEl = document.getElementById('bt-profit');
  profitEl.textContent = (t.total_profit >= 0 ? '+' : '') + t.total_profit + ' €';
  profitEl.className = 'kpi-value ' + (t.total_profit >= 0 ? 'positive' : 'negative');
  document.getElementById('bt-stake-tot').textContent = t.total_stake.toLocaleString('fr-FR');
  document.getElementById('bt-hit').textContent = t.hit_rate_pct + '%';

  // Mois par mois
  const mb = document.getElementById('bt-months-body');
  mb.innerHTML = '';
  for (const m of (data.months || [])) {
    const cls = m.roi_pct >= 0 ? 'text-green' : 'text-red';
    mb.insertAdjacentHTML('beforeend', `
      <tr>
        <td><strong>${m.month}</strong></td>
        <td>${m.n_train}</td>
        <td>${m.n_test_matches}</td>
        <td>${m.n_bets}</td>
        <td>${m.hit_rate_pct}%</td>
        <td class="${cls} bold">${m.roi_pct >= 0 ? '+' : ''}${m.roi_pct}%</td>
        <td class="${cls}">${m.profit >= 0 ? '+' : ''}${m.profit}€</td>
        <td class="${m.cumulative_profit >= 0 ? 'text-green' : 'text-red'} bold">${m.cumulative_profit >= 0 ? '+' : ''}${m.cumulative_profit}€</td>
      </tr>
    `);
  }

  // Niche
  const nb = document.getElementById('bt-niche-body');
  nb.innerHTML = '';
  const niches = Object.entries(data.by_niche || {}).sort((a, b) => (b[1].roi_pct || 0) - (a[1].roi_pct || 0));
  for (const [niche, st] of niches) {
    const cls = st.roi_pct >= 0 ? 'text-green' : 'text-red';
    nb.insertAdjacentHTML('beforeend', `
      <tr>
        <td><strong>${niche}</strong></td>
        <td>${st.n}</td>
        <td>${st.hit_rate_pct}%</td>
        <td class="${cls} bold">${st.roi_pct >= 0 ? '+' : ''}${st.roi_pct}%</td>
        <td class="${cls}">${st.profit >= 0 ? '+' : ''}${st.profit.toFixed(2)}€</td>
      </tr>
    `);
  }

  // Stocke et popule filtres tableau
  allBets = data.all_bets || [];
  populateFilterDropdowns(allBets);
  renderBetsTable();
}

function populateFilterDropdowns(bets) {
  const months  = [...new Set(bets.map(b => b.month).filter(Boolean))].sort();
  const niches  = [...new Set(bets.map(b => b.niche))].sort();
  const leagues = [...new Set(bets.map(b => b.league).filter(Boolean))].sort();
  const populate = (id, items, allLabel) => {
    const sel = document.getElementById(id);
    const cur = sel.value;
    sel.innerHTML = `<option value="">${allLabel}</option>` +
      items.map(x => `<option value="${x}">${x}</option>`).join('');
    if (cur) sel.value = cur;
  };
  populate('bt-filter-month',  months,  'Tous mois');
  populate('bt-filter-niche',  niches,  'Toutes niches');
  populate('bt-filter-league', leagues, 'Toutes ligues');
}

const _date = b => {
  if (!b.date) return 0;
  const p = b.date.split('/');
  return p.length === 3 ? new Date(p[2], p[1] - 1, p[0]).getTime() : 0;
};

const _sorters = {
  ev_desc:    (a, b) => b.ev_pct - a.ev_pct,
  ev_asc:     (a, b) => a.ev_pct - b.ev_pct,
  profit_desc:(a, b) => b.profit - a.profit,
  profit_asc: (a, b) => a.profit - b.profit,
  odds_desc:  (a, b) => (b.odds || 0) - (a.odds || 0),
  odds_asc:   (a, b) => (a.odds || 0) - (b.odds || 0),
  abs_ev_desc:(a, b) => Math.abs(b.ev_pct) - Math.abs(a.ev_pct),
  date_desc:  (a, b) => _date(b) - _date(a),
  date_asc:   (a, b) => _date(a) - _date(b),
};

function renderBetsTable() {
  const sort   = document.getElementById('bt-sort').value;
  const fMonth = document.getElementById('bt-filter-month').value;
  const fNiche = document.getElementById('bt-filter-niche').value;
  const fLeague= document.getElementById('bt-filter-league').value;
  const fRes   = document.getElementById('bt-filter-result').value;
  const limit  = parseInt(document.getElementById('bt-limit').value, 10) || 0;

  let bets = allBets.slice();
  if (fMonth)  bets = bets.filter(b => b.month  === fMonth);
  if (fNiche)  bets = bets.filter(b => b.niche  === fNiche);
  if (fLeague) bets = bets.filter(b => b.league === fLeague);
  if (fRes === 'won')  bets = bets.filter(b => b.won);
  if (fRes === 'lost') bets = bets.filter(b => !b.won);
  bets.sort(_sorters[sort] || _sorters.ev_desc);
  const total = bets.length;
  if (limit > 0) bets = bets.slice(0, limit);

  document.getElementById('bt-bets-count').textContent =
    `${bets.length} affichés / ${total} filtrés / ${allBets.length} total`;

  const body = document.getElementById('bt-bets-body');
  body.innerHTML = '';
  for (const b of bets) {
    const evCls = b.ev_pct >= 0 ? 'text-green bold' : 'text-red bold';
    const pCls  = b.profit >= 0 ? 'text-green' : 'text-red';
    const rCls  = b.won ? 'badge positive' : 'badge negative';
    body.insertAdjacentHTML('beforeend', `
      <tr>
        <td><span class="badge badge-blue">${b.month || ''}</span></td>
        <td>${b.date || '—'}</td>
        <td><strong>${b.home} - ${b.away}</strong></td>
        <td><small class="text-muted">${b.league || ''}</small></td>
        <td><span class="badge badge-blue">${b.niche}</span></td>
        <td>${(b.p * 100).toFixed(1)}%</td>
        <td>${b.odds}</td>
        <td class="${evCls}">${b.ev_pct >= 0 ? '+' : ''}${b.ev_pct}%</td>
        <td class="${pCls} bold">${b.profit >= 0 ? '+' : ''}${b.profit}€</td>
        <td><span class="${rCls}">${b.won ? 'Gagné' : 'Perdu'}</span></td>
      </tr>
    `);
  }
}
