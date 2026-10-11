async function toggleWishlist(event, beerSlug) {
    event.preventDefault();
    event.stopPropagation(); // Évite de cliquer sur la carte en arrière-plan
    const button = event.currentTarget;  // lu tout de suite : il n'est plus disponible après l'attente

    // Récupération sécurisée du token CSRF
    const csrfToken = document.querySelector('[name=csrfmiddlewaretoken]') ?
                      document.querySelector('[name=csrfmiddlewaretoken]').value :
                      (window.CSRF_TOKEN || '');

    // Le bouton est grisé avec un cercle qui tourne le temps de la requête (un second appui est ignoré)
    await Pending.run(button, async () => {
        try {
            const response = await fetch(`/beer/${beerSlug}/wishlist/`, {
                method: 'POST',
                headers: { 'X-CSRFToken': csrfToken, 'Content-Type': 'application/json' }
            });
            const data = await response.json();
            if (data.success) {
                // Met à jour toutes les icônes de cette bière sur la page
                document.querySelectorAll(`#wishlist-icon-${beerSlug}`).forEach(icon => {
                    icon.setAttribute('fill', data.is_in_wishlist ? 'currentColor' : 'none');
                });

                // On lève un drapeau dans la session pour prévenir les autres pages que les données ont changé
                sessionStorage.setItem('db_state_changed', 'true');
            }
        } catch (error) {
            console.error("Erreur Wishlist:", error);
        }
    });
}
