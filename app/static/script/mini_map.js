document.addEventListener("DOMContentLoaded", function() {
    const mapEl = document.getElementById('place-map');
    if (!mapEl) return;

    const lat = parseFloat(mapEl.getAttribute('data-lat'));
    const lng = parseFloat(mapEl.getAttribute('data-lng'));

    const map = L.map('place-map').setView([lat, lng], 15);

    PokebeerBasemap.addTo(map);

    // Même repère que sur la grande carte : jaune pour un bar, orange pour une brasserie
    L.marker([lat, lng], { icon: window.PokebeerPins.forPlace(mapEl.getAttribute('data-kind')), keyboard: false }).addTo(map);
});
