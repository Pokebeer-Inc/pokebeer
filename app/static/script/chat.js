const chatToggle = document.getElementById('chat-toggle');
const chatWindow = document.getElementById('chat-window');
const chatClose = document.getElementById('chat-close');
const chatInput = document.getElementById('chat-input');
const chatMessages = document.getElementById('chat-messages');
const chatOverlay = document.getElementById('chat-overlay'); // On cible le nouveau fond

// Ouvrir / Fermer le chat et le fond
chatToggle.addEventListener('click', () => {
    chatWindow.classList.toggle('hidden');
    chatOverlay.classList.toggle('hidden');
});

// Fermer avec la croix
chatClose.addEventListener('click', () => {
    chatWindow.classList.add('hidden');
    chatOverlay.classList.add('hidden');
});

// Fermer le chat si on clique sur le fond grisé
if (chatOverlay) {
    chatOverlay.addEventListener('click', () => {
        chatWindow.classList.add('hidden');
        chatOverlay.classList.add('hidden');
    });
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
    
    // 2. Afficher l'animation de chargement de Gaétan
    const loadingId = 'loading-' + Date.now();
    chatMessages.innerHTML += `
                <div id="${loadingId}" class="chat chat-start">
                    <div class="chat-bubble chat-bubble-primary shadow-sm">
                        <span class="loading loading-dots loading-sm"></span>
                    </div>
                </div>`;
    chatMessages.scrollTop = chatMessages.scrollHeight;
    
    // 3. Appel API
    try {
        const res = await fetch('/api/chat/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': _csrf_placeholder
            },
            body: JSON.stringify({ message: msg })
        });
        
        const data = await res.json();
        document.getElementById(loadingId).remove();
        
        // Formater la réponse pour gérer les sauts de ligne
        const formattedResponse = marked.parse(data.response);
        
        chatMessages.innerHTML += `
            <div class="chat chat-start">
                <div class="chat-bubble bg-primary text-black shadow-sm text-sm markdown-content">${formattedResponse}</div>
            </div>`;
    } catch (err) {
        document.getElementById(loadingId).remove();
        chatMessages.innerHTML += `
                    <div class="chat chat-start">
                        <div class="chat-bubble chat-bubble-error text-sm">La cave est fermée, impossible de joindre Gaétan.</div>
                    </div>`;
    }
    chatMessages.scrollTop = chatMessages.scrollHeight;
}

if (window.visualViewport) {
    window.visualViewport.addEventListener("resize", () => {
        const chatWindow = document.getElementById("chat-window");
        const chatToggle = document.getElementById("chat-toggle");
        
        // Calcul de la hauteur masquée par le clavier
        const offset = window.innerHeight - window.visualViewport.height;
        
        if (offset > 0) {
            // Clavier ouvert
            if (chatWindow && !chatWindow.classList.contains("hidden")) {
                chatWindow.style.bottom = `${offset + 10}px`;
                chatWindow.style.maxHeight = `${window.visualViewport.height - 20}px`;
            }
            if (chatToggle) {
                chatToggle.style.bottom = `${offset + 80}px`;
            }
        } else {
            // Clavier fermé (restauration des valeurs CSS par défaut)
            if (chatWindow) {
                chatWindow.style.bottom = ""; 
                chatWindow.style.maxHeight = "";
            }
            if (chatToggle) {
                chatToggle.style.bottom = ""; 
            }
        }
    });
}