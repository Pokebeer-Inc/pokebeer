// Recherche unique : saisie en direct, onglets et filtres sans recharger la page.
// Sans JavaScript, le formulaire et les liens des onglets fonctionnent par navigation classique.
(function () {
    const form = document.getElementById('search-form');
    const results = document.getElementById('search-results');
    const input = document.getElementById('search-input');
    const clear = document.getElementById('search-clear');
    if (!form || !results || !input) return;

    const DEBOUNCE_MS = 250;
    let timer = null;
    let controller = null;

    function params() {
        const query = new URLSearchParams();
        new FormData(form).forEach((value, key) => {
            if (typeof value === 'string' && value.trim() !== '') query.set(key, value.trim());
        });
        return query;
    }

    // Le bloc de résultats est remplacé à chaque modification : le panneau de filtres garde l'état voulu par le membre
    // (ouvert tant qu'il règle ses filtres, fermé s'il l'a refermé) au lieu de se refermer à chaque case cochée.
    const panel = () => results.querySelector('input[data-filter-panel]');

    function refresh() {
        clearTimeout(timer);
        // « Près de moi » filtre sa liste sur place : pas de nouvelle requête, la position déjà obtenue est conservée
        if (form.elements.tab.value === 'proche' && results.querySelector('[data-nearby]')) {
            history.replaceState(null, '', '?' + params().toString());
            document.dispatchEvent(new CustomEvent('search:filter'));
            return;
        }
        if (controller) controller.abort(); // une frappe plus récente rend la réponse précédente inutile
        controller = new AbortController();
        const query = params();
        const wasOpen = panel() ? panel().checked : null;
        results.setAttribute('aria-busy', 'true');
        results.classList.add('opacity-60');
        fetch(results.dataset.url + '?' + query.toString(), { signal: controller.signal, headers: { 'X-Requested-With': 'fetch' } })
            .then(res => { if (!res.ok) throw new Error('Erreur réseau'); return res.json(); })
            .then(data => {
                results.innerHTML = data.html;
                if (wasOpen !== null && panel()) panel().checked = wasOpen;
                history.replaceState(null, '', '?' + query.toString());
                if (typeof initLoadMore === 'function') initLoadMore(results);
                if (typeof initNearby === 'function') initNearby(results);
                results.removeAttribute('aria-busy');
                results.classList.remove('opacity-60');
            })
            .catch(err => {
                if (err.name === 'AbortError') return;
                // En cas d'échec, la navigation classique prend le relais
                window.location.search = '?' + query.toString();
            });
    }

    input.addEventListener('input', () => {
        clear.classList.toggle('hidden', input.value === '');
        clearTimeout(timer);
        timer = setTimeout(refresh, DEBOUNCE_MS);
    });
    form.addEventListener('submit', event => { event.preventDefault(); refresh(); });
    // L'événement « input » met à jour le bouton, les recherches récentes et relance la recherche : un seul chemin
    clear.addEventListener('click', () => { input.value = ''; input.dispatchEvent(new Event('input', { bubbles: true })); input.focus(); });

    // Onglets et liens « Voir tout » : même page, autre rubrique (la recherche en cours est conservée)
    results.addEventListener('click', event => {
        const link = event.target.closest('a[data-tab]');
        if (!link || event.metaKey || event.ctrlKey || event.shiftKey) return;
        event.preventDefault();
        form.elements.tab.value = link.dataset.tab;
        // Les filtres appartiennent à l'onglet Bières : ils sont remis à zéro quand on en sort ou qu'on les réinitialise
        results.querySelectorAll('[form="search-form"]').forEach(field => {
            if (field.type === 'radio') field.checked = field.value === '';
            else if (field.type === 'checkbox') field.checked = false;
            else field.value = '';
        });
        refresh();
    });

    if (typeof initNearby === 'function') initNearby(results); // page ouverte directement sur « Près de moi »

    // Filtres et tri (champs rattachés au formulaire par l'attribut form) : application immédiate
    document.addEventListener('change', event => {
        if (event.target.getAttribute && event.target.getAttribute('form') === 'search-form') refresh();
    });
})();
