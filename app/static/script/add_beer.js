document.addEventListener("DOMContentLoaded", function() {
    // Icône SVG (constante du code) ajoutée au libellé du bouton
    const EXTERNAL_ICON = '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" class="inline-block ml-1"><path d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14"/></svg>';
    
    // --- 1. LOGIQUE D'AUTOCOMPLÉTION (DRY) ---
    // `termOf` : partie de la saisie qu'on cherche (par défaut tout) ; `minLength` : longueur à partir de laquelle on interroge le serveur
    function setupAutocomplete(inputId, suggId, apiPath, renderItem, onSelect, { termOf = value => value, minLength = 2 } = {}) {
        const input = document.getElementById(inputId);
        const suggContainer = document.getElementById(suggId);
        
        if (!input || !suggContainer) return;

        input.addEventListener("input", async function() {
            const val = termOf(this.value);
            suggContainer.innerHTML = '';
            // Valeur posée par un choix dans la liste : les autres contrôles (doublons) sont prévenus, mais la liste ne se rouvre pas
            if (this.dataset.picked) {
                delete this.dataset.picked;
                suggContainer.classList.add('hidden');
                return;
            }
            
            if (val.length < minLength) {
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
            // Le lieu distingue deux brasseries de même nom ; noms et lieux viennent d'autres membres : toujours en texte, jamais en HTML
            div.className = "p-3 bg-base-100 hover:bg-base-200 cursor-pointer border-b border-base-200 flex justify-between items-center gap-2";
            const name = document.createElement("span");
            name.className = "font-semibold";
            name.textContent = item.name;
            div.appendChild(name);
            if (item.place) {
                const place = document.createElement("span");
                place.className = "text-xs text-gray-500 shrink-0";
                place.textContent = item.place;
                div.appendChild(place);
            }
        },
        (item, container, input) => {
            input.value = item.name;
            container.innerHTML = '';
            container.classList.add('hidden');
            input.dataset.picked = '1';
            input.dispatchEvent(new Event('input')); // efface la brasserie retenue (voir plus bas), puis on retient celle-ci
            if (slugField) slugField.value = item.slug;
        }
    );

    // Initialisation : styles du référentiel. Le champ accepte plusieurs styles séparés par des virgules : on suggère pour le dernier mot saisi
    setupAutocomplete(
        'id_beer-style',
        'style-suggestions',
        '/api/search-style/',
        (div, item) => {
            // Noms et familles viennent du référentiel de l'équipe, mais restent affichés en texte (jamais en HTML)
            div.className = "p-3 bg-base-100 hover:bg-base-200 cursor-pointer border-b border-base-200 flex justify-between items-center gap-2";
            const name = document.createElement("span");
            name.className = "font-semibold";
            name.textContent = item.name;
            const family = document.createElement("span");
            family.className = "text-xs text-gray-500 shrink-0";
            family.textContent = item.family;
            div.append(name, family);
        },
        (item, container, input) => {
            const parts = input.value.split(',');
            parts[parts.length - 1] = ' ' + item.name;
            input.value = parts.join(',').trim();
            container.innerHTML = '';
            container.classList.add('hidden');
            input.dataset.picked = '1';
            input.dispatchEvent(new Event('input'));
            input.focus();  // on peut enchaîner avec un second style (« , »)
        },
        { termOf: value => value.split(',').pop().trim(), minLength: 1 }
    );

    // La brasserie choisie dans la liste est retenue par son identifiant (le nom seul ne distingue pas deux homonymes) ; retaper le nom l'oublie
    const slugField = document.getElementById('id_beer-brewery_slug');
    const breweryInput = document.getElementById('id_beer-brewery_name');
    if (slugField && breweryInput) breweryInput.addEventListener('input', () => { slugField.value = ''; });

    // Le scan d'étiquette (caméra en direct ou photo) vit dans label_scan_page.js et ses modules.
});
