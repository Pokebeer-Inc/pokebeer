// Position de l'appareil, partagée entre les pages (« Autour de vous », chat) : arrondie à ~1 km, gardée 5 minutes dans l'onglet seulement
// (sessionStorage), jamais enregistrée. Elle ne quitte l'appareil que pour une question de lieux posée à Gaétan, et le serveur ne la garde pas.
(function () {
    const KEY = 'pb-position';
    const MAX_AGE_MS = 5 * 60 * 1000;
    const OPTIONS = { enableHighAccuracy: false, maximumAge: MAX_AGE_MS, timeout: 8000 };
    const round = value => Math.round(value * 100) / 100;

    function remember(lat, lng) {
        const position = { lat: round(lat), lng: round(lng), at: Date.now() };
        try { sessionStorage.setItem(KEY, JSON.stringify(position)); } catch (e) { /* stockage indisponible : pas de partage entre pages */ }
        return { lat: position.lat, lng: position.lng };
    }

    function recall() {
        try {
            const position = JSON.parse(sessionStorage.getItem(KEY));
            if (position && Date.now() - position.at < MAX_AGE_MS && Number.isFinite(position.lat) && Number.isFinite(position.lng)) {
                return { lat: position.lat, lng: position.lng };
            }
        } catch (e) { /* valeur illisible : ignorée */ }
        return null;
    }

    // Lecture avec demande d'autorisation si besoin : { lat, lng } ou { error: 'denied' | 'unavailable' }
    function request() {
        return new Promise(resolve => {
            if (!navigator.geolocation) return resolve({ error: 'unavailable' });
            navigator.geolocation.getCurrentPosition(
                position => resolve(remember(position.coords.latitude, position.coords.longitude)),
                error => resolve({ error: error.code === 1 ? 'denied' : 'unavailable' }),
                OPTIONS,
            );
        });
    }

    async function alreadyGranted() {
        try { return (await navigator.permissions.query({ name: 'geolocation' })).state === 'granted'; } catch (e) { return false; }
    }

    // Sans jamais afficher d'invite : position récente, ou lecture si l'accès est déjà accordé ; null sinon
    async function silent() {
        const known = recall();
        if (known) return known;
        if (!(await alreadyGranted())) return null;
        const position = await request();
        return position.error ? null : position;
    }

    window.PokebeerPosition = { remember, recall, request, silent };
})();
