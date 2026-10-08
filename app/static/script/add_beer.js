document.addEventListener("DOMContentLoaded", function() {
    // Icône SVG (constante du code) ajoutée au libellé du bouton
    const EXTERNAL_ICON = '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" class="inline-block ml-1"><path d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14"/></svg>';
    
    // --- 1. LOGIQUE D'AUTOCOMPLÉTION (DRY) ---
    function setupAutocomplete(inputId, suggId, apiPath, renderItem, onSelect) {
        const input = document.getElementById(inputId);
        const suggContainer = document.getElementById(suggId);
        
        if (!input || !suggContainer) return;

        input.addEventListener("input", async function() {
            const val = this.value;
            suggContainer.innerHTML = '';
            
            if (val.length < 2) {
                suggContainer.classList.add('hidden');
                return;
            }
            
            try {
                const response = await fetch(`${apiPath}?term=${encodeURIComponent(val)}`);
                const data = await response.json();
                
                if (data.length > 0) {
                    suggContainer.classList.remove('hidden');
                    data.forEach(item => {
                        const div = document.createElement("div");
                        renderItem(div, item);
                        div.addEventListener("click", () => onSelect(item, suggContainer, input));
                        suggContainer.appendChild(div);
                    });
                } else {
                    suggContainer.classList.add('hidden');
                }
            } catch (error) {
                console.error(`Erreur API ${apiPath}`, error);
            }
        });

        // Fermer les suggestions au clic extérieur
        document.addEventListener("click", function (e) {
            if (e.target !== input) suggContainer.classList.add('hidden');
        });
    }

    // Initialisation : Suggestions de bières
    setupAutocomplete(
        'id_beer-name', 
        'beer-suggestions', 
        '/api/search-beer/',
        (div, item) => {
            div.className = "p-3 bg-error/10 hover:bg-error/20 cursor-pointer border-b border-error/20 flex justify-between items-center text-error transition-colors";
            // Les noms viennent d'autres membres : toujours en texte (textContent), jamais en HTML
            const label = document.createElement("div");
            const name = document.createElement("span");
            name.className = "font-bold text-lg";
            name.textContent = item.name;
            const stock = document.createElement("span");
            stock.className = "text-sm opacity-80 block";
            stock.textContent = `Déjà en stock (${item.brewery})`;
            label.append(name, stock);
            const action = document.createElement("span");
            action.className = "btn btn-sm btn-error text-white shadow-sm";
            action.textContent = "Aller la noter";
            action.insertAdjacentHTML("beforeend", EXTERNAL_ICON);
            div.append(label, action);
        },
        (item) => window.location.href = `/beer/${item.slug}/`
    );

    // Initialisation : Suggestions de brasseries
    setupAutocomplete(
        'id_beer-brewery_name', 
        'brewery-suggestions', 
        '/api/search-brewery/',
        (div, item) => {
            div.className = "p-3 bg-base-100 hover:bg-base-200 cursor-pointer border-b border-base-200 font-semibold";
            div.textContent = item;
        },
        (item, container, input) => {
            input.value = item;
            container.innerHTML = '';
            container.classList.add('hidden');
            input.dispatchEvent(new Event('input'));
        }
    );

    // Le scan d'étiquette (caméra en direct ou photo) vit dans label_scan_page.js et ses modules.
});
