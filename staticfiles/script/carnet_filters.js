// Page d'un carnet : feuille « Filtrer » (tri, note, alcool, amertume, style).
// La liste est rafraîchie par htmx dès qu'un champ du formulaire change : ce script ne fait que piloter la feuille et remettre des champs à zéro.
(function () {
    const form = document.getElementById('carnet-form');
    const sheet = document.getElementById('filters-sheet');
    if (!form || !sheet) return;

    const refresh = () => form.dispatchEvent(new Event('change', { bubbles: true }));
    const open = () => { if (!sheet.open) sheet.showModal(); };
    const close = () => { if (sheet.open) sheet.close(); };

    // Boutons d'ouverture et de fermeture de la feuille
    document.addEventListener('click', event => {
        if (event.target.closest('[data-open-filters]')) open();
        if (event.target.closest('[data-close-filters]')) close();
    });

    function clearRating() {
        const low = document.getElementById('rating_min');
        const high = document.getElementById('rating_max');
        if (!low || !high) return;
        low.value = 0;
        high.value = 10;
        low.dispatchEvent(new Event('input', { bubbles: true })); // met à jour la barre et l'affichage de la fourchette
    }

    function clearFilter(name) {
        if (name === 'q') {
            form.elements.q.value = '';
        } else if (name === 'rating') {
            clearRating();
        } else if (name === 'style') {
            if (form.elements.style) form.elements.style.value = '';
        } else {
            form.querySelectorAll('input[name="' + name + '"]').forEach(input => { input.checked = input.value === ''; });
        }
    }

    // « Réinitialiser » : tous les filtres et le tri par défaut (la recherche texte reste)
    const reset = document.getElementById('filters-reset');
    if (reset) {
        reset.addEventListener('click', () => {
            ['degree', 'ibu', 'style', 'rating'].forEach(clearFilter);
            const sort = form.querySelector('input[name="sort"][value="date_desc"]');
            if (sort) sort.checked = true;
            refresh();
        });
    }

    // Un clic sur la barre de note déplace un curseur sans événement : on prévient le formulaire une fois le curseur placé
    const ratingBox = document.getElementById('rating_min');
    if (ratingBox && ratingBox.parentElement) {
        ratingBox.parentElement.addEventListener('click', event => {
            if (event.target.tagName.toLowerCase() !== 'input') setTimeout(refresh, 0);
        });
    }

    // Les boutons « Charger plus » du fragment remplacé doivent être rebranchés
    document.body.addEventListener('htmx:afterSwap', event => {
        if (event.detail.target.id === 'carnet-list' && typeof initLoadMore === 'function') initLoadMore(event.detail.target);
    });
})();
