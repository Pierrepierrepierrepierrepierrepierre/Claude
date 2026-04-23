// État global : tous les paris du dernier backtest pour tri/filtre client-side
let allBets = [];

document.addEventListener('DOMContentLoaded', () => {
  initTooltips();
  loadLastBacktest();
});

async function loadLastBacktest() {
  try {
    const data = await API.get('/api/backtest/last');
    if (data.status === 'ok') {
      renderResults(data.summary, data.all_bets || data.sample_bets || []);
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
    renderResults(res.data, last.all_bets || last.sample_bets || []);
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

  // Stocke tous les paris pour tri/filtre dynamique côté client
  allBets = bets || [];
  populateFilterDropdowns(allBets);
  renderBetsTable();
}

function populateFilterDropdowns(bets) {
  const niches = [...new Set(bets.map(b => b.niche))].sort();
  const leagues = [...new Set(bets.map(b => b.league || b.match.split(' - ')[0])).values()];
  // En vrai, le league n'est pas dans le bet sample. On déduit depuis la liste fournie ;
  // si non dispo on laisse vide.
  const leaguesSet = [...new Set(bets.map(b => b.league).filter(Boolean))].sort();

  const nicheSel = document.getElementById('bt-filter-niche');
  const leagueSel = document.getElementById('bt-filter-league');
  // On préserve la sélection courante
  const curN = nicheSel.value, curL = leagueSel.value;
  nicheSel.innerHTML = '<option value="">Toutes niches</option>' +
    niches.map(n => `<option value="${n}">${n}</option>`).join('');
  leagueSel.innerHTML = '<option value="">Toutes ligues</option>' +
    leaguesSet.map(l => `<option value="${l}">${l}</option>`).join('');
  if (curN) nicheSel.value = curN;
  if (curL) leagueSel.value = curL;
}

function renderBetsTable() {
  const sort = document.getElementById('bt-sort').value;
  const fNiche  = document.getElementById('bt-filter-niche').value;
  const fLeague = document.getElementById('bt-filter-league').value;
  const fResult = document.getElementById('bt-filter-result').value;
  const limit   = parseInt(document.getElementById('bt-limit').value, 10) || 0;

  let bets = allBets.slice();

  if (fNiche)  bets = bets.filter(b => b.niche === fNiche);
  if (fLeague) bets = bets.filter(b => b.league === fLeague);
  if (fResult === 'won')  bets = bets.filter(b => b.won);
  if (fResult === 'lost') bets = bets.filter(b => !b.won);

  // Tri
  const _date = b => {
    if (!b.date) return 0;
    // Format "DD/MM/YYYY"
    const parts = b.date.split('/');
    if (parts.length !== 3) return 0;
    return new Date(parts[2], parts[1] - 1, parts[0]).getTime();
  };
  const sorters = {
    ev_desc:    (a, b) => b.ev_pct - a.ev_pct,
    ev_asc:     (a, b) => a.ev_pct - b.ev_pct,
    profit_desc:(a, b) => b.profit - a.profit,
    profit_asc: (a, b) => a.profit - b.profit,
    odds_desc:  (a, b) => b.odds   - a.odds,
    odds_asc:   (a, b) => a.odds   - b.odds,
    abs_ev_desc:(a, b) => Math.abs(b.ev_pct) - Math.abs(a.ev_pct),
    date_desc:  (a, b) => _date(b) - _date(a),
    date_asc:   (a, b) => _date(a) - _date(b),
  };
  bets.sort(sorters[sort] || sorters.ev_desc);

  const total = bets.length;
  if (limit > 0) bets = bets.slice(0, limit);

  document.getElementById('bt-bets-count').textContent =
    `${bets.length} affichés / ${total} filtrés / ${allBets.length} total`;

  const body = document.getElementById('bt-bets-body');
  body.innerHTML = '';
  for (const b of bets) {
    const evCls    = b.ev_pct >= 0 ? 'text-green bold' : 'text-red bold';
    const profCls  = b.profit >= 0 ? 'text-green' : 'text-red';
    const resCls   = b.won ? 'badge positive' : 'badge negative';
    body.insertAdjacentHTML('beforeend', `
      <tr>
        <td>${b.date || '—'}</td>
        <td><strong>${b.match}</strong></td>
        <td><small class="text-muted">${b.league || ''}</small></td>
        <td><span class="badge badge-blue">${b.niche}</span></td>
        <td>${b.p}%</td>
        <td>${b.odds}</td>
        <td class="${evCls}">${b.ev_pct >= 0 ? '+' : ''}${b.ev_pct}%</td>
        <td>${b.stake}€</td>
        <td class="${profCls} bold">${b.profit >= 0 ? '+' : ''}${b.profit}€</td>
        <td><span class="${resCls}">${b.won ? 'Gagné' : 'Perdu'}</span></td>
      </tr>
    `);
  }
}
