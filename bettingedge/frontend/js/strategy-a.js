let lastCalcResult = null;

document.addEventListener('DOMContentLoaded', () => {
  initTooltips();
  checkScraperStatus();
  refreshBoosts();
});

async function checkScraperStatus() {
  try {
    const data = await API.get('/api/scraper/status');
    const betclic = data.data?.betclic;
    if (betclic && betclic.status !== 'ok') {
      const el = document.getElementById('scraper-alert');
      el.textContent = `Scraper Betclic : ${betclic.status} — ${betclic.message || ''} (${betclic.ran_at || ''})`;
      el.classList.remove('hidden');
    }
  } catch (_) {}
}

async function refreshBoosts() {
  const loading = document.getElementById('boosts-loading');
  const table = document.getElementById('boosts-table');
  const empty = document.getElementById('boosts-empty');

  loading.classList.remove('hidden');
  table.classList.add('hidden');
  empty.classList.add('hidden');

  try {
    const data = await API.get('/api/strategy-a/boosts');
    loading.classList.add('hidden');

    if (!data.data || data.data.length === 0) {
      empty.classList.remove('hidden');
      return;
    }

    const tbody = document.getElementById('boosts-body');
    tbody.innerHTML = '';
    for (const opp of data.data) {
      const evClass = opp.ev > 0.05 ? 'ev-high' : 'ev-ok';
      tbody.insertAdjacentHTML('beforeend', `
        <tr>
          <td>${opp.event || '—'}</td>
          <td><span class="badge badge-blue">${opp.market || '—'}</span></td>
          <td class="odds-val">${opp.boost_odds?.toFixed(2) ?? '—'}</td>
          <td class="odds-normal">${opp.normal_odds?.toFixed(2) ?? '—'}</td>
          <td>${(opp.p_consensus * 100).toFixed(1)}%</td>
          <td class="${evClass}">${opp.ev_pct?.toFixed(1)}%</td>
          <td>—</td>
          <td>
            <button class="btn-xs" onclick='prefillCalc(${JSON.stringify(opp)})'>
              Calculer
            </button>
          </td>
        </tr>
      `);
    }
    table.classList.remove('hidden');
  } catch (e) {
    loading.textContent = 'Erreur lors du chargement des boosts.';
  }
}

function prefillCalc(opp) {
  document.getElementById('boost-odds').value = opp.boost_odds ?? '';
  window.scrollTo({ top: document.getElementById('calc-form').offsetTop - 20, behavior: 'smooth' });
}

async function calculate(e) {
  e.preventDefault();

  const boostOdds = parseFloat(document.getElementById('boost-odds').value);
  const outcomeIndex = parseInt(document.getElementById('outcome-index').value);
  const portfolio = document.getElementById('portfolio').value;
  const brierScore = parseFloat(document.getElementById('brier-score').value) || 0.20;
  const nSimilaires = parseInt(document.getElementById('n-similaires').value) || 0;
  const clvMean = parseFloat(document.getElementById('clv-mean').value) || 0;

  const toFloat = (id) => {
    const v = parseFloat(document.getElementById(id).value);
    return isNaN(v) ? null : v;
  };

  const h = toFloat('odds-home'), d = toFloat('odds-draw'), a = toFloat('odds-away');
  const ahH = toFloat('odds-ah-home'), ahA = toFloat('odds-ah-away');
  const ouO = toFloat('odds-ou-over'), ouU = toFloat('odds-ou-under');

  const odds1x2 = (h && d && a) ? [h, d, a] : null;
  const oddsAh = (ahH && ahA) ? [ahH, ahA] : null;
  const oddsOu = (ouO && ouU) ? [ouO, ouU] : null;

  if (!odds1x2 && !oddsAh && !oddsOu) {
    alert('Saisir au moins un marché de référence (1X2, AH ou O/U).');
    return;
  }

  try {
    const data = await API.post('/api/strategy-a/calculate', {
      boost_odds: boostOdds,
      odds_1x2: odds1x2,
      odds_ah: oddsAh,
      odds_ou: oddsOu,
      outcome_index: outcomeIndex,
      portfolio: portfolio,
      n_similaires: nSimilaires,
      brier_score: brierScore,
      clv_mean: clvMean,
    });

    lastCalcResult = data;
    displayResult(data);
  } catch (err) {
    alert('Erreur API : ' + (err.message || err));
  }
}

function displayResult(data) {
  const ev = data.ev;
  const stake = data.stake;

  document.getElementById('res-p-consensus').textContent = (ev.p_consensus * 100).toFixed(1) + '%';

  const evEl = document.getElementById('res-ev');
  evEl.textContent = ev.ev_pct.toFixed(2) + '%';
  evEl.className = 'kpi-val ' + (ev.is_positive ? 'text-green' : 'text-red');

  document.getElementById('res-kelly').textContent = (stake.kelly_fraction * 100).toFixed(2) + '%';

  const rfEl = document.getElementById('res-rf');
  rfEl.textContent = stake.rf?.toFixed(3) + ' (' + (stake.rf_label || '') + ')';

  document.getElementById('res-stake').textContent = stake.stake?.toFixed(2) + ' €';
  document.getElementById('res-stake-pct').textContent = stake.stake_pct?.toFixed(2) + '%';

  const verdict = document.getElementById('calc-verdict');
  if (ev.is_positive) {
    verdict.className = 'verdict verdict-ok';
    verdict.textContent = `✓ EV positif — Seuil : ${(ev.threshold_used * 100).toFixed(0)}%. Mise recommandée : ${stake.stake?.toFixed(2)} €`;
  } else {
    verdict.className = 'verdict verdict-nok';
    verdict.textContent = `✗ EV insuffisant (${ev.ev_pct?.toFixed(2)}%) — Seuil : ${(ev.threshold_used * 100).toFixed(0)}%. Ne pas jouer.`;
  }

  document.getElementById('calc-result').classList.remove('hidden');
}

function simulateBet() {
  if (!lastCalcResult) return;
  const ev = lastCalcResult.ev;
  const stake = lastCalcResult.stake;
  const params = new URLSearchParams({
    strategy: 'A',
    market: 'Boost',
    sport: 'football',
    odds: document.getElementById('boost-odds').value,
    stake: stake.stake,
    ev: ev.ev,
    p: ev.p_consensus,
    portfolio: stake.portfolio,
  });
  window.location.href = '/simulation?' + params.toString();
}
