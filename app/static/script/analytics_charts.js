// Rendu des graphiques d'analytics (ApexCharts), partagé par l'administration (admin_analytics.js) et la page des gérants (pro_analytics.js).
// Un graphique est un conteneur `.analytics-chart` dont `data-spec-id` désigne un <script type="application/json"> (json_script) : les données
// ne sont jamais interprétées comme du HTML. `render(element, { brand: true })` applique les couleurs et le style du site (page des gérants).
window.AnalyticsCharts = (function () {
    "use strict";

    const isDark = document.documentElement.classList.contains("dark");
    const ADMIN = {
        text: isDark ? "#e5e7eb" : "#374151", muted: isDark ? "#9ca3af" : "#6b7280", grid: isDark ? "#374151" : "#e5e7eb",
        palette: ["#2563eb", "#f97316", "#16a34a", "#9333ea", "#dc2626", "#0891b2", "#ca8a04", "#db2777"], neutral: "#9ca3af", font: undefined,
        heat: isDark ? ["#1e3a8a", "#1d4ed8", "#2563eb", "#3b82f6", "#60a5fa"] : ["#dbeafe", "#93c5fd", "#60a5fa", "#2563eb", "#1e40af"],
        heatZero: isDark ? "#374151" : "#e5e7eb", band: "#93c5fd"
    };
    // Thème « beer » du site : ambre pour « vous », gris pour la communauté, cuivre et brun pour le reste
    const BRAND = {
        text: "#333333", muted: "#6b625a", grid: "#e6ddd3",
        palette: ["#d49a06", "#b87e44", "#6b625a", "#eca054", "#8c7b6b", "#333333"], neutral: "#b9b0a4", font: "Montserrat, sans-serif",
        heat: ["#f6e7b8", "#efd06a", "#e3b52a", "#d49a06", "#a87500"], heatZero: "#ece5dc", band: "#e3c27a"
    };

    function readSpec(element) {
        return JSON.parse(document.getElementById(element.dataset.specId).textContent);
    }

    function number(value) {
        return value == null ? "" : Number(value).toLocaleString("fr-FR", { maximumFractionDigits: 2 });
    }

    // La fourchette d'une prévision (deux séries : basse et haute) est dessinée comme une zone ombrée, sous les courbes
    function splitBand(spec) {
        if (!spec.band) return { lines: spec.series, dashed: spec.dashed || [], band: null };
        const low = spec.band[0], high = spec.band[1];
        const lines = spec.series.filter(function (_s, i) { return i !== low && i !== high; });
        const dashed = (spec.dashed || []).filter(function (i) { return i !== low && i !== high; }).map(function (i) {
            return i - (low < i ? 1 : 0) - (high < i ? 1 : 0);
        });
        const band = {
            name: "Fourchette (80 %)", type: "rangeArea",
            data: spec.categories.map(function (category, i) {
                const lo = spec.series[low].data[i], hi = spec.series[high].data[i];
                return { x: category, y: lo == null || hi == null ? null : [lo, hi] };
            })
        };
        return { lines: lines, dashed: dashed, band: band };
    }

    function seriesColors(theme, names) {
        let next = 0;
        return names.map(function (name) {
            if (/communaut/i.test(name)) return theme.neutral;
            return theme.palette[next++ % theme.palette.length];
        });
    }

    function chartOptions(spec, options) {
        const brand = Boolean(options && options.brand);
        const theme = brand ? BRAND : ADMIN;
        const horizontal = spec.kind === "hbar";
        const parts = spec.kind === "line" ? splitBand(spec) : { lines: spec.series, dashed: spec.dashed || [], band: null };
        const height = brand ? (horizontal ? Math.max(200, spec.categories.length * 34 + 60) : 260) : (horizontal ? Math.max(260, spec.categories.length * 32 + 80) : 340);

        const base = {
            chart: {
                type: horizontal ? "bar" : spec.kind,
                height: height,
                stacked: spec.stacked,
                toolbar: { show: false },
                background: "transparent",
                animations: { enabled: false },
                fontFamily: theme.font,
                foreColor: theme.muted
            },
            theme: { mode: !brand && isDark ? "dark" : "light" },
            colors: seriesColors(theme, parts.lines.map(function (s) { return s.name; })),
            series: parts.lines,
            dataLabels: { enabled: horizontal || spec.kind === "donut" || spec.kind === "heatmap", style: { fontSize: "11px" } },
            grid: { borderColor: theme.grid, strokeDashArray: brand ? 3 : 4, xaxis: { lines: { show: false } } },
            tooltip: { theme: !brand && isDark ? "dark" : "light", y: { formatter: number } },
            legend: { labels: { colors: theme.text }, show: parts.lines.length + (parts.band ? 1 : 0) > 1 || spec.kind === "donut", position: brand ? "bottom" : "right", fontSize: "12px", markers: { size: 6 } },
            noData: { text: "Pas encore assez de données", style: { color: theme.muted } }
        };

        if (spec.kind === "donut") {
            // Pour un donut, ApexCharts attend une série plate et des libellés
            const colors = spec.categories.map(function (_c, i) { return theme.palette[i % theme.palette.length]; });
            const donut = { series: spec.series[0].data, labels: spec.categories, colors: colors };
            if (brand) {
                donut.plotOptions = { pie: { donut: { size: "62%", labels: { show: true, total: { show: true, label: "Total", fontSize: "12px", color: theme.muted } } } } };
                donut.dataLabels = { enabled: true, formatter: function (value) { return Math.round(value) + " %"; }, dropShadow: { enabled: false }, style: { fontSize: "11px" } };
                donut.stroke = { width: 2, colors: ["#f7f3f0"] };
            }
            return Object.assign(base, donut);
        }

        base.xaxis = { categories: spec.categories, labels: { style: { colors: theme.muted }, rotate: brand ? 0 : -45, hideOverlappingLabels: true }, axisBorder: { show: false }, axisTicks: { show: false } };
        base.yaxis = { labels: { style: { colors: theme.muted, fontSize: "12px" }, maxWidth: brand ? 140 : 240, formatter: number }, decimalsInFloat: 1 };

        if (horizontal) {
            base.plotOptions = { bar: { horizontal: true, borderRadius: 4, barHeight: brand ? "55%" : "65%" } };
            base.dataLabels.textAnchor = "start";
            base.dataLabels.offsetX = 8;
            base.dataLabels.formatter = number;
            base.yaxis.labels.style.colors = theme.text;
        } else if (spec.kind === "bar") {
            base.plotOptions = { bar: { borderRadius: 4, columnWidth: brand ? "70%" : "70%" } };
        }

        if (spec.kind === "line") {
            const widths = parts.lines.map(function (_s, i) { return i === 0 ? (brand ? 3 : 3) : (brand ? 2 : 3); });
            const dashes = parts.lines.map(function (_s, i) { return parts.dashed.includes(i) ? 6 : (i === 1 && brand ? 3 : 0); });
            base.stroke = { width: widths, curve: "monotoneCubic", dashArray: dashes };
            base.markers = { size: brand ? 0 : 3, hover: { size: 5 } };
            if (parts.band) {
                // Série de zone en premier (dessinée sous les courbes) : les tableaux de style suivent cet ordre
                // ApexCharts lit toutes les séries d'un graphique mixte dans le format de la première (points {x, y}) : les courbes suivent
                base.series = [parts.band].concat(parts.lines.map(function (s) {
                    return { name: s.name, type: "line", data: s.data.map(function (value, i) { return { x: spec.categories[i], y: value }; }) };
                }));
                base.colors = [theme.band].concat(base.colors);
                base.stroke = { width: [0].concat(widths), curve: "monotoneCubic", dashArray: [0].concat(dashes) };
                base.fill = { opacity: [0.18].concat(parts.lines.map(function () { return 1; })) };
                base.markers = { size: 0, hover: { size: 5 } };
            }
        }

        if (spec.kind === "heatmap") {
            // Une case à 0 est « aucune donnée » ou « groupe trop petit, masqué » : grise et sans chiffre, jamais noire
            const max = Math.max(1, ...spec.series.flatMap(function (s) { return s.data.filter(function (v) { return v != null; }); }));
            const ranges = [{ from: 0, to: 0, color: theme.heatZero, name: "Aucun ou masqué" }];
            theme.heat.forEach(function (color, index) {
                ranges.push({ from: index === 0 ? 0.00001 : (max * index) / theme.heat.length, to: (max * (index + 1)) / theme.heat.length, color: color });
            });
            base.plotOptions = { heatmap: { radius: 2, colorScale: { ranges: ranges } } };
            base.dataLabels.formatter = function (value) { return value ? number(value) : ""; };
            base.legend.show = false;
        }
        return base;
    }

    function render(element, options) {
        return new ApexCharts(element, chartOptions(readSpec(element), options)).render();
    }

    return { readSpec: readSpec, render: render };
})();
