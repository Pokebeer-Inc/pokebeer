const chatToggle = document.getElementById('chat-toggle');
const chatWindow = document.getElementById('chat-window');
const chatClose = document.getElementById('chat-close');
const chatInput = document.getElementById('chat-input');
const chatMessages = document.getElementById('chat-messages');
const chatOverlay = document.getElementById('chat-overlay'); 

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

// Appui sur "Entrée"
function handleEnter(e) {
    if (e.key === 'Enter') sendMessage();
}


// Appui sur "Entrée"
function handleEnter(e) {
    if (e.key === 'Enter') sendMessage();
}

async function sendMessage() {
    const msg = chatInput.value.trim();
    if (!msg) return;
    
    // 1. Afficher le message de l'utilisateur
    chatMessages.innerHTML += `
                <div class="chat chat-end">
                    <div class="chat-bubble shadow-sm text-sm">${msg}</div>
                </div>`;
    chatInput.value = '';
    chatMessages.scrollTop = chatMessages.scrollHeight;
    
    // 2. Afficher l'animation de chargement de Gaétan (modifié en jaune/noir)
    const loadingId = 'loading-' + Date.now();
    chatMessages.innerHTML += `
                <div id="${loadingId}" class="chat chat-start">
                    <div class="chat-bubble bg-primary text-black shadow-sm">
                        <span class="loading loading-dots loading-sm bg-black"></span>
                    </div>
                </div>`;
    chatMessages.scrollTop = chatMessages.scrollHeight;
    
    // 3. Appel API
    try {
        const chatUrl = chatWindow.dataset.url;
        const csrfToken = document.querySelector('meta[name="csrf-token"]').content;

        const res = await fetch(chatUrl, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': csrfToken
            },
            body: JSON.stringify({ message: msg })
        });
        
        const data = await res.json();
        const loadingElement = document.getElementById(loadingId);
        if (loadingElement) loadingElement.remove();
        
        // Formater la réponse pour gérer le Markdown
        const formattedResponse = marked.parse(data.response);
        
        chatMessages.innerHTML += `
            <div class="chat chat-start">
                <div class="chat-bubble bg-primary text-black shadow-sm text-sm markdown-content">${formattedResponse}</div>
            </div>`;
    } catch (err) {
        const loadingElement = document.getElementById(loadingId);
        if (loadingElement) loadingElement.remove();
        chatMessages.innerHTML += `
                    <div class="chat chat-start">
                        <div class="chat-bubble chat-bubble-error text-sm">La cave est fermée, impossible de joindre Gaétan.</div>
                    </div>`;
    }
    chatMessages.scrollTop = chatMessages.scrollHeight;
}

document.addEventListener('DOMContentLoaded', async () => {
    try {
        const chatUrl = chatWindow.dataset.url;
        const res = await fetch(chatUrl, {
            method: 'GET',
            headers: { 
                'X-Requested-With': 'XMLHttpRequest',
                'Accept': 'application/json'
            },
            credentials: 'same-origin' // Force l'envoi du cookie de session Django
        });
        
        if (res.ok) {
            const data = await res.json();
            
            // Si on a un historique, on remplace le contenu
            if (data.history && data.history.length > 0) {
                chatMessages.innerHTML = ''; // Efface le message par défaut
                
                data.history.forEach(msg => {
                    if (msg.role === 'user') {
                        chatMessages.innerHTML += `
                            <div class="chat chat-end">
                                <div class="chat-bubble shadow-sm text-sm">${msg.text}</div>
                            </div>`;
                    } else {
                        const formattedResponse = marked.parse(msg.text);
                        chatMessages.innerHTML += `
                            <div class="chat chat-start">
                                <div class="chat-bubble bg-primary text-black shadow-sm text-sm markdown-content">${formattedResponse}</div>
                            </div>`;
                    }
                });
                // Le scroll vers le bas se fera tout seul lorsque l'utilisateur cliquera sur le bouton d'ouverture
            }
        } else {
            console.error("Erreur API Historique : L'accès GET est probablement bloqué par Django (Vérifie @require_POST).");
        }
    } catch (err) {
        console.error("Erreur réseau lors de la récupération de l'historique :", err);
    }
});
