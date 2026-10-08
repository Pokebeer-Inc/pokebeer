// Onglet « Près de moi » : les lieux sont classés par distance dans le navigateur.
// La position n'est jamais envoyée, enregistrée ni placée dans une adresse : elle ne sert qu'à ce calcul, puis disparaît avec la page.
(function () {
    const PAGE = 15;
    const EARTH_RADIUS_M = 6371008.8;
    let directory = null; // une seule requête par visite de la page
    let current = null;   // l'onglet affiché (celui-ci est remplacé quand on change d'onglet)

    const rad = degrees => degrees * Math.PI / 180;

    // Distance en mètres entre deux points (formule de haversine)
    function distance(lat1, lng1, lat2, lng2) {
        const dLat = rad(lat2 - lat1);
        const dLng = rad(lng2 - lng1);
        const a = Math.sin(dLat / 2) ** 2 + Math.cos(rad(lat1)) * Math.cos(rad(lat2)) * Math.sin(dLng / 2) ** 2;
        return 2 * EARTH_RADIUS_M * Math.asin(Math.min(1, Math.sqrt(a)));
    }

    function format(meters) {
        if (meters < 1000) return Math.max(10, Math.round(meters / 10) * 10) + ' m';
        if (meters < 100000) return (meters / 1000).toFixed(meters < 10000 ? 1 : 0).replace('.', ',') + ' km';
        return '100+ km';
    }

    const normalize = text => (text || '').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '');

    // Seul un chemin du site est suivi : jamais une adresse absolue ni « //hôte »
    const safePath = url => typeof url === 'string' && url.startsWith('/') && !url.startsWith('//') ? url : '#';

    // Photo : uniquement une adresse HTTPS ou un chemin du site
    const safeImage = url => typeof url === 'string' && (url.startsWith('https://') || safePath(url) !== '#') ? url : null;

    // Remplit un modèle de carte (même gabarit que les cartes rendues par le serveur) ; le texte passe toujours par textContent
    function card(template, place, meters) {
        const item = template.content.firstElementChild.cloneNode(true);
        item.href = safePath(place.url);
        const image = safeImage(place.image);
        const photo = item.querySelector('[data-image]');
        if (image) photo.src = image;
        photo.classList.toggle('hidden', !image);
        item.querySelector('[data-placeholder]').classList.toggle('hidden', Boolean(image));
        item.querySelector('[data-name]').textContent = place.name;
        item.querySelector('[data-address]').textContent = place.address || '';
        item.querySelector('[data-kind-label]').textContent = place.kind_label;
        item.querySelector('[data-verified]').classList.toggle('hidden', !place.verified);
        const distanceBadge = item.querySelector('[data-distance]');
        distanceBadge.textContent = format(meters);
        distanceBadge.classList.remove('hidden');
        return item;
    }

    function loadDirectory(url) {
        if (!directory) {
            directory = fetch(url, { credentials: 'same-origin' })
                .then(res => { if (!res.ok) throw new Error('Erreur réseau'); return res.json(); })
                .then(data => Array.isArray(data.places) ? data.places : [])
                .catch(error => { directory = null; throw error; });
        }
        return directory;
    }

    function init(scope) {
        const root = scope.querySelector('[data-nearby]');
        current = null;
        if (!root) return;

        const status = root.querySelector('[data-nearby-status]');
        const list = root.querySelector('[data-nearby-list]');
        const more = root.querySelector('[data-nearby-more]');
        const retry = root.querySelector('[data-nearby-retry]');
        const cardTemplate = root.querySelector('template[data-nearby-row]');
        const state = { kind: '', shown: PAGE, places: null, position: null };

        function visible() {
            const words = normalize(document.getElementById('search-input').value).split(/\s+/).filter(Boolean);
            return state.places
                .filter(place => !state.kind || place.kind === state.kind)
                .filter(place => { const text = normalize(place.name + ' ' + place.address); return words.every(word => text.includes(word)); });
        }

        function render() {
            if (!state.places || !state.position) return;
            const { latitude, longitude } = state.position;
            const ranked = visible()
                .filter(place => Number.isFinite(place.lat) && Number.isFinite(place.lng))
                .map(place => ({ place, meters: distance(latitude, longitude, place.lat, place.lng) }))
                .sort((a, b) => a.meters - b.meters);
            list.replaceChildren();
            ranked.slice(0, state.shown).forEach(({ place, meters }) => list.appendChild(card(cardTemplate, place, meters)));
            more.classList.toggle('hidden', ranked.length <= state.shown);
            status.textContent = ranked.length ? '' : 'Aucun lieu localisé ne correspond.';
        }

        function fail(message) {
            status.textContent = message;
            retry.classList.remove('hidden');
        }

        function locate() {
            retry.classList.add('hidden');
            status.textContent = 'Recherche de votre position…';
            if (!navigator.geolocation) return fail("La localisation n'est pas disponible sur cet appareil.");
            navigator.geolocation.getCurrentPosition(position => {
                state.position = { latitude: position.coords.latitude, longitude: position.coords.longitude };
                loadDirectory(root.dataset.url)
                    .then(places => { state.places = places; render(); })
                    .catch(() => fail('Impossible de charger les lieux. Réessayez.'));
            }, error => {
                fail(error.code === 1
                    ? "Position refusée : autorisez la localisation pour Pokebeer dans les réglages, puis réessayez."
                    : "Position introuvable. Réessayez.");
            }, { enableHighAccuracy: false, maximumAge: 60000, timeout: 15000 });
        }

        root.querySelectorAll('[data-nearby-kind]').forEach(button => button.addEventListener('click', () => {
            state.kind = button.dataset.nearbyKind;
            state.shown = PAGE;
            root.querySelectorAll('[data-nearby-kind]').forEach(other => {
                const active = other === button;
                other.setAttribute('aria-pressed', String(active));
                other.classList.toggle('btn-primary', active);
                other.classList.toggle('btn-outline', !active);
            });
            render();
        }));
        more.addEventListener('click', () => { state.shown += PAGE; render(); });
        retry.addEventListener('click', locate);

        current = { render: () => { state.shown = PAGE; render(); } };
        locate();
    }

    // La saisie de la barre filtre la liste sur place (sans nouvelle requête ni nouvelle position)
    document.addEventListener('search:filter', () => { if (current) current.render(); });
    window.initNearby = init;
})();
