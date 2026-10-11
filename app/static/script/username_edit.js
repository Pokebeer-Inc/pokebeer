// Profil : modifier son pseudo depuis une fenêtre. Le serveur valide tout (format, unicité, pseudos réservés) ;
// le navigateur ne fait qu'afficher le message d'erreur reçu. Sans JavaScript le formulaire fonctionne par envoi classique.
// La fenêtre est dans le bloc des modales, créé après le contenu de la page : on attend la fin du chargement.
document.addEventListener('DOMContentLoaded', function () {
    const dialog = document.getElementById('modal_username');
    const form = document.getElementById('username-form');
    if (!dialog || !form) return;
    const input = document.getElementById('username-input');
    const error = document.getElementById('username-error');
    const submit = form.querySelector('button[type="submit"]');

    document.addEventListener('click', event => {
        if (event.target.closest('[data-username-open]')) {
            error.textContent = '';
            dialog.showModal();
            input.focus();
            input.select();
        }
        if (event.target.closest('[data-username-close]')) dialog.close();
    });

    form.addEventListener('submit', event => {
        event.preventDefault();
        error.textContent = '';
        Pending.start(submit);
        fetch(form.action, {
            method: 'POST',
            credentials: 'same-origin',
            headers: { 'X-Requested-With': 'fetch' },
            body: new FormData(form),
        })
            .then(response => response.json().then(data => ({ ok: response.ok, data })))
            .then(({ ok, data }) => {
                if (!ok || !data.success) { error.textContent = data.error || 'Pseudo invalide.'; return; }
                document.querySelectorAll('[data-username]').forEach(node => { node.textContent = data.username; });
                const open = document.querySelector('[data-username-open]');
                if (open) open.setAttribute('aria-label', 'Modifier mon pseudo : ' + data.username);
                dialog.close();
            })
            .catch(() => { error.textContent = 'Connexion impossible. Réessayez.'; })
            .finally(() => { Pending.stop(submit); });
    });
});
