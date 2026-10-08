// Vérification des doublons pendant la saisie d'une bière : après une pause de frappe (et après un remplissage par le scanner, qui
// déclenche l'événement « input »), le serveur renvoie le panneau des brasseries et bières déjà au catalogue qui ressemblent à la saisie.
// Le panneau est du HTML produit par Django (échappé) : le navigateur n'y insère rien venu de l'utilisateur.
(function () {
    'use strict';

    const DEBOUNCE_MS = 400;
    const panel = document.getElementById('duplicate-panel');
    const nameField = document.getElementById('id_beer-name');
    const breweryField = document.getElementById('id_beer-brewery_name');
    const postalField = document.getElementById('id_beer-brewery_postal_code');
    const cityField = document.getElementById('id_beer-brewery_city');
    if (!panel || !nameField || !breweryField || !postalField || !cityField) return;

    let timer = null;
    let controller = null;

    function schedule() {
        clearTimeout(timer);
        timer = setTimeout(check, DEBOUNCE_MS);
    }

    async function check() {
        if (controller) controller.abort(); // une saisie plus récente rend la réponse précédente inutile
        controller = new AbortController();
        const query = new URLSearchParams({
            name: nameField.value.trim(), brewery: breweryField.value.trim(), postal: postalField.value.trim(), city: cityField.value.trim(),
        });
        try {
            const response = await fetch(panel.dataset.url + '?' + query.toString(), { signal: controller.signal, credentials: 'same-origin' });
            if (!response.ok) return; // quota atteint ou panne : le contrôle du serveur à l'envoi reste entier
            const data = await response.json();
            panel.innerHTML = data.html;
            // Brasserie déjà connue sous un nom très voisin (accents, « Microbrasserie ») : on adopte son nom exact
            if (data.apply_brewery && data.apply_brewery !== breweryField.value) breweryField.value = data.apply_brewery;
        } catch (error) {
            /* annulation ou réseau : rien à afficher, le serveur recontrôle à l'envoi */
        }
    }

    nameField.addEventListener('input', schedule);
    breweryField.addEventListener('input', schedule);
    postalField.addEventListener('input', schedule);
    cityField.addEventListener('input', schedule);
    cityField.addEventListener('change', schedule); // la ville est remplie par postal_code.js sans événement de frappe

    // « Utiliser celle-ci » : la saisie reprend le nom exact de la brasserie existante
    panel.addEventListener('click', event => {
        const button = event.target.closest('[data-use-brewery]');
        if (!button) return;
        breweryField.value = button.dataset.useBrewery;
        check();
    });
})();
