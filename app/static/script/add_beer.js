document.addEventListener("DOMContentLoaded", function() {
    
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
            action.textContent = "Aller la noter ↗";
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

    // --- 2. LOGIQUE DU SCANNER D'ÉTIQUETTE ---
    const scanBtn = document.getElementById('scan-label-btn');
    const cameraInput = document.getElementById('camera-input');
    const scanLoader = document.getElementById('scan-loader');

    if (scanBtn && cameraInput) {
        // Récupération de l'URL passée depuis Django
        const apiUrl = scanBtn.getAttribute('data-url');

        scanBtn.addEventListener('click', () => cameraInput.click());

        cameraInput.addEventListener('change', function(event) {
            const file = event.target.files[0];
            if (!file) return;

            scanLoader.classList.remove('hidden');
            scanBtn.disabled = true;

            const reader = new FileReader();
            reader.onload = function(e) {
                const img = new Image();
                img.onload = function() {
                    const canvas = document.createElement('canvas');
                    const MAX_WIDTH = 800;
                    let width = img.width;
                    let height = img.height;

                    if (width > MAX_WIDTH) {
                        height *= MAX_WIDTH / width;
                        width = MAX_WIDTH;
                    }
                    
                    canvas.width = width;
                    canvas.height = height;
                    const ctx = canvas.getContext('2d');
                    ctx.drawImage(img, 0, 0, width, height);

                    canvas.toBlob(function(blob) {
                        const formData = new FormData();
                        formData.append('image', blob, 'label.jpg');

                        const csrfToken = document.querySelector('[name=csrfmiddlewaretoken]').value;

                        fetch(apiUrl, {
                            method: 'POST',
                            body: formData,
                            headers: {
                                'X-CSRFToken': csrfToken
                            }
                        })
                        .then(response => response.json())
                        .then(result => {
                            if (result.success) {
                                const data = result.data;
                                
                                // Utilitaire pour remplir et formater proprement un champ
                                const fillField = (id, val, formatName = false) => {
                                    if (val) {
                                        const field = document.getElementById(id);
                                        if (field) {
                                            field.value = formatName ? val.charAt(0).toUpperCase() + val.slice(1).toLowerCase() : val;
                                            field.dispatchEvent(new Event('input'));
                                        }
                                    }
                                };

                                fillField('id_beer-name', data.name, true);
                                fillField('id_beer-brewery_name', data.brewery, true);
                                fillField('id_beer-style', data.style);
                                fillField('id_beer-degree', data.degree);
                                fillField('id_beer-bitterness', data.bitterness);

                                // La photo prise pour l'analyse illustre aussi l'avis ; le membre peut la changer ou la retirer
                                window.ImageFields.preset(
                                    document.getElementById('id_drink-photo'),
                                    new File([blob], 'tasting.jpg', { type: 'image/jpeg' })
                                );
                                
                            } else {
                                alert("Erreur: " + result.error);
                            }
                        })
                        .catch(error => {
                            console.error("Erreur réseau:", error);
                            alert("Impossible de joindre le serveur d'analyse.");
                        })
                        .finally(() => {
                            scanLoader.classList.add('hidden');
                            scanBtn.disabled = false;
                            cameraInput.value = '';
                        });

                    }, 'image/jpeg', 0.8);
                };
                img.src = e.target.result;
            };
            reader.readAsDataURL(file);
        });
    }

});