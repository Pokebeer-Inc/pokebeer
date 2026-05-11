const chatToggle = document.getElementById('chat-toggle');
const chatWindow = document.getElementById('chat-window');
const chatClose = document.getElementById('chat-close');
const chatInput = document.getElementById('chat-input');
const chatMessages = document.getElementById('chat-messages');
const chatOverlay = document.getElementById('chat-overlay');

// Ouvrir / Fermer le chat et le fond
chatToggle.addEventListener('click', () => {
    chatWindow.classList.toggle('hidden');
    if (chatOverlay) chatOverlay.classList.toggle('hidden');
});

// Fermer avec la croix
chatClose.addEventListener('click', () => {
    chatWindow.classList.add('hidden');
    if (chatOverlay) chatOverlay.classList.add('hidden');
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
        const res = await fetch('/api/chat/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': _csrf_placeholder
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

// --- GESTION DU CLAVIER SUR MOBILE ---
const initialScreenHeight = window.innerHeight;

if (window.visualViewport) {
    window.visualViewport.addEventListener("resize", () => {
        const chatWindow = document.getElementById("chat-window");
        if (!chatWindow || chatWindow.classList.contains("hidden")) return;
        
        // Si la hauteur visible diminue de plus de 20%, on en déduit que le clavier est ouvert
        const isKeyboardOpen = window.visualViewport.height < (initialScreenHeight * 0.8);
        
        if (isKeyboardOpen) {
            // Clavier ouvert : on modifie la fenêtre pour qu'elle tienne au-dessus du clavier
            chatWindow.style.bottom = '10px'; 
            chatWindow.style.height = `${window.visualViewport.height - 20}px`;
        } else {
            // Clavier fermé : on retire nos modifications pour laisser Tailwind gérer
            chatWindow.style.bottom = '';
            chatWindow.style.height = '';
        }
        
        // On s'assure de toujours voir le dernier message
        setTimeout(() => {
            const chatMessages = document.getElementById("chat-messages");
            if (chatMessages) chatMessages.scrollTop = chatMessages.scrollHeight;
        }, 100);
    });
}