document.addEventListener('DOMContentLoaded', () => {
  initTooltips();
  loadLastBacktest();
});

async function loadLastBacktest() {
  try {
    const data = await API.get('/api/backtest/last');
    if (data.status === 'ok') {
      renderResults(data.summary, data.sample_bets);
    }
  } catch (_) {}
}

async function runBacktest(e) {
  e.preventDefault();
  const ev = parseFloat(document.getElementById('bt-ev').value) || 0.02;
  const stake = parseFloat(document.getElementById('bt-stake').value) || 10;
  const sel = document.getElementById('bt-leagues');
  const leagues = Array.from(sel.selectedOptions).map(o => o.value).join(',');

  document.getElementById('bt-loading').classList.remove('hidden');
  document.getElementById('bt-results').classList.add('hidden');
  document.getElementById('bt-submit').disabled = true;

  try {
    const params = new URLSearchParams({ ev_threshold: ev, flat_stake: stake });
    if (leagues) params.set('leagues', leagues);
    const res = await API.post('/api/backtest/run?' + params.toString(), {});
    const last = await API.get('/api/backtest/last');
    renderResults(res.data, last.sample_bets || []);
  } catch (err) {
    alert('Erreur backtest : ' + (err.message || err));
  } finally {
    document.getElementById('bt-loading').classList.add('hidden');
    document.getElementById('bt-submit').disabled = false;
  }
}

function renderResults(s, bets) {
  document.getElementById('bt-results').classList.remove('hidden');

  document.getElementById('bt-n').textContent = s.n_bets;
  document.getElementById('bt-hit').textContent = s.hit_rate_pct + '%';
  const roiEl = document.getElementById('bt-roi');
  roiEl.textContent = (s.roi_pct >= 0 ? '+' : '') + s.roi_pct + '%';
  roiEl.className = 'kpi-value ' + (s.roi >= 0 ? 'positive' : 'negative');
  document.getElementById('bt-roi-meta').textContent =
    s.roi >= 0.05 ? '✓ objectif > 5% atteint' :
    s.roi >= 0    ? 'positif mais sous l\'objectif 5%' :
                    '✗ négatif';
  const profitEl = document.getElementById('bt-profit');
  profitEl.textContent = (s.total_profit >= 0 ? '+' : '') + s.total_profit + ' €';
  profitEl.className = 'kpi-value ' + (s.total_profit >= 0 ? 'positive' : 'negative');
  document.getElementById('bt-stake-tot').textContent = s.total_stake.toLocaleString('fr-FR');

  // Par niche
  const nicheBody = document.getElementById('bt-niche-body');
  nicheBody.innerHTML = '';
  const niches = Object.entries(s.by_niche || {}).sort((a, b) => (b[1].roi || 0) - (a[1].roi || 0));
  for (const [niche, st] of niches) {
    const cls = st.roi >= 0 ? 'text-green' : 'text-red';
    nicheBody.insertAdjacentHTML('beforeend', `
      <tr>
        <td><strong>${niche}</strong></td>
        <td>${st.n}</td>
        <td>${(st.hit_rate * 100).toFixed(1)}%</td>
        <td class="${cls} bold">${(st.roi * 100 >= 0 ? '+' : '')}${(st.roi * 100).toFixed(2)}%</td>
        <td class="${cls}">${st.profit >= 0 ? '+' : ''}${st.profit.toFixed(2)} €</td>
      </tr>
    `);
  }

  // Par ligue
  const leagueBody = document.getElementById('bt-league-body');
  leagueBody.innerHTML = '';
  for (const [league, st] of Object.entries(s.by_league || {})) {
    const cls = st.roi >= 0 ? 'text-green' : 'text-red';
    leagueBody.insertAdjacentHTML('beforeend', `
      <tr>
        <td><strong>${league}</strong></td>
        <td>${st.n}</td>
        <td class="${cls} bold">${(st.roi * 100 >= 0 ? '+' : '')}${(st.roi * 100).toFixed(2)}%</td>
        <td class="${cls}">${st.profit >= 0 ? '+' : ''}${st.profit.toFixed(2)} €</td>
      </tr>
    `);
  }

  // Top paris EV extrêmes
  const betsBody = document.getElementById('bt-bets-body');
  betsBody.innerHTML = '';
  for (const b of (bets || []).slice(0, 20)) {
    const evCls = b.ev_pct >= 0 ? 'text-green' : 'text-red';
    const resCls = b.won ? 'badge positive' : 'badge negative';
    betsBody.insertAdjacentHTML('beforeend', `
      <tr>
        <td>${b.date || '—'}</td>
        <td>${b.match}</td>
        <td><span class="badge badge-blue">${b.niche}</span></td>
        <td>${b.p}%</td>
        <td>${b.odds}</td>
        <td class="${evCls} bold">${b.ev_pct >= 0 ? '+' : ''}${b.ev_pct}%</td>
        <td>${b.stake}€</td>
        <td><span class="${resCls}">${b.won ? 'Gagné' : 'Perdu'} (${b.profit >= 0 ? '+' : ''}${b.profit}€)</span></td>
      </tr>
    `);
  }
}
