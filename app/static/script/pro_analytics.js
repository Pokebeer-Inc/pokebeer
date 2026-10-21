// Statistiques des gérants : dessine chaque graphique de la page (le rendu est partagé avec l'administration, voir analytics_charts.js).
document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll(".analytics-chart").forEach(function (chart) {
        window.AnalyticsCharts.render(chart);
    });
});
