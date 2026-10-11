// Formulaire par étapes dans une fenêtre (notation d'une bière) : un panneau à la fois, progression, retour/suivant ; l'envoi se fait depuis la dernière étape.
// Délégation d'événements : les fenêtres chargées dynamiquement (« voir plus ») fonctionnent sans initialisation. L'affichage des panneaux
// est porté par data-current (ui.css) ; sans JavaScript toutes les étapes restent visibles. Rien n'est enregistré avant l'envoi final :
// le serveur valide comme pour tout autre formulaire.
(function () {
    const panelsOf = form => Array.from(form.querySelectorAll('[data-stepper-step]'));
    const currentOf = form => Number(form.dataset.current) || 1;

    function nativeValid(panel) {
        const invalid = Array.from(panel.querySelectorAll('input, select, textarea')).find(control => control.type !== 'file' && !control.checkValidity());
        if (!invalid) return true;
        invalid.reportValidity();
        return false;
    }

    function show(form, number) {
        const panels = panelsOf(form);
        const total = panels.length;
        const current = Math.min(Math.max(number, 1), total);
        form.dataset.current = String(current);
        if (current === total) form.dataset.last = ''; else delete form.dataset.last;
        form.querySelector('[data-stepper-number]').textContent = current;
        form.querySelector('[data-stepper-total]').textContent = total;
        form.querySelector('[data-stepper-title]').textContent = panels[current - 1].dataset.title;
        form.querySelector('[data-stepper-bar]').style.width = (current / total * 100) + '%';
        const progress = form.querySelector('[role="progressbar"]');
        progress.setAttribute('aria-valuenow', current);
        progress.setAttribute('aria-valuemax', total);
        const box = form.closest('.modal-box');
        if (box) box.scrollTop = 0;
    }

    function next(form) {
        const panel = panelsOf(form)[currentOf(form) - 1];
        if (nativeValid(panel)) show(form, currentOf(form) + 1);
    }

    document.addEventListener('click', event => {
        const forward = event.target.closest('[data-stepper-next]');
        const backward = event.target.closest('[data-stepper-back]');
        const form = (forward || backward)?.closest('[data-stepper]');
        if (!form) return;
        if (forward) next(form); else show(form, currentOf(form) - 1);
    });

    // Entrée dans un champ passe à l'étape suivante au lieu d'envoyer l'avis trop tôt
    document.addEventListener('keydown', event => {
        if (event.key !== 'Enter' || event.isComposing || event.target.tagName === 'TEXTAREA' || event.target.tagName === 'BUTTON') return;
        const form = event.target.closest('[data-stepper]');
        if (!form || 'last' in form.dataset) return;
        event.preventDefault();
        next(form);
    });

    // Envoi : seulement depuis la dernière étape, une seule fois
    document.addEventListener('submit', event => {
        const form = event.target;
        if (!form.matches || !form.matches('[data-stepper]')) return;
        if (!('last' in form.dataset)) {
            event.preventDefault();
            return next(form);
        }
        if (form.dataset.sent) return event.preventDefault();
        form.dataset.sent = '1';
        const submit = form.querySelector('[data-stepper-submit]');
        if (submit) Pending.start(submit);  // le cercle montre que l'avis part ; la page change ensuite
    });
})();
