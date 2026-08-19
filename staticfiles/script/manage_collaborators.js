let searchTimeout;
    
function searchUsersForCollab() {
    clearTimeout(searchTimeout);
    
    const inputEl = document.getElementById('search-collab');
    const input = inputEl.value.trim();
    const container = document.getElementById('search-results-container');

    // Récupération des valeurs dynamiques générées par Django
    const searchUrl = inputEl.dataset.searchUrl;
    const addUrl = inputEl.dataset.addUrl;
    const csrfToken = inputEl.dataset.csrfToken;

    if (input.length < 2) {
        container.innerHTML = '<p class="text-xs text-gray-500 italic text-center py-2">Tapez au moins 2 caractères...</p>';
        return;
    }

    // Affiche un loader pendant la recherche
    container.innerHTML = '<div class="flex justify-center py-4"><span class="loading loading-spinner text-primary"></span></div>';

    // Lance la recherche AJAX après 300ms
    searchTimeout = setTimeout(() => {
        fetch(`${searchUrl}?q=${encodeURIComponent(input)}`)
        .then(res => res.json())
        .then(data => {
            if (data.users && data.users.length > 0) {
                container.innerHTML = data.users.map(u => `
                    <div class="collab-item flex justify-between items-center py-2 border-b border-base-200 last:border-0">
                        
                        <div class="flex items-center gap-3">
                            <div class="avatar">
                                <div class="w-8 h-8 rounded-full border border-base-300 overflow-hidden shadow-inner">
                                    <img src="${u.avatar_url}" class="object-cover" />
                                </div>
                            </div>
                            <a href="/user/${u.username}/" class="text-sm font-semibold hover:text-primary transition-colors">${u.username}</a>
                        </div>
                        
                        <!-- Le formulaire utilise l'URL et le Token récupérés via data-* -->
                        <form method="post" action="${addUrl}">
                            <input type="hidden" name="csrfmiddlewaretoken" value="${csrfToken}">
                            <input type="hidden" name="user_id" value="${u.id}">
                            <button type="submit" class="btn btn-xs btn-primary btn-outline">Ajouter</button>
                        </form>
                    </div>
                `).join('');
            } else {
                container.innerHTML = '<p class="text-xs text-gray-500 italic text-center py-2">Aucun utilisateur trouvé.</p>';
            }
        })
        .catch(err => {
            container.innerHTML = '<p class="text-xs text-error italic text-center py-2">Erreur lors de la recherche.</p>';
        });
    }, 300);
}