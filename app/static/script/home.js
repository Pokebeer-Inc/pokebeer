// Accueil (Recherche) : salutation selon l'heure de l'appareil, bouton Gaétan et « Autour de vous ».
(function () {
    const greeting = document.querySelector('[data-greeting]');
    if (greeting) greeting.textContent = new Date().getHours() < 18 ? 'Bonjour' : 'Bonsoir';

    // Gaétan : ouvre la bulle de discussion (sans la refermer si elle est déjà ouverte) et ne préremplit rien.
    // La bulle est créée après le contenu de la page : on la cherche au moment du clic, jamais au chargement du script.
    const chat = document.querySelector('[data-open-chat]');
    if (chat) {
        chat.addEventListener('click', () => {
            const toggle = document.getElementById('chat-toggle');
            const bubble = document.getElementById('chat-window');
            if (toggle && bubble && bubble.classList.contains('hidden')) toggle.click();
        });
    }

    // Autour de vous : la position n'est demandée que lorsque la rubrique approche de l'écran (pas dès l'ouverture de la page)
    const nearby = document.getElementById('home-nearby');
    if (!nearby || typeof initNearby !== 'function') return;
    let started = false;
    const start = () => { if (!started) { started = true; initNearby(nearby); } };
    if ('IntersectionObserver' in window) {
        const observer = new IntersectionObserver(entries => {
            if (entries.some(entry => entry.isIntersecting)) { observer.disconnect(); start(); }
        }, { rootMargin: '200px 0px' });
        observer.observe(nearby);
    } else {
        start();
    }
})();
