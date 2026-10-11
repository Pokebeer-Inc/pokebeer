// Choix de dégustations d'un carnet : recherche, compteur, « tout sélectionner » (parmi les lignes visibles), « tout effacer ».
// Délégation d'événements : fonctionne pour toutes les fenêtres de la page. Rien n'est inséré comme HTML.
(function () {
    // Sans accents ni majuscules : « Pêche » trouve « peche »
    const normalize = text => text.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase().trim();
    const rowsOf = picker => Array.from(picker.querySelectorAll('[data-picker-item]'));

    function updateCount(picker) {
        picker.querySelector('[data-picker-count]').textContent = picker.querySelectorAll('[data-picker-item] input:checked').length;
    }

    function filter(picker) {
        const query = normalize(picker.querySelector('[data-picker-search]').value);
        let visible = 0;
        rowsOf(picker).forEach(row => {
            const match = !query || normalize(row.dataset.search || '').includes(query);
            row.hidden = !match;
            if (match) visible += 1;
        });
        picker.querySelector('[data-picker-empty]').hidden = visible > 0;
    }

    document.addEventListener('input', event => {
        const picker = event.target.closest('[data-picker]');
        if (picker && event.target.matches('[data-picker-search]')) filter(picker);
    });

    document.addEventListener('change', event => {
        const picker = event.target.closest('[data-picker]');
        if (picker && event.target.matches('[data-picker-item] input')) updateCount(picker);
    });

    document.addEventListener('click', event => {
        const all = event.target.closest('[data-picker-all]');
        const none = event.target.closest('[data-picker-none]');
        const picker = (all || none)?.closest('[data-picker]');
        if (!picker) return;
        rowsOf(picker).forEach(row => {
            if (all && !row.hidden) row.querySelector('input').checked = true;
            if (none) row.querySelector('input').checked = false;
        });
        updateCount(picker);
    });

    // Entrée dans la recherche filtre sans envoyer le formulaire
    document.addEventListener('keydown', event => {
        if (event.key === 'Enter' && event.target.matches && event.target.matches('[data-picker-search]')) event.preventDefault();
    });
})();
