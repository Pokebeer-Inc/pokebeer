// Statistiques des gérants : graphiques aux couleurs du site, onglet actif visible, largeur des barres de part.
// Les largeurs et couleurs sont posées ici par le DOM (pas de style en ligne dans le gabarit).
document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll(".analytics-chart").forEach(function (chart) {
        window.AnalyticsCharts.render(chart, { brand: true });
    });

    document.querySelectorAll(".pa-bar-fill").forEach(function (fill) {
        fill.style.width = fill.dataset.width + "%";
    });

    const tabs = document.querySelector("[data-pa-tabs]");
    const current = tabs && tabs.querySelector("[aria-current]");
    if (current) tabs.scrollLeft = Math.max(0, current.offsetLeft - 16);
});
