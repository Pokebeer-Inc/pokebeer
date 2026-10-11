const chatToggle = document.getElementById('chat-toggle');
const chatWindow = document.getElementById('chat-window');
const chatClose = document.getElementById('chat-close');
const chatInput = document.getElementById('chat-input');
const chatMessages = document.getElementById('chat-messages');
const chatOverlay = document.getElementById('chat-overlay');
const chatSend = document.getElementById('chat-send');
const chatReset = document.getElementById('chat-reset');
const CHAT_WELCOME_HTML = chatMessages.innerHTML;  // message d'accueil et questions de départ, rendus par la page

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

// Position : lue sans invite quand elle est déjà connue (page « Autour de vous », autorisation accordée) et jointe au message ; sinon Gaétan
// la demande seulement s'il en a besoin, avec un bouton qui renvoie la même question. Le serveur l'arrondit (~1 km) et ne l'enregistre pas.
const LOCATION_ERRORS = {
    denied: "Position refusée : autorisez la localisation pour Pokebeer dans les réglages, ou citez une ville dans votre question.",
    unavailable: "Position introuvable. Citez une ville dans votre question.",
};
let pendingLocationMessage = null;  // la demande qui attend la position

function locationBubble(markdown) {
    return `
            <div class="chat chat-start">
                <div class="chat-bubble bg-primary text-black shadow-sm text-sm markdown-content">${renderMarkdown(markdown)}
                    <button type="button" class="btn btn-xs btn-outline mt-2 text-black border-black" data-chat-locate>Activer ma position</button>
                </div>
            </div>`;
}

async function locateAndResend(button) {
    const message = pendingLocationMessage;
    if (!message) return;
    if (!Pending.start(button)) return;
    const position = await PokebeerPosition.request();  // déclenche la demande d'autorisation du navigateur
    if (position.error) {
        Pending.stop(button);
        return addToChat(errorBubble(LOCATION_ERRORS[position.error]));
    }
    button.remove();
    sendMessage(message, { resend: true, position });
}

async function sendMessage(text, { resend = false, position = null } = {}) {
    const msg = (text ?? chatInput.value).trim();
    if (!msg || !Pending.start(chatSend)) return;  // bouton grisé avec un cercle ; un second envoi est ignoré

    document.getElementById('chat-suggestions')?.remove();
    if (!resend) addToChat(userBubble(msg));
    if (!resend) chatInput.value = '';

    const loadingId = 'loading-' + Date.now();
    addToChat(`
                <div id="${loadingId}" class="chat chat-start">
                    <div class="chat-bubble bg-primary text-black shadow-sm">
                        <span class="loading loading-dots loading-sm bg-black"></span>
                    </div>
                </div>`);

    try {
        const body = { message: msg };
        const location = position || await PokebeerPosition.silent();
        if (location) body.location = { lat: location.lat, lng: location.lng };
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
        const needsLocation = res.ok && data.needs_location === true;
        pendingLocationMessage = needsLocation ? msg : null;
        addToChat(!res.ok ? errorBubble(data.response) : needsLocation ? locationBubble(data.response) : modelBubble(data.response));
    } catch (err) {
        document.getElementById(loadingId)?.remove();
        addToChat(errorBubble("La cave est fermée, impossible de joindre Gaétan."));
    } finally {
        Pending.stop(chatSend);
    }
}

// Nouvelle conversation : le serveur oublie l'historique, la fenêtre retrouve l'accueil et ses questions de départ
chatReset.addEventListener('click', async () => {
    if (chatSend.disabled || !Pending.start(chatReset)) return;
    try {
        const res = await fetch(chatWindow.dataset.url, {
            method: 'DELETE',
            headers: { 'X-CSRFToken': document.querySelector('meta[name="csrf-token"]').content },
            credentials: 'same-origin'
        });
        if (!res.ok) throw new Error('reset');
        pendingLocationMessage = null;
        chatMessages.innerHTML = CHAT_WELCOME_HTML;
        chatInput.value = '';
    } catch (err) {
        addToChat(errorBubble("Impossible de réinitialiser la conversation. Réessayez."));
    } finally {
        Pending.stop(chatReset);
    }
});

chatSend.addEventListener('click', () => sendMessage());
chatInput.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.isComposing) sendMessage();
});
chatMessages.addEventListener('click', e => {
    const suggestion = e.target.closest('[data-chat-suggestion]');
    if (suggestion) sendMessage(suggestion.dataset.chatSuggestion);
    const locate = e.target.closest('[data-chat-locate]');
    if (locate) locateAndResend(locate);
});

document.addEventListener('DOMContentLoaded', async () => {
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
