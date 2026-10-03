document.addEventListener("DOMContentLoaded", function () {

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
            base.plotOptions = { heatmap: { colorScale: { ranges: [] } } };
            base.colors = ["#2563eb"];
        }
        return base;
    }

    // --- Rendu paresseux : une tuile masquée n'a pas de largeur, on ne dessine qu'à l'affichage ---
    const rendered = new WeakSet();

    function renderTile(tile) {
        if (rendered.has(tile)) {
            const map = tile._leafletMap;
            if (map) map.invalidateSize();
            return;
        }
        rendered.add(tile);

        const chart = tile.querySelector(".analytics-chart");
        if (chart) new ApexCharts(chart, chartOptions(readSpec(chart))).render();

        const mapElement = tile.querySelector(".analytics-map");
        if (mapElement) renderMap(tile, mapElement);
    }

    // Cartes : tooltips construits en DOM (textContent) ; aucune donnée n'est interprétée comme du HTML
    function renderMap(tile, element) {
        const spec = readSpec(element);
        const map = L.map(element).setView([46.6, 2.4], 5);
        tile._leafletMap = map;
        L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 19, attribution: "&copy; OpenStreetMap" }).addTo(map);

        const bounds = [];
        spec.points.forEach(function (point) {
            const marker = L.circleMarker([point.lat, point.lng], {
                radius: point.radius, color: point.color, fillColor: point.color, fillOpacity: 0.35, weight: 2
            }).addTo(map);
            const content = document.createElement("div");
            point.lines.forEach(function (line) {
                const row = document.createElement("div");
                row.textContent = line;
                content.appendChild(row);
            });
            marker.bindTooltip(content);
            bounds.push([point.lat, point.lng]);
        });
        if (bounds.length) map.fitBounds(bounds, { padding: [30, 30], maxZoom: 11 });
        new ResizeObserver(function () { map.invalidateSize(); }).observe(element);
    }

    // --- Disposition : déplacer, masquer, restaurer, mémoriser ---
    const grid = document.getElementById("analytics-grid");
    const status = document.getElementById("analytics-save-status");
    const panel = document.getElementById("analytics-hidden-panel");
    const hiddenList = document.getElementById("analytics-hidden-list");
    const hiddenCount = document.getElementById("analytics-hidden-count");

    function tiles() { return Array.from(grid.querySelectorAll(".analytics-tile")); }

    function showStatus(text) { status.textContent = text; }

    let saveTimer;
    function save(payload) {
        clearTimeout(saveTimer);
        showStatus("Enregistrement…");
        saveTimer = setTimeout(function () {
            fetch(grid.dataset.layoutUrl, {
                method: "POST",
                headers: { "Content-Type": "application/json", "X-CSRFToken": grid.dataset.csrf },
                credentials: "same-origin",
                body: JSON.stringify(payload || currentLayout())
            }).then(function (response) {
                showStatus(response.ok ? "Disposition enregistrée" : "Échec de l'enregistrement");
            }).catch(function () { showStatus("Échec de l'enregistrement"); });
        }, 400);
    }

    function currentLayout() {
        return {
            order: tiles().map(function (tile) { return tile.dataset.tileId; }),
            hidden: tiles().filter(function (tile) { return tile.hidden; }).map(function (tile) { return tile.dataset.tileId; })
        };
    }

    function refreshHiddenPanel() {
        const hidden = tiles().filter(function (tile) { return tile.hidden; });
        hiddenList.replaceChildren();
        hidden.forEach(function (tile) {
            const item = document.createElement("li");
            const label = document.createElement("span");
            label.textContent = tile.dataset.tileTitle;
            const button = document.createElement("button");
            button.type = "button";
            button.className = "analytics-link-button";
            button.textContent = "Afficher";
            button.addEventListener("click", function () { setHidden(tile, false); });
            item.append(label, button);
            hiddenList.appendChild(item);
        });
        hiddenCount.textContent = hidden.length;
        panel.hidden = hidden.length === 0;
    }

    function setHidden(tile, hide) {
        tile.hidden = hide;
        if (!hide) renderTile(tile);
        refreshHiddenPanel();
        save();
    }

    // Boutons de chaque tuile (délégation)
    grid.addEventListener("click", function (event) {
        const button = event.target.closest(".analytics-action");
        if (!button) return;
        const tile = button.closest(".analytics-tile");
        if (button.dataset.action === "hide") setHidden(tile, true);
        if (button.dataset.action === "top") {
            grid.insertBefore(tile, grid.firstElementChild);
            tile.scrollIntoView({ behavior: "smooth", block: "nearest" });
            save();
        }
    });

    // Glisser-déposer natif : seule la poignée active le déplacement (le texte des tuiles reste sélectionnable)
    let dragged = null;
    grid.addEventListener("mousedown", function (event) {
        const tile = event.target.closest(".analytics-tile");
        if (tile) tile.draggable = Boolean(event.target.closest(".analytics-handle"));
    });
    grid.addEventListener("dragstart", function (event) {
        dragged = event.target.closest(".analytics-tile");
        if (!dragged || !dragged.draggable) return event.preventDefault();
        dragged.classList.add("is-dragging");
        event.dataTransfer.effectAllowed = "move";
        event.dataTransfer.setData("text/plain", dragged.dataset.tileId);
    });
    grid.addEventListener("dragover", function (event) {
        if (!dragged) return;
        event.preventDefault();
        const target = event.target.closest(".analytics-tile");
        if (!target || target === dragged || target.hidden) return;
        const box = target.getBoundingClientRect();
        const after = (event.clientY - box.top) / box.height > 0.5 && (event.clientX - box.left) / box.width > 0.5;
        grid.insertBefore(dragged, after ? target.nextElementSibling : target);
    });
    grid.addEventListener("dragend", function () {
        if (!dragged) return;
        dragged.classList.remove("is-dragging");
        dragged.draggable = false;
        dragged = null;
        tiles().forEach(function (tile) { if (!tile.hidden) renderTile(tile); });
        save();
    });

    document.getElementById("analytics-reset").addEventListener("click", function () {
        if (!window.confirm("Rétablir la disposition par défaut de cette page ?")) return;
        save({ order: [], hidden: [] });
        window.setTimeout(function () { window.location.reload(); }, 600);
    });

    tiles().forEach(function (tile) { if (!tile.hidden) renderTile(tile); });
    refreshHiddenPanel();
});
