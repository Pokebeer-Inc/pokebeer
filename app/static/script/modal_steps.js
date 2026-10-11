// Fenêtre de notation en deux étapes : l'étape affichée est portée par la fenêtre (data-step) et mise en forme par ui.css. Délégation
// d'événements : les fenêtres chargées dynamiquement (« voir plus ») fonctionnent sans initialisation.
(function () {
    function show(trigger, step) {
        const dialog = trigger.closest('dialog');
        if (!dialog) return;
        dialog.dataset.step = step;
        const box = dialog.querySelector('.modal-box');
        if (box) box.scrollTop = 0;
    }

    document.addEventListener('click', event => {
        const go = event.target.closest('[data-step-go]');
        if (go) return show(go, go.dataset.stepGo === '2' ? '2' : '1');
        const back = event.target.closest('[data-step-back]');
        if (back) show(back, '1');
    });

    // « close » ne remonte pas : on l'écoute en phase de capture pour rouvrir chaque fenêtre sur sa première étape
    document.addEventListener('close', event => {
        if (event.target.dataset && event.target.dataset.step) delete event.target.dataset.step;
    }, true);
})();
