const chatToggle = document.getElementById('chat-toggle');
    const chatWindow = document.getElementById('chat-window');
    const chatClose = document.getElementById('chat-close');
    const chatInput = document.getElementById('chat-input');
    const chatMessages = document.getElementById('chat-messages');
    
    // Ouvrir / Fermer
    chatToggle.addEventListener('click', () => chatWindow.classList.toggle('hidden'));
    chatClose.addEventListener('click', () => chatWindow.classList.add('hidden'));
    
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
            const formattedResponse = data.response.replace(/\n/g, '<br>');
            
            chatMessages.innerHTML += `
                    <div class="chat chat-start">
                        <div class="chat-bubble chat-bubble-primary shadow-sm text-sm">${formattedResponse}</div>
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