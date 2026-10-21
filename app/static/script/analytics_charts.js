// Rendu des graphiques d'analytics (ApexCharts), partagé par l'administration (admin_analytics.js) et la page des gérants (pro_analytics.js).
// Un graphique est un conteneur `.analytics-chart` dont `data-spec-id` désigne un <script type="application/json"> (json_script) : les données
// ne sont jamais interprétées comme du HTML.
window.AnalyticsCharts = (function () {
    "use strict";

    const isDark = document.documentElement.classList.contains("dark");
    const textColor = isDark ? "#e5e7eb" : "#374151";
    const mutedColor = isDark ? "#9ca3af" : "#6b7280";
    const gridColor = isDark ? "#374151" : "#e5e7eb";
    const PALETTE = ["#2563eb", "#f97316", "#16a34a", "#9333ea", "#dc2626", "#0891b2", "#ca8a04", "#db2777"];

    function readSpec(element) {
        return JSON.parse(document.getElementById(element.dataset.specId).textContent);
    }

    function chartOptions(spec) {
        const horizontal = spec.kind === "hbar";
        const base = {
            chart: {
                type: spec.kind === "hbar" ? "bar" : spec.kind,
                height: horizontal ? Math.max(260, spec.categories.length * 32 + 80) : 340,
                stacked: spec.stacked,
                toolbar: { show: false },
                background: "transparent",
                animations: { enabled: false }
            },
            theme: { mode: isDark ? "dark" : "light" },
            colors: PALETTE,
            series: spec.series,
            dataLabels: { enabled: horizontal || spec.kind === "donut" || spec.kind === "heatmap", style: { fontSize: "11px" } },
            grid: { borderColor: gridColor, strokeDashArray: 4 },
            tooltip: { theme: isDark ? "dark" : "light" },
            legend: { labels: { colors: textColor }, show: spec.series.length > 1 || spec.kind === "donut" },
            noData: { text: "Pas encore assez de données", style: { color: mutedColor } }
        };

        if (spec.kind === "donut") {
            // Pour un donut, ApexCharts attend une série plate et des libellés
            return Object.assign(base, { series: spec.series[0].data, labels: spec.categories });
        }

        base.xaxis = { categories: spec.categories, labels: { style: { colors: mutedColor }, rotate: -45, hideOverlappingLabels: true } };
        base.yaxis = { labels: { style: { colors: mutedColor, fontSize: "12px" }, maxWidth: 240 }, decimalsInFloat: 1 };

        if (horizontal) {
            base.plotOptions = { bar: { horizontal: true, borderRadius: 4, barHeight: "65%" } };
            base.dataLabels.textAnchor = "start";
            base.dataLabels.offsetX = 8;
            base.yaxis.labels.style.colors = textColor;
        }
        if (spec.kind === "line") {
            base.stroke = { width: spec.series.map(function () { return 3; }), curve: "smooth", dashArray: spec.series.map(function (_s, i) { return spec.dashed.includes(i) ? 6 : 0; }) };
            base.markers = { size: 3 };
        }
        if (spec.kind === "heatmap") {
            // Une case à 0 est « aucune donnée » ou « groupe trop petit, masqué » : grise et sans chiffre, jamais noire
            const max = Math.max(1, ...spec.series.flatMap(function (s) { return s.data.filter(function (v) { return v != null; }); }));
            const shades = isDark ? ["#1e3a8a", "#1d4ed8", "#2563eb", "#3b82f6", "#60a5fa"] : ["#dbeafe", "#93c5fd", "#60a5fa", "#2563eb", "#1e40af"];
            const ranges = [{ from: 0, to: 0, color: isDark ? "#374151" : "#e5e7eb", name: "Aucun ou masqué" }];
            shades.forEach(function (color, index) {
                ranges.push({ from: index === 0 ? 0.00001 : (max * index) / shades.length, to: (max * (index + 1)) / shades.length, color: color });
            });
            base.plotOptions = { heatmap: { radius: 2, colorScale: { ranges: ranges } } };
            base.dataLabels.formatter = function (value) { return value ? value : ""; };
            base.legend.show = false;
        }
        return base;
    }

    function render(element) {
        return new ApexCharts(element, chartOptions(readSpec(element))).render();
    }

    return { readSpec: readSpec, render: render };
})();
