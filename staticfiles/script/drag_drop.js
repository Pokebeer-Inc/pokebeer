let draggedSlot = null;

function dragStart(event) {
    draggedSlot = event.currentTarget.dataset.slot;
    // Nécessaire pour Firefox
    event.dataTransfer.setData('text/plain', draggedSlot);
    event.dataTransfer.effectAllowed = "move";
    
    // Ajoute un effet visuel de transparence sur l'élément en cours de déplacement
    setTimeout(() => event.currentTarget.classList.add('opacity-40'), 0);
}

function dragOver(event) {
    event.preventDefault(); // Indispensable pour autoriser le "drop"
    event.dataTransfer.dropEffect = "move";
    
    const target = event.currentTarget;
    // Si on survole un autre emplacement, on l'illumine
    if (target.dataset.slot !== draggedSlot) {
        target.classList.add('ring-2', 'ring-primary', 'ring-offset-1');
    }
}

function dragLeave(event) {
    // On retire l'illumination si on quitte la zone
    event.currentTarget.classList.remove('ring-2', 'ring-primary', 'ring-offset-1');
}

function drop(event) {
    event.preventDefault();
    const target = event.currentTarget;
    target.classList.remove('ring-2', 'ring-primary', 'ring-offset-1');
    
    const targetSlot = target.dataset.slot;

    // Si on a bien déposé sur un autre slot différent
    if (draggedSlot && targetSlot && draggedSlot !== targetSlot) {
        
        // On envoie la requête à notre API Django pour échanger
        fetch("{% url 'swap_top_beers' %}", {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': '{{ csrf_token }}' // Sécurité Django
            },
            body: JSON.stringify({
                from_slot: draggedSlot,
                to_slot: targetSlot
            })
        })
        .then(res => res.json())
        .then(data => {
            if(data.success) {
                location.reload(); // Recharge la page pour afficher le nouvel ordre
            } else {
                alert("Erreur lors de l'échange.");
            }
        })
        .catch(err => console.error(err));
    }
}

function dragEnd(event) {
    // Réinitialise la transparence une fois le clic relâché
    event.currentTarget.classList.remove('opacity-40');
}