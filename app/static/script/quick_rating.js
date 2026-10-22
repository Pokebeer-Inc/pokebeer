// Note rapide de la page de félicitations : deux étapes gérées par stepper.js (note et quelques mots, puis contexte facultatif). Passer à la
// suite exige une note ou quelques mots : le message natif du navigateur s'affiche sur le champ de texte tant que la réaction est vide
// (le serveur la refuse aussi).
document.addEventListener('DOMContentLoaded', function () {
    const form = document.getElementById('quick-rating');
    const comment = form && form.querySelector('textarea[name="comment"]');
    if (!form || !comment) return;

    const refresh = () => {
        const reacted = Boolean(form.querySelector('input[name="note"]:checked')) || Boolean(comment.value.trim());
        comment.setCustomValidity(reacted ? '' : 'Choisissez une note ou écrivez quelques mots.');
    };

    form.addEventListener('change', refresh);
    form.addEventListener('input', refresh);
    refresh();
});
