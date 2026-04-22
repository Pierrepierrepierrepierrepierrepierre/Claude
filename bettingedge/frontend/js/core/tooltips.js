const TOOLTIPS = {
  ev:          { short: "Espérance de gain par unité misée. EV > 0 = pari intéressant.", anchor: "ev" },
  vig:         { short: "Marge du bookmaker. Rend l'EV négatif en moyenne.", anchor: "vig" },
  value_bet:   { short: "Pari où notre probabilité estimée dépasse celle encodée dans la cote.", anchor: "value-bet" },
  kelly:       { short: "Formule de mise optimale selon l'edge. On utilise Kelly × 0.25.", anchor: "kelly" },
  clv:         { short: "Ratio cote prise / cote de clôture. CLV > 0 = edge prouvé.", anchor: "clv" },
  devig:       { short: "Extraction de la probabilité réelle depuis une cote bookmaker.", anchor: "devig" },
  brier:       { short: "Mesure d'erreur du modèle de probabilité. Plus bas = meilleur.", anchor: "brier" },
  dixon_coles: { short: "Modèle Poisson corrigé pour les faibles scores (0-0, 1-0...).", anchor: "dixon-coles" },
  drawdown:    { short: "Perte maximale sur une période donnée.", anchor: "drawdown" },
  rf:          { short: "Facteur Risque composite [0-1]. Pondère la mise recommandée.", anchor: "rf" },
  sharp:       { short: "Parieur professionnel dont les mises font bouger les cotes.", anchor: "sharp" },
};

document.addEventListener("DOMContentLoaded", () => {
  let popup = null;

  document.querySelectorAll("[data-tooltip]").forEach(el => {
    const key = el.dataset.tooltip;
    const def = TOOLTIPS[key];
    if (!def) return;

    el.classList.add("tooltip-trigger");
    el.textContent = el.textContent || "?";

    el.addEventListener("mouseenter", e => {
      popup = document.createElement("div");
      popup.className = "tooltip-popup";
      popup.innerHTML = `${def.short} <br><a href="/docs#${def.anchor}">En savoir plus →</a>`;
      document.body.appendChild(popup);
      const r = el.getBoundingClientRect();
      popup.style.left = `${r.left + window.scrollX}px`;
      popup.style.top  = `${r.bottom + window.scrollY + 6}px`;
    });

    el.addEventListener("mouseleave", () => {
      if (popup) { popup.remove(); popup = null; }
    });
  });
});
