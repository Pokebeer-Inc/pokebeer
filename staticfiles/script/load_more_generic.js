document.addEventListener('DOMContentLoaded', function() {
    
    const loadMoreButtons = document.querySelectorAll('.btn-load-more-generic');

    // 1. Configuration de l'observateur (IntersectionObserver)
    const observerOptions = {
        root: null, // Observe par rapport à la fenêtre du navigateur
        rootMargin: '0px 0px 30px 0px', // Déclenche l'événement 30px AVANT que le bouton ne soit visible
        threshold: 0.1
    };

    const observer = new IntersectionObserver((entries, observer) => {
        entries.forEach(entry => {
            // Si le bouton entre dans la zone ET qu'il n'est pas déjà en train de charger
            if (entry.isIntersecting && !entry.target.disabled) {
                entry.target.click(); // On simule un clic utilisateur
            }
        });
    }, observerOptions);

    // 2. Initialisation des événements pour chaque bouton
    loadMoreButtons.forEach(btn => {
        
        // A. La logique de chargement (le clic)
        btn.addEventListener('click', function() {
            if (this.disabled) return; // Double sécurité anti-spam
            
            const offset = parseInt(this.dataset.offset);
            const containerId = this.dataset.container;
            const originalText = this.innerHTML;
            
            // État visuel de chargement
            this.innerHTML = '<span class="loading loading-spinner loading-xs"></span> Chargement...';
            this.disabled = true;

            // 1. On initialise un véritable objet URL basé sur le data-url du bouton
            const fetchUrl = new URL(this.dataset.url, window.location.origin);
            
            // 2. On récupère les filtres éventuels de la page actuelle (barre de recherche, tris...)
            const currentParams = new URLSearchParams(window.location.search);
            
            // 3. On injecte proprement ces filtres, SANS écraser ceux du bouton (ex: username ou source)
            currentParams.forEach((value, key) => {
                if (!fetchUrl.searchParams.has(key)) {
                    fetchUrl.searchParams.set(key, value);
                }
            });
            
            // 4. On écrase spécifiquement l'offset
            fetchUrl.searchParams.set('offset', offset);

            // On lance la requête avec l'URL parfaitement formattée
            fetch(fetchUrl.toString())
            .then(res => {
                if(!res.ok) throw new Error("Erreur réseau");
                return res.json();
            })
            .then(data => {
                if (data.html) {
                    document.getElementById(containerId).insertAdjacentHTML('beforeend', data.html);
                    this.dataset.offset = offset + 10;
                }
                
                // S'il n'y a plus de résultats
                if (!data.has_more) {
                    observer.unobserve(this); // On arrête de surveiller ce bouton
                    this.remove();            // On le supprime
                } else {
                    // On restaure le bouton
                    this.innerHTML = originalText;
                    this.disabled = false;
                }
            })
            .catch(err => {
                console.error("Erreur de chargement:", err);
                this.innerHTML = originalText;
                this.disabled = false;
            });
        });

        // B. On demande à l'observateur de surveiller ce bouton (si activé)
        if (btn.dataset.autoscroll !== "false") {
            observer.observe(btn);
        }
    });
});