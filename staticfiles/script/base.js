document.addEventListener('submit', function(event) {
    const form = event.target;
    const submitBtn = form.querySelector('button[type="submit"], input[type="submit"]');
    
    if (submitBtn) {
        //submitBtn.disabled = true;
        submitBtn.style.opacity = '0.7';
    }
});

document.addEventListener("DOMContentLoaded", function() {
    // Fonction robuste pour lire un cookie
    function getCookie(name) {
        let cookieValue = null;
        if (document.cookie && document.cookie !== '') {
            const cookies = document.cookie.split(';');
            for (let i = 0; i < cookies.length; i++) {
                const cookie = cookies[i].trim();
                if (cookie.substring(0, name.length + 1) === (name + '=')) {
                    cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                    break;
                }
            }
        }
        return cookieValue;
    }

    // Enregistrement du jeton Firebase de l'appareil pour le compte connecté (notifications push Android)
    const isAuthenticated = document.querySelector('meta[name="user-authenticated"]')?.content === 'true';
    const accountKey = document.querySelector('meta[name="ws-channel"]')?.content; // identifiant privé et stable du compte
    const SYNC_KEY = 'pokebeer_fcm_sync';

    localStorage.removeItem('pokebeer_fcm_token'); // ancienne clé : valait « enregistré » même sans compte connecté

    if (!isAuthenticated) {
        // Déconnecté (le serveur oublie alors le jeton) : à la prochaine connexion, l'appareil doit se réenregistrer
        localStorage.removeItem(SYNC_KEY);
    } else if (window.AndroidBridge && accountKey) {
        let retries = 0;
        const tokenInterval = setInterval(() => {
            const fcmToken = window.AndroidBridge.getFcmToken();

            if (fcmToken && fcmToken !== "") {
                clearInterval(tokenInterval);
                const syncValue = accountKey + ':' + fcmToken; // un jeton n'est « enregistré » que pour CE compte

                if (syncValue !== localStorage.getItem(SYNC_KEY)) {
                    const csrfToken = getCookie('csrftoken');
                    if (!csrfToken) return; // Sécurité si le cookie n'est pas encore là

                    fetch('/api/update-fcm-token/', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken },
                        credentials: 'same-origin',
                        redirect: 'manual', // une redirection vers la connexion n'est PAS un succès
                        body: JSON.stringify({ token: fcmToken })
                    })
                    .then(response => response.ok ? response.json() : null)
                    .then(data => {
                        if (data && data.status === 'success') {
                            localStorage.setItem(SYNC_KEY, syncValue);
                        }
                    })
                    .catch(err => console.error("Erreur réseau FCM", err));
                }
            }

            retries++;
            if (retries >= 5) clearInterval(tokenInterval);
        }, 2000);
    }
});