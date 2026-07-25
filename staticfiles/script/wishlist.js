function toggleWishlist(event, beerId) {
    event.preventDefault();
    event.stopPropagation(); // Évite de cliquer sur la carte en arrière-plan
    
    // Récupération sécurisée du token CSRF
    const csrfToken = document.querySelector('[name=csrfmiddlewaretoken]') ? 
                      document.querySelector('[name=csrfmiddlewaretoken]').value : 
                      (window.CSRF_TOKEN || '');
    
    fetch(`/beer/${beerId}/wishlist/`, {
        method: 'POST',
        headers: {
            'X-CSRFToken': csrfToken,
            'Content-Type': 'application/json'
        }
    })
    .then(res => res.json())
    .then(data => {
        if(data.success) {
            // Met à jour toutes les icônes de cette bière sur la page
            const icons = document.querySelectorAll(`#wishlist-icon-${beerId}`);
            icons.forEach(icon => {
                if(data.is_in_wishlist) {
                    icon.setAttribute('fill', 'currentColor');
                } else {
                    icon.setAttribute('fill', 'none');
                }
            });
        }
    })
    .catch(err => console.error("Erreur Wishlist:", err));
}