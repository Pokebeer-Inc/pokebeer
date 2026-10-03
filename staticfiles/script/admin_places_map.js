document.addEventListener("DOMContentLoaded", function () {

    const places = JSON.parse(document.getElementById("places-data").textContent);

    const searchInput = document.getElementById("places-search");
    const typeBoxes = Array.from(document.querySelectorAll(".places-type"));
    const statusSelect = document.getElementById("places-status");
    const managersSelect = document.getElementById("places-managers");
    const counter = document.getElementById("places-count");
    const mapElement = document.getElementById("places-map");

    const map = L.map(mapElement).setView([46.6, 2.4], 5);
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
        maxZoom: 19,
        attribution: "&copy; OpenStreetMap"
    }).addTo(map);
    new ResizeObserver(function () { map.invalidateSize(); }).observe(mapElement);

    const layer = L.layerGroup().addTo(map);

    // Seuls les liens http(s) saisis par les gérants sont rendus cliquables
    function safeExternalUrl(value) {
        try {
            const url = new URL(value);
            return url.protocol === "https:" || url.protocol === "http:" ? url.href : null;
        } catch (e) {
            return null;
        }
    }

    // Chemin interne de l'app uniquement (jamais d'URL absolue ni protocole-relative)
    function safeInternalPath(value) {
        return typeof value === "string" && value.startsWith("/") && !value.startsWith("//") ? value : null;
    }

    function addField(list, label, value, href) {
        if (!value) return;
        const row = document.createElement("div");
        const term = document.createElement("dt");
        term.className = "text-xs text-font-subtle-light dark:text-font-subtle-dark";
        term.textContent = label;
        const definition = document.createElement("dd");
        if (href) {
            const link = document.createElement("a");
            link.href = href;
            link.textContent = value;
            link.target = "_blank";
            link.rel = "noopener noreferrer";
            link.className = "text-primary-600 break-all";
            definition.appendChild(link);
        } else {
            definition.textContent = value;
        }
        row.append(term, definition);
        list.appendChild(row);
    }

    function showDetails(place) {
        document.getElementById("place-details-empty").classList.add("hidden");
        document.getElementById("place-details-content").classList.remove("hidden");

        document.getElementById("place-type").textContent = place.type_label;
        document.getElementById("place-name").textContent = place.name;
        document.getElementById("place-description").textContent = place.description || "";

        const status = document.getElementById("place-status");
        status.textContent = place.is_verified
            ? "Vérifié" + (place.verified_at ? " le " + place.verified_at : "")
            : "À vérifier";
        status.className = "place-status mt-2 " + (place.is_verified ? "place-status--verified" : "place-status--pending");

        const fields = document.getElementById("place-fields");
        fields.replaceChildren();
        addField(fields, "Adresse", place.address);
        addField(fields, "Téléphone", place.phone, place.phone ? "tel:" + place.phone.replace(/[^0-9+]/g, "") : null);
        addField(fields, "Email", place.email, place.email ? "mailto:" + encodeURIComponent(place.email).replace("%40", "@") : null);
        addField(fields, "Site web", place.website, safeExternalUrl(place.website));
        addField(fields, "Instagram", place.instagram, safeExternalUrl(place.instagram));
        addField(fields, "Facebook", place.facebook, safeExternalUrl(place.facebook));
        addField(fields, "Gérants", String(place.managers_count));

        const publicLink = document.getElementById("place-public-link");
        const path = safeInternalPath(place.url);
        publicLink.classList.toggle("hidden", !path);
        if (path) publicLink.href = path;
    }

    const markers = places.map(function (place) {
        const marker = L.marker([place.latitude, place.longitude], {
            title: place.name,
            icon: L.divIcon({
                className: "",
                html: '<div class="place-marker place-marker--' + place.type + " place-marker--" +
                      (place.is_verified ? "verified" : "pending") + '"></div>',
                iconSize: [20, 20],
                iconAnchor: [10, 10]
            })
        });
        marker.on("click", function () { showDetails(place); });
        return { place: place, marker: marker, haystack: (place.name + " " + (place.address || "")).toLowerCase() };
    });

    function matches(entry) {
        const place = entry.place;
        const types = typeBoxes.filter(function (box) { return box.checked; }).map(function (box) { return box.value; });
        const query = searchInput.value.trim().toLowerCase();

        if (!types.includes(place.type)) return false;
        if (statusSelect.value === "verified" && !place.is_verified) return false;
        if (statusSelect.value === "pending" && place.is_verified) return false;
        if (managersSelect.value === "with" && place.managers_count === 0) return false;
        if (managersSelect.value === "without" && place.managers_count > 0) return false;
        return !query || entry.haystack.includes(query);
    }

    function update() {
        layer.clearLayers();
        const visible = markers.filter(matches);
        visible.forEach(function (entry) { layer.addLayer(entry.marker); });
        counter.textContent = visible.length;

        if (visible.length) {
            map.fitBounds(visible.map(function (entry) { return entry.marker.getLatLng(); }), { padding: [40, 40], maxZoom: 15 });
        }
    }

    searchInput.addEventListener("input", update);
    [statusSelect, managersSelect].forEach(function (el) { el.addEventListener("change", update); });
    typeBoxes.forEach(function (box) { box.addEventListener("change", update); });

    update();
});
