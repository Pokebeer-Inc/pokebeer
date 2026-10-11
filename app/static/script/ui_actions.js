// Actions déclarées dans le HTML par des attributs data-*, à la place des gestionnaires en ligne (onclick="…").
// La politique de sécurité du contenu (CSP) interdit le JavaScript en ligne : un script injecté dans une page ne peut donc plus s'exécuter.
//
//   data-modal-open="id"        clic : ouvre la fenêtre <dialog id="…">
//   data-modal-close[="id"]     clic : ferme la fenêtre indiquée, ou celle qui contient l'élément
//   data-on-<événement>="fonction"  appelle window.fonction(événement, ...data-args) ; data-no-event : sans l'événement ; data-key="Enter" : seulement cette touche
//   data-args='["a", true]'     arguments (JSON) transmis à la fonction
//   data-stop="click mousedown" ne laisse pas ces événements remonter aux parents (comme event.stopPropagation())
//   data-no-contextmenu         désactive le menu contextuel
//   data-prevent-submit         empêche l'envoi du formulaire
//   data-history-back           clic : revient à la page précédente (le lien href sert si l'historique est vide)
//   data-remove-on-error        retire l'image si elle ne se charge pas
(function () {
    const EVENTS = ['click', 'mousedown', 'mouseup', 'mouseleave', 'touchstart', 'touchend', 'touchcancel', 'keyup', 'keypress'];
    const NON_BUBBLING = new Set(['mouseleave']); // seul l'élément visé réagit, pas ses parents

    function argsOf(element) {
        try { return JSON.parse(element.dataset.args || '[]'); } catch (error) { return []; }
    }

    function run(element, event) {
        const name = element.dataset['on' + event.type[0].toUpperCase() + event.type.slice(1)];
        if (!name) return;
        if (element.dataset.key && event.key !== element.dataset.key) return;
        const fn = window[name];
        if (typeof fn !== 'function') return;
        const args = argsOf(element);
        if ('noEvent' in element.dataset) return fn(...args);
        // Comme avec un gestionnaire en ligne, `event.currentTarget` est l'élément qui porte l'attribut (ici l'écouteur est sur le document)
        const own = new Proxy(event, {
            get(target, property) {
                if (property === 'currentTarget') return element;
                const value = target[property];
                return typeof value === 'function' ? value.bind(target) : value;
            },
        });
        fn(own, ...args);
    }

    function stops(element, type) {
        return (element.dataset.stop || '').split(' ').includes(type);
    }

    EVENTS.forEach(type => {
        document.addEventListener(type, event => {
            let element = event.target instanceof Element ? event.target : null;
            while (element) {
                run(element, event);
                // Comme un gestionnaire en ligne : l'événement ne remonte plus si l'élément (data-stop) ou la fonction (stopPropagation) l'arrête
                if (NON_BUBBLING.has(type) || stops(element, type) || event.cancelBubble) break;
                element = element.parentElement;
            }
        }, { capture: NON_BUBBLING.has(type), passive: type.startsWith('touch') });  // mouseleave ne remonte pas : on le capte à la descente
    });

    document.addEventListener('click', event => {
        const target = event.target instanceof Element ? event.target : null;
        const opener = target && target.closest('[data-modal-open]');
        if (opener) {
            const dialog = document.getElementById(opener.dataset.modalOpen);
            if (dialog) dialog.showModal();
        }
        const closer = target && target.closest('[data-modal-close]');
        if (closer) {
            const dialog = closer.dataset.modalClose ? document.getElementById(closer.dataset.modalClose) : closer.closest('dialog');
            if (dialog) dialog.close();
        }
    });

    document.addEventListener('click', event => {
        const back = event.target instanceof Element && event.target.closest('[data-history-back]');
        if (back && history.length > 1) { event.preventDefault(); history.back(); }
    });

    document.addEventListener('contextmenu', event => {
        if (event.target instanceof Element && event.target.closest('[data-no-contextmenu]')) event.preventDefault();
    });

    document.addEventListener('submit', event => {
        const form = event.target;
        if (form instanceof Element && form.hasAttribute('data-prevent-submit')) event.preventDefault();
    });

    // Les erreurs de chargement ne remontent pas : on les capte à la descente
    document.addEventListener('error', event => {
        const target = event.target;
        if (target instanceof Element && target.hasAttribute('data-remove-on-error')) target.remove();
    }, true);
})();
