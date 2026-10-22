// Accueil (Recherche) : salutation selon l'heure de l'appareil et « Autour de vous ».
(function () {
    const greeting = document.querySelector('[data-greeting]');
    if (greeting) greeting.textContent = new Date().getHours() < 18 ? 'Bonjour' : 'Bonsoir';

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
