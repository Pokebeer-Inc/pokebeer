// Recherche unique : la recherche part quand le membre valide (Entrée, touche « Rechercher » du clavier ou loupe), jamais à chaque frappe ;
// onglets et filtres s'appliquent sans recharger la page.
// Sans JavaScript, le formulaire et les liens des onglets fonctionnent par navigation classique.
(function () {
    const form = document.getElementById('search-form');
    const results = document.getElementById('search-results');
    const input = document.getElementById('search-input');
    const clear = document.getElementById('search-clear');
    const home = document.getElementById('home-sections'); // présent seulement sur la page d'accueil (Recherche)
    if (!form || !results || !input) return;

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

    // Accueil : tant que la barre est vide et qu'aucun onglet ou filtre n'a été choisi, on montre l'accueil et non des résultats
    function showHome() {
        if (controller) controller.abort();
        results.replaceChildren();
        Pending.region(results, false);
        form.removeAttribute('aria-busy');
        home.classList.remove('hidden');
        history.replaceState(null, '', location.pathname);
    }

    function refresh() {
        if (home && input.value.trim() === '' && form.elements.tab.value === 'all') return showHome();
        if (home) home.classList.add('hidden');
        // « Près de moi » filtre sa liste sur place : pas de nouvelle requête, la position déjà obtenue est conservée
        if (form.elements.tab.value === 'nearby' && results.querySelector('[data-nearby]')) {
            history.replaceState(null, '', '?' + params().toString());
            document.dispatchEvent(new CustomEvent('search:filter'));
            return;
        }
        if (controller) controller.abort(); // une frappe plus récente rend la réponse précédente inutile
        controller = new AbortController();
        const query = params();
        const wasOpen = panel() ? panel().checked : null;
        Pending.region(results, true);
        form.setAttribute('aria-busy', 'true');  // l'icône de la barre devient un cercle (ui.css)
        fetch(results.dataset.url + '?' + query.toString(), { signal: controller.signal, headers: { 'X-Requested-With': 'fetch' } })
            .then(res => { if (!res.ok) throw new Error('Erreur réseau'); return res.json(); })
            .then(data => {
                results.innerHTML = data.html;
                if (wasOpen !== null && panel()) panel().checked = wasOpen;
                history.replaceState(null, '', '?' + query.toString());
                if (typeof initLoadMore === 'function') initLoadMore(results);
                if (typeof initNearby === 'function') initNearby(results);
                Pending.region(results, false);
                form.removeAttribute('aria-busy');
            })
            .catch(err => {
                if (err.name === 'AbortError') return;
                // En cas d'échec, la navigation classique prend le relais
                window.location.search = '?' + query.toString();
            });
    }

    // Saisir ne lance aucune requête : on met seulement à jour la croix d'effacement (et, via recent_searches.js, les recherches récentes)
    input.addEventListener('input', () => clear.classList.toggle('hidden', input.value === ''));
    form.addEventListener('submit', event => { event.preventDefault(); refresh(); });
    // Effacer est une action volontaire : elle ramène tout de suite à l'accueil / aux résultats sans filtre de texte
    clear.addEventListener('click', () => { input.value = ''; if (home) form.elements.tab.value = 'all'; input.dispatchEvent(new Event('input', { bubbles: true })); refresh(); input.focus(); });

    // Onglets et liens « Voir tout » : même page, autre rubrique (la recherche en cours est conservée)
    function onTabClick(event) {
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
    }
    results.addEventListener('click', onTabClick);
    if (home) home.addEventListener('click', onTabClick); // puces de l'accueil

    if (typeof initNearby === 'function') initNearby(results); // page ouverte directement sur « Près de moi »

    // Filtres et tri (champs rattachés au formulaire par l'attribut form) : application immédiate
    document.addEventListener('change', event => {
        if (event.target.getAttribute && event.target.getAttribute('form') === 'search-form') refresh();
    });
})();
