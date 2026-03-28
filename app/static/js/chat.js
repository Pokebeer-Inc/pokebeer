// Fonction pour récupérer le token CSRF de Django
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

function toggleChat() {
    var box = document.getElementById("chat-box");
    box.style.display = (box.style.display === "none" || box.style.display === "") ? "flex" : "none";
}

function handleEnter(e) {
    if (e.key === "Enter") sendMessage();
}

async function sendMessage() {
    const input = document.getElementById("chat-input");
    const logs = document.getElementById("chat-logs");
    const msg = input.value.trim();
    
    if (!msg) return;

    // Affichage user
    logs.innerHTML += `<div class="chat-msg user">${msg}</div>`;
    input.value = "";
    logs.scrollTop = logs.scrollHeight;

    // Loader
    const loaderId = "loader-" + Date.now();
    logs.innerHTML += `<div id="${loaderId}" class="chat-msg bot loading">Le sommelier réfléchit... 🍺</div>`;
    logs.scrollTop = logs.scrollHeight;

    try {
        // Récupération du token CSRF
        const csrftoken = getCookie('csrftoken');

        // Appel Django
        const response = await fetch("/api/chat/", {  // Notez le slash à la fin pour Django
            method: "POST",
            headers: { 
                "Content-Type": "application/json",
                "X-CSRFToken": csrftoken // Indispensable pour Django
            },
            body: JSON.stringify({ message: msg })
        });

        if (!response.ok) throw new Error("Erreur réseau");

        const data = await response.json();
        
        document.getElementById(loaderId).remove();
        const formattedResponse = data.response.replace(/\n/g, "<br>");
        logs.innerHTML += `<div class="chat-msg bot">${formattedResponse}</div>`;
        
    } catch (error) {
        if(document.getElementById(loaderId)) document.getElementById(loaderId).remove();
        logs.innerHTML += `<div class="chat-msg bot" style="color:red">Erreur technique :/</div>`;
        console.error(error);
    }
    logs.scrollTop = logs.scrollHeight;
}