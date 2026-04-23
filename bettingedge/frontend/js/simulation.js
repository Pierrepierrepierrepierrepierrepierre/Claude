let currentResolveBetId = null;

document.addEventListener('DOMContentLoaded', () => {
  initTooltips();
  loadBets();
  prefillFromParams();
});

// Métadonnées d'événement passées par la page Recos pour le auto-CLV au resolve
let pendingMeta = {};

function prefillFromParams() {
  const params = new URLSearchParams(window.location.search);
  if (!params.get('strategy')) return;

  document.getElementById('f-strategy').value = params.get('strategy') || 'A';
  document.getElementById('f-market').value = params.get('market') || '';
  document.getElementById('f-sport').value = params.get('sport') || 'football';
  document.getElementById('f-odds').value = params.get('odds') || '';
  document.getElementById('f-stake').value = params.get('stake') || '';
  document.getElementById('f-ev').value = params.get('ev') || '';
  document.getElementById('f-p').value = params.get('p') || '';
  if (document.getElementById('f-league'))
    document.getElementById('f-league').value = params.get('league') || '';

  // Stocker les métadonnées pour les inclure dans features_json
  pendingMeta = {
    event_name: params.get('event_name') || '',
    event_date: params.get('event_date') || '',
    league: params.get('league') || '',
    outcome: params.get('outcome') || '',
  };

  // Ouvrir le formulaire automatiquement
  document.getElementById('bet-form').classList.remove('hidden');
}

function toggleForm() {
  const form = document.getElementById('bet-form');
  form.classList.toggle('hidden');
}

async function recordBet(e) {
  e.preventDefault();
  // features_json embarque event_name + league + outcome pour l'auto-CLV au resolve
  const features = {
    event_name: pendingMeta.event_name || '',
    event_date: pendingMeta.event_date || '',
    league:     pendingMeta.league     || document.getElementById('f-league').value || '',
    outcome:    pendingMeta.outcome    || '',
  };
  const body = {
    strategy: document.getElementById('f-strategy').value,
    market: document.getElementById('f-market').value,
    sport: document.getElementById('f-sport').value,
    odds_taken: parseFloat(document.getElementById('f-odds').value),
    stake: parseFloat(document.getElementById('f-stake').value),
    p_estimated: parseFloat(document.getElementById('f-p').value) || 0.5,
    ev_expected: parseFloat(document.getElementById('f-ev').value) || 0.0,
    league: features.league || null,
    features_json: JSON.stringify(features),
  };

  try {
    const data = await API.post('/api/simulation/record-bet', body);
    if (data.status === 'ok') {
      document.getElementById('bet-form').reset();
      document.getElementById('bet-form').classList.add('hidden');
      loadBets();
    }
  } catch (err) {
    alert('Erreur : ' + (err.message || err));
  }
}

async function loadBets() {
  const strategy = document.getElementById('filter-strategy').value;
  const status = document.getElementById('filter-status').value;
  const loading = document.getElementById('bets-loading');
  const table = document.getElementById('bets-table');
  const empty = document.getElementById('bets-empty');

  loading.classList.remove('hidden');
  table.classList.add('hidden');
  empty.classList.add('hidden');

  try {
    let url = '/api/simulation/bets';
    if (strategy) url += `?strategy=${strategy}`;

    const data = await API.get(url);
    loading.classList.add('hidden');

    let bets = data.data || [];

    if (status === 'open') bets = bets.filter(b => b.result === null || b.result === undefined);
    if (status === 'resolved') bets = bets.filter(b => b.result !== null && b.result !== undefined);

    if (bets.length === 0) {
      empty.classList.remove('hidden');
      return;
    }

    const tbody = document.getElementById('bets-body');
    tbody.innerHTML = '';
    for (const b of bets) {
      const isOpen = b.result === null || b.result === undefined;
      const resultCell = isOpen
        ? `<button class="btn-xs" onclick="openResolveModal(${b.id})">Résoudre</button>`
        : b.result === 1
        ? '<span class="badge positive">Gagné</span>'
        : '<span class="badge negative">Perdu</span>';

      const evRealized = b.ev_realized !== null ? (b.ev_realized * 100).toFixed(1) + '%' : '—';
      const evRealizedClass = b.ev_realized > 0 ? 'text-green' : b.ev_realized < 0 ? 'text-red' : '';

      const impact = b.portfolio_after && b.portfolio_before
        ? (b.portfolio_after - b.portfolio_before).toFixed(2)
        : '—';
      const impactClass = parseFloat(impact) > 0 ? 'text-green' : parseFloat(impact) < 0 ? 'text-red' : '';

      tbody.insertAdjacentHTML('beforeend', `
        <tr>
          <td>${b.created_at?.slice(0, 10) || '—'}</td>
          <td><span class="badge badge-blue">${b.strategy}</span></td>
          <td>${b.market}</td>
          <td>${b.sport}</td>
          <td class="odds-val">${b.odds_taken?.toFixed(2)}</td>
          <td>${b.stake?.toFixed(2)} €</td>
          <td>${b.ev_expected ? (b.ev_expected * 100).toFixed(1) + '%' : '—'}</td>
          <td class="${evRealizedClass}">${evRealized}</td>
          <td>${resultCell}</td>
          <td class="${impactClass} bold">${impact !== '—' ? (parseFloat(impact) > 0 ? '+' : '') + impact + ' €' : '—'}</td>
          <td></td>
        </tr>
      `);
    }
    table.classList.remove('hidden');
  } catch (_) {
    loading.textContent = 'Erreur lors du chargement.';
  }
}

function openResolveModal(betId) {
  currentResolveBetId = betId;
  document.getElementById('resolve-id').textContent = betId;
  document.getElementById('resolve-odds-close').value = '';
  document.getElementById('resolve-modal').classList.remove('hidden');
}

function closeModal() {
  document.getElementById('resolve-modal').classList.add('hidden');
  currentResolveBetId = null;
}

async function submitResolve() {
  if (!currentResolveBetId) return;
  const result = parseInt(document.getElementById('resolve-result').value);
  const oddsCloseRaw = document.getElementById('resolve-odds-close').value.trim();

  // Si vide → on n'envoie pas le param et l'API auto-fetch via Pinnacle
  let url = `/api/simulation/resolve-bet?bet_id=${currentResolveBetId}&result=${result}`;
  if (oddsCloseRaw) {
    const v = parseFloat(oddsCloseRaw);
    if (v > 1.0) url += `&odds_close=${v}`;
  }

  try {
    const res = await API.post(url, {});
    if (res?.odds_close_used) {
      console.log(`CLV calculé avec cote clôture ${res.odds_close_used}`);
    }
    closeModal();
    loadBets();
  } catch (err) {
    alert('Erreur : ' + (err.message || err));
  }
}
