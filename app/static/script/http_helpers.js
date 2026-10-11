// Utilitaires partagés par les scripts du site : jeton CSRF et temporisation des saisies. Chargé avant tous les autres (base.html).
window.Pokebeer = window.Pokebeer || {};

(function (Pokebeer) {
    function cookie(name) {
        const match = document.cookie.split('; ').find(row => row.startsWith(name + '='));
        return match ? decodeURIComponent(match.slice(name.length + 1)) : '';
    }

    // Jeton CSRF à envoyer dans l'en-tête X-CSRFToken : celui de la page (meta), sinon d'un formulaire, sinon le cookie
    Pokebeer.csrfToken = function () {
        const meta = document.querySelector('meta[name="csrf-token"]');
        if (meta && meta.content) return meta.content;
        const field = document.querySelector('[name=csrfmiddlewaretoken]');
        if (field && field.value) return field.value;
        return cookie('csrftoken');
    };

    // Retarde `fn` jusqu'à `wait` ms après le dernier appel ; `.cancel()` abandonne l'appel en attente
    Pokebeer.debounce = function (fn, wait) {
        let timer = null;
        const debounced = function (...args) {
            clearTimeout(timer);
            timer = setTimeout(() => { timer = null; fn.apply(this, args); }, wait);
        };
        debounced.cancel = () => { clearTimeout(timer); timer = null; };
        return debounced;
    };
})(window.Pokebeer);
