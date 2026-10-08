// Code postal -> ville : saisir un code postal à 5 chiffres propose la ou les communes correspondantes (annuaire officiel, via notre serveur).
// Le serveur revérifie à l'envoi : la ville n'est jamais crue sur parole. Si l'annuaire ne répond pas, la saisie reste possible.
(function () {
    'use strict';

    const DEBOUNCE_MS = 250;
    const FORMAT = /^\d{5}$/;

    document.querySelectorAll('[data-postal-input]').forEach(postal => {
        const group = postal.dataset.postalGroup;
        const city = document.querySelector('[data-city-input][data-postal-group="' + group + '"]');
        const list = document.getElementById('cities-' + group);
        if (!city || !list) return;

        let timer = null;
        let controller = null;

        function show(cities) {
            list.replaceChildren(...cities.map(name => {
                const option = document.createElement('option');
                option.value = name;
                return option;
            }));
        }

        async function lookup() {
            const code = postal.value.trim();
            postal.setCustomValidity('');
            if (!FORMAT.test(code)) { show([]); return; }
            if (controller) controller.abort();
            controller = new AbortController();
            try {
                const response = await fetch(postal.dataset.postalUrl + '?code=' + encodeURIComponent(code), { signal: controller.signal, credentials: 'same-origin' });
                if (!response.ok) return;
                const data = await response.json();
                show(data.cities);
                if (data.available && !data.known) postal.setCustomValidity('Ce code postal est inconnu.');
                const before = city.value;
                if (data.cities.length === 1) city.value = data.cities[0];
                else if (!data.cities.includes(city.value)) city.value = ''; // plusieurs communes : le membre choisit la sienne
                if (city.value !== before) city.dispatchEvent(new Event('change', { bubbles: true }));
            } catch (error) {
                /* annulation ou réseau : le serveur contrôlera à l'envoi */
            }
        }

        postal.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(lookup, DEBOUNCE_MS); });
        if (FORMAT.test(postal.value.trim())) lookup();
    });
})();
