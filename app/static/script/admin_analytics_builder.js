// Assistant de création d'une tuile : n'affiche que les choix compatibles. Simple confort : le serveur revalide tout.
document.addEventListener("DOMContentLoaded", function () {
    const catalog = JSON.parse(document.getElementById("builder-catalog").textContent);

    const dataset = document.getElementById("id_dataset");
    const chart = document.getElementById("id_chart");
    const dimension = document.getElementById("id_dimension");
    const measureBoxes = Array.from(document.querySelectorAll("#measures-box input[type=checkbox]"));
    const fields = {
        dimension: document.getElementById("field-dimension"),
        limit: document.getElementById("field-limit"),
        sort: document.getElementById("field-sort"),
        trend: document.getElementById("field-trend")
    };
    const hint = document.getElementById("builder-hint");

    const HINTS = {
        kpi: "Valeur unique : une seule mesure, sans regroupement.",
        table: "Tableau : un regroupement et jusqu'à 4 mesures.",
        bar: "Barres : un regroupement et jusqu'à 4 mesures comparées.",
        hbar: "Barres horizontales : pratique pour de longs libellés (styles, brasseries).",
        line: "Courbe : regroupement par période ; activez la tendance pour une moyenne mobile et une prévision.",
        donut: "Anneau : une seule mesure répartie selon le regroupement."
    };

    function current() { return catalog[dataset.value]; }

    function kindOf(dimensionKey) {
        const found = current().dimensions.find(function (d) { return d.key === dimensionKey; });
        return found ? found.kind : null;
    }

    function setOptionVisible(option, visible) {
        option.hidden = !visible;
        option.disabled = !visible;
    }

    function refresh() {
        const data = current();
        const dimensionKeys = data.dimensions.map(function (d) { return d.key; });
        const measureKeys = data.measures.map(function (m) { return m.key; });
        const labelOf = Object.fromEntries(data.measures.map(function (m) { return [m.key, m.label]; }));

        // Regrouper par : seulement les dimensions du jeu de données (et « Période » imposée pour une courbe)
        Array.from(dimension.options).forEach(function (option) {
            const allowed = option.value === "" || dimensionKeys.includes(option.value);
            setOptionVisible(option, allowed && (chart.value === "kpi" ? option.value === "" : option.value !== "" || chart.value === "kpi"));
        });
        if (chart.value === "line") {
            Array.from(dimension.options).forEach(function (option) { if (option.value && kindOf(option.value) !== "time") setOptionVisible(option, false); });
        }
        if (dimension.selectedOptions[0] && dimension.selectedOptions[0].disabled) {
            const first = Array.from(dimension.options).find(function (o) { return !o.disabled; });
            dimension.value = chart.value === "kpi" ? "" : (first ? first.value : "");
        }
        if (chart.value === "line" && kindOf("time")) dimension.value = "time";

        // Mesures : celles du jeu de données, avec leur libellé propre ; une seule pour KPI/anneau/courbe tendance
        const single = chart.value === "kpi" || chart.value === "donut";
        measureBoxes.forEach(function (box) {
            const allowed = measureKeys.includes(box.value);
            box.closest("label").hidden = !allowed;
            if (!allowed) box.checked = false;
            if (allowed) box.parentElement.querySelector("span").textContent = labelOf[box.value];
        });
        if (single) {
            let seen = false;
            measureBoxes.forEach(function (box) { if (box.checked && !seen) { seen = true; } else if (box.checked) { box.checked = false; } });
        }
        if (!measureBoxes.some(function (box) { return box.checked; })) {
            const first = measureBoxes.find(function (box) { return measureKeys.includes(box.value); });
            if (first) first.checked = true;
        }

        const kind = kindOf(dimension.value);
        fields.dimension.hidden = chart.value === "kpi";
        fields.limit.hidden = fields.sort.hidden = chart.value === "kpi" || kind !== "category";
        fields.trend.hidden = chart.value !== "line";
        if (chart.value !== "line") fields.trend.querySelector("input").checked = false;
        hint.textContent = HINTS[chart.value] || "";
    }

    // Courbe : réservée aux jeux de données qui ont une dimension « Période »
    function refreshChartOptions() {
        const hasTime = Boolean(kindOf("time"));
        Array.from(chart.options).forEach(function (option) { if (option.value === "line") setOptionVisible(option, hasTime); });
        if (chart.selectedOptions[0] && chart.selectedOptions[0].disabled) chart.value = "table";
    }

    // Une seule case cochée pour KPI/anneau
    document.getElementById("measures-box").addEventListener("change", function (event) {
        if ((chart.value === "kpi" || chart.value === "donut") && event.target.checked) {
            measureBoxes.forEach(function (box) { if (box !== event.target) box.checked = false; });
        }
    });

    dataset.addEventListener("change", function () { refreshChartOptions(); refresh(); });
    chart.addEventListener("change", refresh);
    dimension.addEventListener("change", refresh);

    refreshChartOptions();
    refresh();
});
