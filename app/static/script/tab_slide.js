// Glissement des onglets en puces (.pb-chips) : le contenu entre par la droite si l'onglet choisi est plus loin dans la liste, par la gauche sinon.
// Deux cas : recherche (contenu remplacé sans recharger la page) et pages à liens (le sens est gardé le temps du rechargement).
(function () {
    const KEY = 'pb-slide';
    const RIGHT = 'slide-in-right';
    const LEFT = 'slide-in-left';

    function store(direction) {
        try { sessionStorage.setItem(KEY, direction); } catch (e) { /* stockage indisponible : pas d'animation */ }
    }
    function take() {
        try {
            const direction = sessionStorage.getItem(KEY);
            sessionStorage.removeItem(KEY);
            return direction;
        } catch (e) { return null; }
    }

    // Anime tout ce qui suit les puces (les puces elles-mêmes restent en place)
    function slideAfter(nav, direction) {
        for (let node = nav.nextElementSibling; node; node = node.nextElementSibling) {
            node.classList.remove(RIGHT, LEFT);
            void node.offsetWidth; // relance l'animation même si la classe était déjà là
            node.classList.add(direction);
        }
    }

    document.addEventListener('click', event => {
        const chip = event.target.closest('.pb-chips a.pb-chip');
        if (!chip || event.metaKey || event.ctrlKey || event.shiftKey || event.button) return;
        const chips = Array.from(chip.parentElement.querySelectorAll('a.pb-chip'));
        const current = chips.findIndex(c => c.classList.contains('is-on'));
        const next = chips.indexOf(chip);
        if (next === current) return;
        store(next > current ? RIGHT : LEFT);
    }, true);

    if (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) { take(); return; }

    document.addEventListener('DOMContentLoaded', () => {
        const direction = take();
        const nav = document.querySelector('.pb-chips');
        const results = document.getElementById('search-results');
        // Page ouverte par un lien d'onglet (carnet, profil public, recherche sans JavaScript)
        if (direction && nav) slideAfter(nav, direction);

        // Recherche : le bloc de résultats est remplacé sur place
        if (results) {
            new MutationObserver(() => {
                const pending = take();
                const tabs = results.querySelector('.pb-chips');
                if (pending && tabs) slideAfter(tabs, pending);
            }).observe(results, { childList: true });
        }
    });
})();
