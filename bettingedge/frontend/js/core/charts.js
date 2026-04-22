const COLORS = { A: "#4f8ef7", B: "#2ecc71", C: "#f1c40f" };

function createPerfChart(canvasId, datasets) {
  const ctx = document.getElementById(canvasId).getContext("2d");
  return new Chart(ctx, {
    type: "line",
    data: {
      datasets: datasets.map(d => ({
        label: `Stratégie ${d.strategy}`,
        data: d.points,
        borderColor: COLORS[d.strategy],
        backgroundColor: COLORS[d.strategy] + "20",
        tension: 0.3,
        fill: false,
        pointRadius: 3,
      })),
    },
    options: {
      responsive: true,
      interaction: { mode: "index", intersect: false },
      plugins: { legend: { labels: { color: "#e8eaf0" } } },
      scales: {
        x: { ticks: { color: "#7f8fa6" }, grid: { color: "#2d3245" } },
        y: { ticks: { color: "#7f8fa6" }, grid: { color: "#2d3245" } },
      },
    },
  });
}

function createCalibrationChart(canvasId, data) {
  const ctx = document.getElementById(canvasId).getContext("2d");
  return new Chart(ctx, {
    type: "scatter",
    data: {
      datasets: [
        { label: "Modèle", data: data.points, backgroundColor: "#4f8ef7" },
        { label: "Parfait", data: [{ x: 0, y: 0 }, { x: 1, y: 1 }], type: "line", borderColor: "#7f8fa6", borderDash: [5, 5], pointRadius: 0 },
      ],
    },
    options: {
      scales: {
        x: { title: { display: true, text: "p estimée", color: "#7f8fa6" }, ticks: { color: "#7f8fa6" }, grid: { color: "#2d3245" } },
        y: { title: { display: true, text: "fréquence réelle", color: "#7f8fa6" }, ticks: { color: "#7f8fa6" }, grid: { color: "#2d3245" } },
      },
    },
  });
}
