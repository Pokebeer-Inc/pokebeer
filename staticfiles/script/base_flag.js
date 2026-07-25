window.addEventListener('pageshow', function(event) {
    // On vérifie si la page vient du cache (BFCache) ET si le drapeau de modification est levé
    if (event.persisted && sessionStorage.getItem('db_state_changed') === 'true') {
        // On baisse le drapeau pour éviter des rechargements infinis
        sessionStorage.removeItem('db_state_changed');
        // On demande la nouvelle page au serveur
        window.location.reload();
    }
});