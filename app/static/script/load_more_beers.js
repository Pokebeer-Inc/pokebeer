document.addEventListener('DOMContentLoaded', function() {
    const btnLoadMore = document.getElementById('btn-load-more');

    // On s'assure que le bouton existe avant d'ajouter l'événement
    if (btnLoadMore) {
        btnLoadMore.addEventListener('click', function() {
            const btn = this;
            const offset = parseInt(btn.dataset.offset);
            const originalText = btn.innerHTML;
            
            // État visuel de chargement
            btn.innerHTML = '<span class="loading loading-spinner loading-xs"></span> Chargement...';
            btn.disabled = true;

            // Utilisation de l'URL passée depuis le HTML
            const fetchUrl = `${window.LOAD_MORE_URL}?offset=${offset}`;

            fetch(fetchUrl)
            .then(res => {
                if(!res.ok) throw new Error("Erreur réseau");
                return res.json();
            })
            .then(data => {
                // Insérer le HTML généré à la fin de la liste
                if (data.html) {
                    document.getElementById('unrated-beers-container').insertAdjacentHTML('beforeend', data.html);
                    btn.dataset.offset = offset + 10; // Prépare le prochain lot
                }
                
                // Si on a atteint la fin des bières
                if (!data.has_more) {
                    btn.remove();
                } else {
                    // Restaure le bouton pour un prochain clic
                    btn.innerHTML = originalText;
                    btn.disabled = false;
                }
            })
            .catch(err => {
                console.error("Erreur de chargement des bières:", err);
                btn.innerHTML = originalText;
                btn.disabled = false;
            });
        });
    }
});