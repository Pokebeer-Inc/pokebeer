// Retour visuel pendant une attente : un bouton ou un lien grisé avec un petit cercle qui tourne, une zone estompée (liste en cours de
// rechargement). Le membre voit que son geste est pris en compte ; un second appui est ignoré le temps de la requête.
// Un seul module pour tout le site : les scripts appellent Pending.run(bouton, requête) et les requêtes htmx sont prises en charge ici.
// Le cercle n'apparaît qu'après un court délai (ui.css) : une réponse rapide ne fait pas clignoter l'écran.
(function () {
    const isControl = element => element instanceof HTMLButtonElement || element instanceof HTMLInputElement;

    // Début de l'attente ; false si l'élément attend déjà (appui répété)
    function start(element) {
        if (!element || element.dataset.pending) return false;
        element.dataset.pending = '1';
        element.classList.add('pb-pending');
        element.setAttribute('aria-busy', 'true');
        if (isControl(element)) {
            element.dataset.wasDisabled = element.disabled ? '1' : '';
            element.disabled = true;
        } else {
            element.setAttribute('aria-disabled', 'true');
        }
        if (element.matches('button, a, .btn')) {
            const spinner = document.createElement('span');
            spinner.className = 'pb-spinner';
            spinner.setAttribute('aria-hidden', 'true');
            spinner.dataset.pendingSpinner = '';
            element.prepend(spinner);
        }
        return true;
    }

    function stop(element) {
        if (!element || !element.dataset.pending) return;
        delete element.dataset.pending;
        element.classList.remove('pb-pending');
        element.removeAttribute('aria-busy');
        element.removeAttribute('aria-disabled');
        if (isControl(element)) {
            element.disabled = element.dataset.wasDisabled === '1';
            delete element.dataset.wasDisabled;
        }
        const spinner = element.querySelector(':scope > [data-pending-spinner]');
        if (spinner) spinner.remove();
    }

    // Exécute le travail (une promesse ou une fonction) avec l'élément en attente ; rend sa valeur, ou undefined si l'élément attendait déjà
    async function run(element, work) {
        if (!start(element)) return undefined;
        try {
            return await (typeof work === 'function' ? work() : work);
        } finally {
            stop(element);
        }
    }

    // Zone dont le contenu se recharge : estompée (et non cliquable) pendant l'attente
    function region(element, busy) {
        if (!element) return;
        element.classList.toggle('pb-region', Boolean(busy));
        if (busy) element.setAttribute('aria-busy', 'true'); else element.removeAttribute('aria-busy');
    }

    // Bouton qui envoie un formulaire (confirmations de suppression…) : attente visible, puis envoi normal (le formulaire passe par ses
    // contrôles et par le chargeur de page, contrairement à form.submit())
    function submitForm(button, formId) {
        const form = document.getElementById(formId);
        if (!form || !start(button)) return;
        if (!form.reportValidity()) return stop(button);
        form.requestSubmit();
    }

    window.Pending = { start, stop, run, region, submitForm };

    // Requêtes htmx (filtres du carnet…) : la zone qui se recharge est estompée, la page garde sa place
    document.addEventListener('htmx:beforeRequest', event => region(event.detail.target || event.detail.elt, true));
    document.addEventListener('htmx:afterRequest', event => region(event.detail.target || event.detail.elt, false));

    // Retour par le bouton « précédent » (page restaurée du cache) : rien ne doit rester en attente
    window.addEventListener('pageshow', event => {
        if (!event.persisted) return;
        document.querySelectorAll('[data-pending]').forEach(stop);
        document.querySelectorAll('.pb-region').forEach(element => region(element, false));
    });
})();
