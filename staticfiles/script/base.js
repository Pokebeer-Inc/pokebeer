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

    if (window.AndroidBridge) {
        let retries = 0;
        const tokenInterval = setInterval(() => {
            const fcmToken = window.AndroidBridge.getFcmToken();
            
            if (fcmToken && fcmToken !== "") {
                clearInterval(tokenInterval); 
                const storedToken = localStorage.getItem('pokebeer_fcm_token');
                
                if (fcmToken !== storedToken) {
                    const csrfToken = getCookie('csrftoken');
                    
                    if (!csrfToken) return; // Sécurité si le cookie n'est pas encore là
                    
                    fetch('/api/update-fcm-token/', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'X-CSRFToken': csrfToken
                        },
                        body: JSON.stringify({ token: fcmToken })
                    })
                    .then(response => {
                        if(response.ok) {
                            localStorage.setItem('pokebeer_fcm_token', fcmToken);
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