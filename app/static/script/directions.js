// Boutons « Y aller » et adresses cliquables (partials/directions_button.html, place_header.html) : le lien pointe vers Google Maps (nouvel onglet) ;
// sur iPhone, iPad et Mac tactile on lui substitue Plans, au moment du toucher. Sans JavaScript, le lien Google Maps reste valable.
(function () {
    const APPLE_MAPS_PREFIX = 'https://maps.apple.com/';

    const isAppleTouchDevice = () => /iPad|iPhone|iPod/.test(navigator.userAgent)
        || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);  // iPadOS se présente comme un Mac

    // Phase de capture : les bulles de la carte arrêtent la propagation des clics avant qu'ils n'atteignent le document
    document.addEventListener('click', event => {
        const link = event.target.closest('a[data-apple-url]');
        if (!link || !isAppleTouchDevice()) return;
        const url = link.dataset.appleUrl;
        if (url.startsWith(APPLE_MAPS_PREFIX)) link.href = url;  // jamais une autre adresse que Plans
    }, true);
})();
