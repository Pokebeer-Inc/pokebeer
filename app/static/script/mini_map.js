document.addEventListener("DOMContentLoaded", function() {
    const mapEl = document.getElementById('place-map');
    if (!mapEl) return;

    const lat = parseFloat(mapEl.getAttribute('data-lat'));
    const lng = parseFloat(mapEl.getAttribute('data-lng'));

    const map = L.map('place-map').setView([lat, lng], 15);

    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        maxZoom: 19,
    }).addTo(map);

    const brownIcon = new L.Icon({
        iconUrl: 'https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-2x-gold.png',
        shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/0.7.7/images/marker-shadow.png',
        iconSize: [25, 41],
        iconAnchor: [12, 41],
        shadowSize: [41, 41]
    });

    L.marker([lat, lng], {icon: brownIcon}).addTo(map);
});