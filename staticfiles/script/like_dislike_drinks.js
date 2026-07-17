let pressTimer;
let currentDrinkId = null;
let isPressing = false; // Permet de savoir si on est en train de maintenir l'appui

// Démarre le chronomètre au toucher/clic long
function startPress(e, drinkId) {
    if (e.type === 'mousedown' && e.button !== 0) return; // Ignore clic droit
    
    isPressing = true;
    pressTimer = setTimeout(() => {
        if (isPressing) { // Vérifie qu'on est toujours en train d'appuyer
            showReactions(drinkId);
            // Petit retour haptique sur mobile pour indiquer que le menu s'ouvre
            if (window.navigator && window.navigator.vibrate) window.navigator.vibrate(50);
        }
    }, 500); // 500ms d'appui
}

// Annule si l'utilisateur relâche trop tôt
function cancelPress() {
    isPressing = false;
    clearTimeout(pressTimer);
}

// Affiche le menu des pouces
function showReactions(drinkId) {
    hideAllReactions();
    const menu = document.getElementById('reactions-' + drinkId);
    if (menu) {
        menu.classList.remove('hidden', 'scale-0');
        menu.classList.add('scale-100');
        currentDrinkId = drinkId;
    }
}

// Cache les menus
function hideAllReactions() {
    document.querySelectorAll('.reaction-menu').forEach(menu => {
        menu.classList.remove('scale-100');
        menu.classList.add('hidden', 'scale-0');
    });
    currentDrinkId = null;
}

// Cache le menu si on clique n'importe où ailleurs (SAUF sur le menu lui-même)
document.addEventListener('pointerdown', (e) => { // pointerdown est plus fiable que click sur mobile/desktop
    if (currentDrinkId && !e.target.closest('.reaction-menu') && !e.target.closest('.drink-card')) {
        hideAllReactions();
    }
});

// Envoi de la réaction (Like/Dislike) au serveur
function react(event, drinkId, isLike) {
    event.preventDefault(); // Empêche les comportements par défaut (comme le double clic sur mobile)
    event.stopPropagation(); // Évite que le pointerdown global ou d'autres clics soient déclenchés
    
    hideAllReactions();
    
    fetch(`/drink/${drinkId}/react/`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': document.querySelector('[name=csrfmiddlewaretoken]') ? document.querySelector('[name=csrfmiddlewaretoken]').value : window.CSRF_TOKEN
        },
        body: JSON.stringify({ is_like: isLike })
    })
    .then(res => res.json())
    .then(data => {
        if (data.success) {
            // Met à jour le Score Global
            const scoreSpan = document.getElementById('score-val-' + drinkId);
            scoreSpan.innerText = data.score > 0 ? '+' + data.score : data.score;
            
            scoreSpan.classList.remove('text-success', 'text-error', 'text-gray-300', 'opacity-50');
            if (data.score > 0) scoreSpan.classList.add('text-success');
            else if (data.score < 0) scoreSpan.classList.add('text-error');
            else {
                scoreSpan.classList.add('text-gray-300', 'opacity-50');
                scoreSpan.innerText = "0"; 
            }

            // Met à jour les petits compteurs en bas à droite
            document.getElementById('likes-count-' + drinkId).innerText = data.likes;
            document.getElementById('dislikes-count-' + drinkId).innerText = data.dislikes;

            // Met à jour les couleurs des petits pouces en bas à droite
            const thumbUp = document.getElementById('thumb-up-' + drinkId);
            const thumbDown = document.getElementById('thumb-down-' + drinkId);
            
            thumbUp.classList.remove('text-success');
            thumbDown.classList.remove('text-error');
            
            if (data.current_reaction === true) {
                thumbUp.classList.add('text-success'); // Colore le pouce en haut en vert
            } else if (data.current_reaction === false) {
                thumbDown.classList.add('text-error'); // Colore le pouce en bas en rouge
            }

        } else {
            alert(data.error);
        }
    });
}