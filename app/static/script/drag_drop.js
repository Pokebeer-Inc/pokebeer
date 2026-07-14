let draggedSlot = null;

function dragStart(event) {
    draggedSlot = event.currentTarget.dataset.slot;
    event.dataTransfer.setData('text/plain', draggedSlot);
    event.dataTransfer.effectAllowed = "move";
    
    const target = event.currentTarget;
    setTimeout(() => target.classList.add('opacity-40'), 0);
}

function dragOver(event) {
    event.preventDefault(); 
    event.dataTransfer.dropEffect = "move";
    
    const target = event.currentTarget;
    if (target.dataset.slot !== draggedSlot) {
        target.classList.add('ring-2', 'ring-primary', 'ring-offset-1');
    }
}

function dragLeave(event) {
    event.currentTarget.classList.remove('ring-2', 'ring-primary', 'ring-offset-1');
}

function drop(event) {
    event.preventDefault();
    const target = event.currentTarget;
    target.classList.remove('ring-2', 'ring-primary', 'ring-offset-1');
    
    const targetSlot = target.dataset.slot;

    if (draggedSlot && targetSlot && draggedSlot !== targetSlot) {
        
        fetch(window.DJANGO_URLS.swapTopBeers, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': window.CSRF_TOKEN
            },
            body: JSON.stringify({
                from_slot: draggedSlot,
                to_slot: targetSlot
            })
        })
        .then(res => {
            if (!res.ok) {
                throw new Error("Erreur réseau: " + res.status);
            }
            return res.json();
        })
        .then(data => {
            if(data.success) {
                location.reload(); 
            } else {
                alert("Erreur lors de l'échange.");
            }
        })
        .catch(err => console.error("Erreur lors du drag & drop:", err));
    }
}

function dragEnd(event) {
    event.currentTarget.classList.remove('opacity-40');
}