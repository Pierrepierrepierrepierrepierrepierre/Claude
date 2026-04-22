let lastCalcResult = null;
let allBets = [];

const TENNIS_NICHES = ['aces', 'double_faults', 'tiebreaks'];
const FOOT_NICHES = ['corners', 'btts', 'cartons'];

document.addEventListener('DOMContentLoaded', () => {
  initTooltips();
  onNicheChange();
  loadBets();
});

async function loadBets() {
  const loading = document.getElementById('bets-loading');
  const table = document.getElementById('bets-table');
  const empty = document.getElementById('bets-empty');

  loading.classList.remove('hidden');
  table.classList.add('hidden');
  empty.classList.add('hidden');

  try {
    const data = await API.get('/api/strategy-b/bets');
    loading.classList.add('hidden');
    allBets = data.data || [];
    renderBets(allBets);
  } catch (_) {
    loading.textContent = 'Erreur lors du chargement.';
  }
}

function applyFilters() {
  const sport = document.getElementById('filter-sport').value;
  const niche = document.getElementById('filter-niche').value;
  const surface = document.getElementById('filter-surface').value;

  let filtered = allBets;
  if (sport) filtered = filtered.filter(b => b.sport === sport);
  if (niche) filtered = filtered.filter(b => b.niche === niche);
  if (surface) filtered = filtered.filter(b => b.surface === surface);
  renderBets(filtered);
}

function renderBets(bets) {
  const table = document.getElementById('bets-table');
  const empty = document.getElementById('bets-empty');

  if (!bets || bets.length === 0) {
    empty.classList.remove('hidden');
    table.classList.add('hidden');
    return;
  }

  const tbody = document.getElementById('bets-body');
  tbody.innerHTML = '';
  for (const b of bets) {
    const valClass = b.value_pct > 5 ? 'ev-high' : 'ev-ok';
    const evClass = b.ev_pct > 0 ? 'text-green' : 'text-red';
    tbody.insertAdjacentHTML('beforeend', `
      <tr>
        <td><span class="badge badge-blue">${nicheLabel(b.niche)}</span></td>
        <td>${b.event || '—'}</td>
        <td>${b.description || '—'}</td>
        <td>${(b.p_estimated * 100).toFixed(1)}%</td>
        <td class="odds-normal">${b.odds_fair?.toFixed(2) ?? '—'}</td>
        <td class="odds-val">${b.odds_betclic?.toFixed(2) ?? '—'}</td>
        <td class="${valClass}">${b.value_pct?.toFixed(1)}%</td>
        <td class="${evClass}">${b.ev_pct?.toFixed(1)}%</td>
        <td>${b.rf?.toFixed(2)} <small class="text-muted">(${b.rf_label})</small></td>
        <td>${b.stake?.toFixed(2)} €</td>
        <td><button class="btn-xs" onclick='prefillCalc(${JSON.stringify(b)})'>Détail</button></td>
      </tr>
    `);
  }
  table.classList.remove('hidden');
}

function nicheLabel(niche) {
  const labels = {
    corners: 'Corners', btts: 'BTTS', cartons: 'Cartons',
    aces: 'Aces', double_faults: 'DF', tiebreaks: 'TB',
  };
  return labels[niche] || niche;
}

function onNicheChange() {
  const niche = document.getElementById('niche').value;
  const isTennis = TENNIS_NICHES.includes(niche);
  const fieldsFoot = document.getElementById('fields-foot');
  const fieldsTennis = document.getElementById('fields-tennis');
  const fieldThreshold = document.getElementById('field-threshold');
  const fieldReferee = document.getElementById('field-referee');
  const fieldTBThreshold = document.getElementById('field-threshold-tennis');

  fieldsFoot.classList.toggle('hidden', isTennis);
  fieldsTennis.classList.toggle('hidden', !isTennis);

  if (!isTennis) {
    fieldThreshold.classList.toggle('hidden', niche === 'btts');
    fieldReferee.classList.toggle('hidden', niche !== 'cartons');
  }
  if (isTennis) {
    fieldTBThreshold.classList.toggle('hidden', niche === 'tiebreaks');
  }
}

async function calculate(e) {
  e.preventDefault();
  const niche = document.getElementById('niche').value;
  const oddsBetclic = parseFloat(document.getElementById('odds-betclic').value);
  const portfolio = document.getElementById('portfolio').value;
  const brierScore = parseFloat(document.getElementById('brier-score').value) || 0.20;
  const nSimilaires = parseInt(document.getElementById('n-similaires').value) || 0;
  const clvMean = parseFloat(document.getElementById('clv-mean').value) || 0;

  const body = {
    niche,
    sport: TENNIS_NICHES.includes(niche) ? 'tennis' : 'football',
    odds_betclic: oddsBetclic,
    portfolio,
    brier_score: brierScore,
    n_similaires: nSimilaires,
    clv_mean: clvMean,
  };

  if (FOOT_NICHES.includes(niche)) {
    body.home_team = document.getElementById('home-team').value;
    body.away_team = document.getElementById('away-team').value;
    if (niche !== 'btts') {
      body.threshold = parseFloat(document.getElementById('threshold').value);
    }
    if (niche === 'cartons') {
      body.referee = document.getElementById('referee').value;
    }
  } else {
    body.player_a = document.getElementById('player-a').value;
    body.player_b = document.getElementById('player-b').value;
    body.surface = document.getElementById('surface').value;
    body.best_of = parseInt(document.getElementById('best-of').value);
    if (niche !== 'tiebreaks') {
      body.threshold = parseFloat(document.getElementById('threshold-tennis').value);
    }
  }

  try {
    const data = await API.post('/api/strategy-b/calculate', body);
    lastCalcResult = data.data;
    displayResult(data.data);
  } catch (err) {
    alert('Erreur API : ' + (err.message || err));
  }
}

function displayResult(d) {
  document.getElementById('res-p').textContent = (d.p_estimated * 100).toFixed(1) + '%';
  document.getElementById('res-odds-fair').textContent = d.odds_fair?.toFixed(3) ?? '—';

  const valEl = document.getElementById('res-value');
  valEl.textContent = d.value_pct?.toFixed(2) + '%';
  valEl.className = 'kpi-val ' + (d.value_pct > 0 ? 'text-green' : 'text-red');

  const evEl = document.getElementById('res-ev');
  evEl.textContent = d.ev_pct?.toFixed(2) + '%';
  evEl.className = 'kpi-val ' + (d.ev_pct > 0 ? 'text-green' : 'text-red');

  document.getElementById('res-rf').textContent = `${d.rf?.toFixed(3)} (${d.rf_label})`;
  document.getElementById('res-stake').textContent = `${d.stake?.toFixed(2)} €`;

  const verdict = document.getElementById('calc-verdict');
  if (d.is_positive) {
    verdict.className = 'verdict verdict-ok';
    verdict.textContent = `✓ Value positif (${d.value_pct?.toFixed(1)}%). Mise : ${d.stake?.toFixed(2)} €`;
  } else {
    verdict.className = 'verdict verdict-nok';
    verdict.textContent = `✗ Pas de value (${d.value_pct?.toFixed(1)}%). Ne pas jouer.`;
  }

  document.getElementById('calc-result').classList.remove('hidden');
}

function prefillCalc(bet) {
  document.getElementById('niche').value = bet.niche || 'corners';
  onNicheChange();
  if (bet.odds_betclic) document.getElementById('odds-betclic').value = bet.odds_betclic;
  window.scrollTo({ top: document.getElementById('calc-form').offsetTop - 20, behavior: 'smooth' });
}

function simulateBet() {
  if (!lastCalcResult) return;
  const params = new URLSearchParams({
    strategy: 'B',
    market: lastCalcResult.niche,
    sport: lastCalcResult.sport,
    odds: lastCalcResult.odds_betclic,
    stake: lastCalcResult.stake,
    ev: lastCalcResult.ev,
    p: lastCalcResult.p_estimated,
    portfolio: 'B',
  });
  window.location.href = '/simulation?' + params.toString();
}
