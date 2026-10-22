// Pages de félicitations : fête de confettis (confetti.js) au chargement et au clic sur « célébrer encore ».
(function () {
    // L'adresse garde le « #step-6 » de l'assistant après la redirection : on l'enlève
    if (location.hash.indexOf('#step-') === 0) history.replaceState(null, '', location.pathname + location.search);
    const canvas = document.getElementById('confetti');
    if (!canvas) return;
    Pokebeer.confetti.attach(canvas);
    const again = document.getElementById('celebrate-again');
    if (again) again.addEventListener('click', Pokebeer.confetti.party);
    Pokebeer.confetti.party();
})();
