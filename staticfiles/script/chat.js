const chatToggle = document.getElementById('chat-toggle');
const chatWindow = document.getElementById('chat-window');
const chatClose = document.getElementById('chat-close');
const chatInput = document.getElementById('chat-input');
const chatMessages = document.getElementById('chat-messages');
const chatOverlay = document.getElementById('chat-overlay');
const chatSend = document.getElementById('chat-send');

// Ouvrir / Fermer le chat et le fond
chatToggle.addEventListener('click', () => {
    chatWindow.classList.toggle('hidden');
    chatOverlay.classList.toggle('hidden'); // On affiche/masque l'overlay en même temps

    if (!chatWindow.classList.contains('hidden')) {
        chatMessages.scrollTop = chatMessages.scrollHeight;
    }
});

// Fonction centralisée pour fermer le chat
function closeChat() {
    chatWindow.classList.add('hidden');
    chatOverlay.classList.add('hidden');
}

// Fermer avec la croix
chatClose.addEventListener('click', closeChat);

// Fermer si on clique en dehors (sur le fond grisé)
chatOverlay.addEventListener('click', closeChat);

// Bulles de discussion : le texte du membre est échappé, la réponse de l'IA (Markdown) est nettoyée par DOMPurify
function userBubble(text) {
    return `
                <div class="chat chat-end">
                    <div class="chat-bubble shadow-sm text-sm">${escapeHtml(text)}</div>
                </div>`;
}

function modelBubble(markdown) {
    return `
            <div class="chat chat-start">
                <div class="chat-bubble bg-primary text-black shadow-sm text-sm markdown-content">${renderMarkdown(markdown)}</div>
            </div>`;
}

function errorBubble(text) {
    return `
                    <div class="chat chat-start">
                        <div class="chat-bubble chat-bubble-error text-sm">${escapeHtml(text)}</div>
                    </div>`;
}

function addToChat(html) {
    chatMessages.insertAdjacentHTML('beforeend', html);
    chatMessages.scrollTop = chatMessages.scrollHeight;
}

// Position : réservée à la demande du membre (bouton), lue à chaque envoi et gardée en mémoire seulement le temps de l'envoi.
// Le serveur l'arrondit (~1 km) et ne l'enregistre pas.
const chatLocationButton = document.getElementById('chat-location');
const CHAT_LOCATION_KEY = 'chat-location-enabled';
const CHAT_LOCATION_OPTIONS = { enableHighAccuracy: false, maximumAge: 300000, timeout: 8000 };

function locationEnabled() {
    try { return sessionStorage.getItem(CHAT_LOCATION_KEY) === '1'; } catch (e) { return false; }
}

function setLocationEnabled(enabled) {
    try { sessionStorage.setItem(CHAT_LOCATION_KEY, enabled ? '1' : '0'); } catch (e) { /* stockage indisponible : réglage non mémorisé */ }
    chatLocationButton.setAttribute('aria-pressed', String(enabled));
    chatLocationButton.classList.toggle('btn-primary', enabled);
    chatLocationButton.classList.toggle('btn-outline', !enabled);
    chatLocationButton.classList.toggle('text-black', enabled);  // le texte du bouton plein est clair sur le jaune du thème
}

function readPosition() {
    return new Promise(resolve => {
        if (!navigator.geolocation) return resolve({ error: "La localisation n'est pas disponible sur cet appareil." });
        navigator.geolocation.getCurrentPosition(
            position => resolve({ lat: position.coords.latitude, lng: position.coords.longitude }),
            error => resolve({ error: error.code === 1
                ? "Position refusée : autorisez la localisation pour Pokebeer dans les réglages, ou citez une ville dans votre question."
                : "Position introuvable. Citez une ville dans votre question." }),
            CHAT_LOCATION_OPTIONS,
        );
    });
}

// Vrai quand la dernière réponse de Gaétan attendait la position du membre : l'activer relance alors la conversation
let awaitingLocation = false;
const LOCATION_RESUME_MESSAGE = "J'ai activé ma position, reprends ma demande précédente.";

chatLocationButton.addEventListener('click', async () => {
    if (locationEnabled()) return setLocationEnabled(false);
    const position = await readPosition();  // déclenche la demande d'autorisation du navigateur
    if (position.error) return addToChat(errorBubble(position.error));
    setLocationEnabled(true);
    if (awaitingLocation) return sendMessage(LOCATION_RESUME_MESSAGE);
    addToChat(modelBubble("Position activée : je peux chercher des bars et brasseries autour de vous. Elle n'est jamais enregistrée."));
});

async function sendMessage(text) {
    const msg = (text ?? chatInput.value).trim();
    if (!msg || chatSend.disabled) return;

    chatSend.disabled = true;
    document.getElementById('chat-suggestions')?.remove();
    addToChat(userBubble(msg));
    chatInput.value = '';

    const loadingId = 'loading-' + Date.now();
    addToChat(`
                <div id="${loadingId}" class="chat chat-start">
                    <div class="chat-bubble bg-primary text-black shadow-sm">
                        <span class="loading loading-dots loading-sm bg-black"></span>
                    </div>
                </div>`);

    try {
        const body = { message: msg };
        if (locationEnabled()) {
            const position = await readPosition();
            if (!position.error) body.location = position;
        }
        const res = await fetch(chatWindow.dataset.url, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': document.querySelector('meta[name="csrf-token"]').content
            },
            body: JSON.stringify(body)
        });
        const data = await res.json();
        document.getElementById(loadingId)?.remove();
        // Un refus (quota, message invalide, service indisponible) n'est pas une réponse de Gaétan
        awaitingLocation = res.ok && data.needs_location === true;
        addToChat(res.ok ? modelBubble(data.response) : errorBubble(data.response));
    } catch (err) {
        document.getElementById(loadingId)?.remove();
        addToChat(errorBubble("La cave est fermée, impossible de joindre Gaétan."));
    } finally {
        chatSend.disabled = false;
    }
}

chatSend.addEventListener('click', () => sendMessage());
chatInput.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.isComposing) sendMessage();
});
chatMessages.addEventListener('click', e => {
    const suggestion = e.target.closest('[data-chat-suggestion]');
    if (suggestion) sendMessage(suggestion.dataset.chatSuggestion);
});

document.addEventListener('DOMContentLoaded', async () => {
    setLocationEnabled(locationEnabled());
    try {
        const res = await fetch(chatWindow.dataset.url, {
            method: 'GET',
            headers: { 'X-Requested-With': 'XMLHttpRequest', 'Accept': 'application/json' },
            credentials: 'same-origin'
        });
        if (!res.ok) return;
        const data = await res.json();
        if (data.history && data.history.length > 0) {
            chatMessages.innerHTML = data.history.map(msg => msg.role === 'user' ? userBubble(msg.text) : modelBubble(msg.text)).join('');
        }
    } catch (err) {
        console.error("Erreur réseau lors de la récupération de l'historique :", err);
    }
});
