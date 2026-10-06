document.addEventListener('DOMContentLoaded', function () {
    const backBtn = document.getElementById('error-404-back');
    const homeBtn = document.getElementById('error-404-home');
    if (!backBtn || !homeBtn) return;

    backBtn.addEventListener('click', function () {
        // Pas d'historique ou page précédente externe : on retombe sur l'accueil
        const sameOrigin = document.referrer && new URL(document.referrer).origin === window.location.origin;
        if (window.history.length > 1 && sameOrigin) {
            window.history.back();
        } else {
            window.location.href = homeBtn.href;
        }
    });
});
