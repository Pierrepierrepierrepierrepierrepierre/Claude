let perfChart = null;

document.addEventListener('DOMContentLoaded', () => {
  initTooltips();
  loadDashboard();
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

function renderScraperTable(statuses) {
  if (!statuses) return;
  const tbody = document.getElementById('scraper-body');
  tbody.innerHTML = '';
  for (const [name, s] of Object.entries(statuses)) {
    const badge = s.status === 'ok'
      ? '<span class="badge positive">OK</span>'
      : s.status === 'jamais'
      ? '<span class="badge neutral">Jamais</span>'
      : '<span class="badge negative">' + s.status + '</span>';
    tbody.insertAdjacentHTML('beforeend', `
      <tr>
        <td><strong>${name}</strong></td>
        <td>${s.ran_at ? s.ran_at.slice(0, 16).replace('T', ' ') : '—'}</td>
        <td>${badge}</td>
        <td class="text-muted" style="font-size:0.8rem">${s.message || ''}</td>
        <td>
          <button class="btn-xs" onclick="runScraper('${name}')">Lancer</button>
        </td>
      </tr>
    `);
  }
}

async function runScraper(name) {
  try {
    await API.post(`/api/scraper/run?scraper=${name}`, {});
    setTimeout(loadDashboard, 2000);
  } catch (e) {
    alert('Erreur : ' + e.message);
  }
}
