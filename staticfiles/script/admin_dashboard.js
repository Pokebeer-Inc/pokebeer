document.addEventListener("DOMContentLoaded", function () {

    const rawData = JSON.parse(
        document.getElementById("beer-style-data").textContent
    );

    const isDark = document.documentElement.classList.contains("dark");
    const textColor = isDark ? "#e5e7eb" : "#374151";
    const mutedColor = isDark ? "#9ca3af" : "#6b7280";
    const gridColor = isDark ? "#374151" : "#e5e7eb";

    const ROW_HEIGHT = 34;

    const searchInput = document.getElementById("styleSearch");
    const limitSelect = document.getElementById("styleLimit");
    const minInput = document.getElementById("styleMin");
    const splitSelect = document.getElementById("styleSplit");

    // Les styles composés ("IPA, NEIPA / Hazy") comptent pour chacun de leurs styles
    function aggregate(split) {
        const totals = new Map();
        rawData.forEach(function (item) {
            const names = split
                ? item.style.split(",").map(function (s) { return s.trim(); }).filter(Boolean)
                : [item.style];
            names.forEach(function (name) {
                totals.set(name, (totals.get(name) || 0) + item.nb_bieres);
            });
        });
        return Array.from(totals, function (entry) {
            return { style: entry[0], nb_bieres: entry[1] };
        });
    }

    function filteredData() {
        const query = searchInput.value.trim().toLowerCase();
        const min = Math.max(1, parseInt(minInput.value, 10) || 1);
        const limit = parseInt(limitSelect.value, 10);

        const rows = aggregate(splitSelect.value === "split")
            .filter(function (row) {
                return row.nb_bieres >= min && row.style.toLowerCase().includes(query);
            })
            .sort(function (a, b) {
                return b.nb_bieres - a.nb_bieres || a.style.localeCompare(b.style, "fr");
            });

        return limit > 0 ? rows.slice(0, limit) : rows;
    }

    const chart = new ApexCharts(document.querySelector("#beerStyleChart"), {

        chart: {
            type: "bar",
            height: 300,
            toolbar: { show: false },
            background: "transparent",
            animations: { enabled: false }
        },

        theme: { mode: isDark ? "dark" : "light" },

        series: [],
        noData: {
            text: "Aucun style ne correspond aux filtres",
            style: { color: mutedColor }
        },

        plotOptions: {
            bar: {
                horizontal: true,
                borderRadius: 4,
                barHeight: "65%",
                dataLabels: { position: "top" }
            }
        },

        // Valeur affichée au bout de la barre, jamais par-dessus
        dataLabels: {
            enabled: true,
            textAnchor: "start",
            offsetX: 8,
            style: { colors: [textColor], fontSize: "12px" }
        },

        xaxis: {
            labels: { style: { colors: mutedColor }, formatter: function (v) { return Math.round(v); } },
            title: { text: "Nombre de bières", style: { color: textColor } },
            axisBorder: { color: gridColor },
            axisTicks: { color: gridColor },
            tickAmount: undefined,
            decimalsInFloat: 0
        },

        yaxis: {
            // Pas de troncature : la place des libellés est réservée
            labels: { style: { colors: textColor, fontSize: "12px" }, maxWidth: 260 }
        },

        grid: { borderColor: gridColor, strokeDashArray: 4 },

        tooltip: {
            theme: isDark ? "dark" : "light",
            y: {
                formatter: function (value) {
                    return value + " bière" + (value > 1 ? "s" : "");
                }
            }
        }
    });

    function update() {
        const rows = filteredData();
        chart.updateOptions({
            chart: { height: Math.max(200, rows.length * ROW_HEIGHT + 90) },
            series: [{ name: "Nombre de bières", data: rows.map(function (r) { return r.nb_bieres; }) }],
            xaxis: { categories: rows.map(function (r) { return r.style; }) }
        });
    }

    [searchInput, minInput].forEach(function (el) { el.addEventListener("input", update); });
    [limitSelect, splitSelect].forEach(function (el) { el.addEventListener("change", update); });

    chart.render().then(update);
});
