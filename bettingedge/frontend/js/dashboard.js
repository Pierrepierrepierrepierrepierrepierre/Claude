async function loadDashboard() {
  try {
    const data = await API.get("/dashboard");

    // Alerte scraper
    const alert = document.getElementById("scraper-alert");
    if (data.scraper_error) {
      alert.textContent = `⚠ Scraper Betclic en erreur : ${data.scraper_error}`;
      alert.className = "alert error";
    }

    // KPIs par stratégie
    ["A", "B", "C"].forEach(s => {
      const p = data.portfolios?.[s];
      if (!p) return;
      const roi = ((p.capital_current - p.capital_initial) / p.capital_initial * 100).toFixed(2);
      const cls = roi >= 0 ? "positive" : "negative";
      document.getElementById(`kpi-${s.toLowerCase()}`).innerHTML = `
        <h3>Stratégie ${s}</h3>
        <div class="kpi-value ${cls}">${roi}%</div>
        <div class="kpi-meta">ROI · ${p.n_bets} paris</div>
        <div class="kpi-meta">Capital : ${p.capital_current.toFixed(0)}€</div>
        <div class="kpi-meta">CLV moyen : ${(p.clv_mean * 100 || 0).toFixed(1)}% · BS : ${(p.brier_score || 0.25).toFixed(3)}</div>
      `;
    });

    // Courbe de performance
    if (data.series) {
      createPerfChart("perf-chart", data.series);
    }
  } catch (e) {
    console.error("Dashboard error:", e);
  }
}

loadDashboard();
