document.addEventListener("DOMContentLoaded", function () {

    const readSpec = window.AnalyticsCharts.readSpec;

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
        if (chart) window.AnalyticsCharts.render(chart);

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
