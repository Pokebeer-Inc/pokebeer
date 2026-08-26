document.addEventListener("DOMContentLoaded", function() {
    let movingMarker = null;
    let mapInstance = null;
    let isMovingMode = false;
    
    // 1. Initialisation de la carte
    const map = L.map('map', {zoomControl: false}).setView([46.603354, 1.888334], 5);
    L.control.zoom({ position: 'bottomleft' }).addTo(map);
    L.tileLayer('https://{s}.tile.openstreetmap.fr/osmfr/{z}/{x}/{y}.png', {
        maxZoom: 19,
        attribution: '&copy; OpenStreetMap France'
    }).addTo(map);

    new ResizeObserver(() => {
        map.invalidateSize();
    }).observe(document.getElementById('map'));

    mapInstance = map;

    const brownIcon = new L.Icon({
        iconUrl: 'https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-2x-gold.png',
        shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/0.7.7/images/marker-shadow.png',
        iconSize: [25, 41],
        iconAnchor: [12, 41],
        popupAnchor: [1, -34],
        shadowSize: [41, 41]
    });

    const breweryIcon = new L.Icon({
        iconUrl: 'https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-2x-orange.png',
        shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/0.7.7/images/marker-shadow.png',
        iconSize: [25, 41],
        iconAnchor: [12, 41],
        popupAnchor: [1, -34],
        shadowSize: [41, 41]
    });

    const barIcon = new L.Icon({
        iconUrl: 'https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-2x-red.png',
        shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/0.7.7/images/marker-shadow.png',
        iconSize: [25, 41],
        iconAnchor: [12, 41],
        popupAnchor: [1, -34],
        shadowSize: [41, 41]
    });

    // 2. Extraction des données préparées par Django dans le HTML caché
    const spotsContainer = document.getElementById('spots-data-container');
    const spotsData = {};
    const mapBounds = [];

    if (spotsContainer) {
        document.querySelectorAll('.spot-data-item').forEach(item => {
            const id = item.dataset.id;
            const lat = parseFloat(item.dataset.lat);
            const lng = parseFloat(item.dataset.lng);
            // On récupère le design HTML du popup déjà formaté par Django
            const popupHtml = item.querySelector('.popup-template').innerHTML;
            
            spotsData[id] = {
                id: id,
                title: item.dataset.title,
                description: item.dataset.desc,
                date: item.dataset.dateVal,
                lat: lat,
                lng: lng,
                is_owner: item.dataset.isOwner === 'true',
                // Nettoyage des chaînes "id1,id2," en vrais tableaux JavaScript
                drink_ids: item.dataset.drinkIds.split(',').filter(Boolean),
                other_beer_ids: item.dataset.otherBeerIds.split(',').filter(Boolean),
                friend_ids: item.dataset.friendIds.split(',').filter(Boolean)
            };

            // Ajout direct du marqueur sur la carte
            const marker = L.marker([lat, lng], {icon: brownIcon}).addTo(map);
            marker.bindPopup(popupHtml);
            mapBounds.push([lat, lng]);
        });
    }

    // Chargement des Bars et Brasseries
    const placesContainer = document.getElementById('places-data-container');
    if (placesContainer) {
        document.querySelectorAll('.place-data-item').forEach(item => {
            const lat = parseFloat(item.dataset.lat);
            const lng = parseFloat(item.dataset.lng);
            const type = item.dataset.type;
            const url = item.dataset.url;
            const name = item.dataset.name;

            const icon = type === 'bar' ? barIcon : breweryIcon;
            
            const marker = L.marker([lat, lng], {icon: icon, title: name}).addTo(map);
            mapBounds.push([lat, lng]);
            
            // Événement au clic : Ouverture de la modale et chargement du contenu
            marker.on('click', function() {
                const modal = document.getElementById('modal_place');
                const contentDiv = document.getElementById('modal_place_content');
                
                // Affiche le loader
                contentDiv.innerHTML = '<div class="flex justify-center p-20"><span class="loading loading-spinner text-primary loading-lg"></span></div>';
                modal.showModal();

                // Aspire la page ciblée
                fetch(url)
                    .then(response => response.text())
                    .then(html => {
                        // Transforme le texte HTML en vrai document parcourable
                        const parser = new DOMParser();
                        const doc = parser.parseFromString(html, 'text/html');
                        
                        // Extrait UNIQUEMENT le contenu utile (le block content) pour éviter les doublons de navbar
                        const extractedContent = doc.querySelector('.p-4.flex-1.mb-16');
                        
                        if (extractedContent) {
                            contentDiv.innerHTML = extractedContent.innerHTML;
                            
                            // UX 1 : Cache le bouton "Retour" natif de la page aspirée puisqu'on a déjà la croix de la modale
                            const backBtn = contentDiv.querySelector('a[href="javascript:history.back()"]');
                            if (backBtn) backBtn.style.display = 'none';

                            // UX 2 : Supprime la mini-carte pour éviter une redondance sur la page map
                            const miniMap = contentDiv.querySelector('#place-map');
                            if (miniMap) miniMap.parentElement.remove();
                            
                        } else {
                            contentDiv.innerHTML = '<p class="text-center p-10 text-error">Erreur lors du chargement des données.</p>';
                        }
                    })
                    .catch(err => {
                        console.error('Erreur Fetch:', err);
                        contentDiv.innerHTML = '<p class="text-center p-10 text-error">Impossible de joindre le serveur.</p>';
                    });
            });
        });
    }

    // Centrage automatique sur tous les points
    if (mapBounds.length > 0) {
        map.fitBounds(mapBounds, { maxZoom: 5, padding: [30, 30] }); 
    }

    // Gestion de l'ouverture de la modale d'édition
    window.openEditModal = function(spotId) {
        const data = spotsData[spotId];
        if (!data) return;

        document.getElementById('modal-title').innerText = "Modifier le lieu";
        document.getElementById('spot-id').value = data.id;
        document.getElementById('spot-title').value = data.title;
        document.getElementById('spot-desc').value = data.description;
        document.getElementById('spot-date').value = data.date;
        document.getElementById('spot-lat').value = data.lat;
        document.getElementById('spot-lng').value = data.lng;

        // Gestion de l'affichage des bières
        document.querySelectorAll('.drink-item').forEach(item => {
            const isDeleted = item.getAttribute('data-is-deleted') === 'true';
            const drinkId = item.getAttribute('data-drink-id');
            
            item.style.display = (!isDeleted || data.drink_ids.includes(drinkId)) ? 'flex' : 'none';
        });

        // Gestion du cochage / grisage des bières
        document.querySelectorAll('.drink-checkbox').forEach(cb => {
            const beerId = cb.getAttribute('data-beer-id');
            cb.checked = data.drink_ids.includes(cb.value);
            
            if (data.other_beer_ids.includes(beerId)) {
                cb.disabled = true;
                cb.parentElement.classList.add('opacity-50', 'cursor-not-allowed');
            } else {
                cb.disabled = false;
                cb.parentElement.classList.remove('opacity-50', 'cursor-not-allowed');
            }
        });

        // Gestion des droits (créateur)
        const friendsSection = document.getElementById('friends-section');
        const deleteForm = document.getElementById('form-delete-spot');
        
        if (data.is_owner) {
            friendsSection.style.display = 'block';
            document.querySelectorAll('.friend-checkbox').forEach(cb => {
                cb.checked = data.friend_ids.includes(cb.value);
            });
            deleteForm.action = `/delete-spot/${spotId}/`;
            deleteForm.style.display = "block";
        } else {
            friendsSection.style.display = 'none';
            deleteForm.style.display = "none";
        }

        document.getElementById('modal_add_spot').showModal();
    };

    // 4. Clique sur la carte (Création d'un NOUVEAU point)
    map.on('click', function(e) {
        if (isMovingMode) return;

        document.getElementById('modal-title').innerText = "Ajouter un lieu";
        document.getElementById('spot-id').value = ""; 
        document.getElementById('spot-title').value = "";
        document.getElementById('spot-desc').value = "";
        
        const today = new Date().toISOString().split('T')[0];
        document.getElementById('spot-date').value = today;
        
        document.getElementById('spot-lat').value = e.latlng.lat.toFixed(6);
        document.getElementById('spot-lng').value = e.latlng.lng.toFixed(6);

        // Remise à zéro des champs
        document.querySelectorAll('.friend-checkbox').forEach(cb => cb.checked = false);
        document.querySelectorAll('.drink-checkbox').forEach(cb => {
            cb.checked = false;
            cb.disabled = false;
            cb.parentElement.classList.remove('opacity-50', 'cursor-not-allowed');
        });
        document.querySelectorAll('.drink-item').forEach(item => {
            item.style.display = item.getAttribute('data-is-deleted') === 'true' ? 'none' : 'flex';
        });
        
        document.getElementById('form-delete-spot').style.display = 'none';
        document.getElementById('friends-section').style.display = 'block';

        document.getElementById('modal_add_spot').showModal();
    });

    // 5. Gestion de la géolocalisation
    let userMarker = null;
    let geoWatchId = null;

    const userIcon = L.divIcon({
        className: 'custom-user-icon',
        html: `<div class="bg-primary text-white rounded-full w-8 h-8 flex items-center justify-center border-2 border-white shadow-md">
                <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" viewBox="0 0 20 20" fill="currentColor">
                    <path fill-rule="evenodd" d="M10 9a3 3 0 100-6 3 3 0 000 6zm-7 9a7 7 0 1114 0H3z" clip-rule="evenodd" />
                </svg>
               </div>`,
        iconSize: [32, 32],
        iconAnchor: [16, 16],
        popupAnchor: [0, -16]
    });

    const geolocBtn = document.getElementById('geoloc-btn');
    if (geolocBtn) {
        geolocBtn.addEventListener('click', function() {
            if(navigator.geolocation) {
                const originalHtml = this.innerHTML;
                
                // Si la localisation est déjà active, on se contente de recentrer la carte
                if (geoWatchId !== null && userMarker) {
                    map.setView(userMarker.getLatLng(), 16);
                    return;
                }

                // On affiche le loader
                this.innerHTML = '<span class="loading loading-spinner loading-xs"></span>';
                
                // watchPosition suit l'utilisateur en temps réel
                geoWatchId = navigator.geolocation.watchPosition((position) => {
                    const lat = position.coords.latitude;
                    const lng = position.coords.longitude;
                    
                    // Restaure le bouton et centre la carte uniquement lors du tout premier fix
                    if (this.innerHTML !== originalHtml) {
                        this.innerHTML = originalHtml;
                        map.setView([lat, lng], 16);
                    }

                    // Crée le marqueur "bonhomme" s'il n'existe pas, ou déplace-le s'il existe déjà
                    if (!userMarker) {
                        userMarker = L.marker([lat, lng], {
                            icon: userIcon, 
                            zIndexOffset: 9999 // S'assure qu'il passe au-dessus des autres points
                        }).addTo(map);
                        userMarker.bindPopup("<div class='text-center font-bold text-primary mb-0'>Vous êtes ici</div>");
                    } else {
                        userMarker.setLatLng([lat, lng]);
                    }
                }, (error) => {
                    console.error("Erreur de géolocalisation:", error);
                    this.innerHTML = originalHtml;
                }, {
                    enableHighAccuracy: true,
                    maximumAge: 0,
                    timeout: 20000
                });
            }
        });
    }

    // --- Fonctions globales (Accessibles par les boutons HTML de la modale) ---
    
    window.updateToCurrentLocation = function() {
        if(navigator.geolocation) {
            navigator.geolocation.getCurrentPosition(function(position) {
                const latInput = document.getElementById('spot-lat');
                const lngInput = document.getElementById('spot-lng');
                latInput.value = position.coords.latitude.toFixed(6);
                lngInput.value = position.coords.longitude.toFixed(6);
                
                // Effet visuel
                latInput.classList.add('bg-success/20');
                setTimeout(() => latInput.classList.remove('bg-success/20'), 1000);
            });
        }
    };

    window.startMoveMode = function() {
        isMovingMode = true;
        const lat = parseFloat(document.getElementById('spot-lat').value);
        const lng = parseFloat(document.getElementById('spot-lng').value);

        document.getElementById('modal_add_spot').close();
        document.getElementById('move-overlay').classList.remove('-translate-y-full');

        mapInstance.setView([lat, lng], 17);

        movingMarker = L.marker([lat, lng], {
            icon: brownIcon,
            draggable: true,
            zIndexOffset: 1000
        }).addTo(mapInstance);

        movingMarker.bindTooltip("Faites-moi glisser !", {permanent: true, direction: 'top', offset: [0,-40]}).openTooltip();
    };

    window.finishMoveMode = function() {
        if (movingMarker) {
            const newPos = movingMarker.getLatLng();
            document.getElementById('spot-lat').value = newPos.lat.toFixed(6);
            document.getElementById('spot-lng').value = newPos.lng.toFixed(6);
            
            cleanupMoveMode();
            document.getElementById('modal_add_spot').showModal();
        }
    };

    window.cancelMoveMode = function() {
        cleanupMoveMode();
        document.getElementById('modal_add_spot').showModal();
    };

    function cleanupMoveMode() {
        isMovingMode = false;
        if (movingMarker) {
            mapInstance.removeLayer(movingMarker);
            movingMarker = null;
        }
        document.getElementById('move-overlay').classList.add('-translate-y-full');
    }

    // --- MOTEUR DE RECHERCHE DE LIEUX (Nominatim) ---
    let searchMarker = null;

    window.searchLocation = async function() {
        const query = document.getElementById('map-search-input').value.trim();
        const resultsContainer = document.getElementById('map-search-results');
        
        // Empêche les requêtes inutiles pour 1 ou 2 lettres
        if (query.length < 3) {
            resultsContainer.classList.add('hidden');
            return;
        }

        // Affichage du loader pendant la recherche
        resultsContainer.innerHTML = '<li class="p-2 flex justify-center"><span class="loading loading-spinner text-primary loading-sm"></span></li>';
        resultsContainer.classList.remove('hidden');

        try {
            // Appel à l'API gratuite OpenStreetMap
            const response = await fetch(`https://nominatim.openstreetmap.org/search?format=json&q=${encodeURIComponent(query)}&limit=8`);
            const data = await response.json();

            resultsContainer.innerHTML = ''; // On vide le loader

            // Gestion d'aucun résultat
            if (data.length === 0) {
                resultsContainer.innerHTML = '<li class="p-2 text-center text-xs text-gray-500 italic">Aucun résultat trouvé</li>';
                return;
            }

            // Construction de la liste des résultats
            data.forEach(place => {
                const li = document.createElement('li');
                li.innerHTML = `<a class="text-xs py-2 border-b border-base-200 last:border-none cursor-pointer block w-full hover:bg-base-200 font-medium">
                                    <span class="truncate block w-full">${place.display_name}</span>
                                </a>`;
                
                // Action au clic : focus sur la carte
                li.onclick = () => {
                    if (mapInstance) {
                        mapInstance.setView([place.lat, place.lon], 16);
                        
                        if (searchMarker) {
                            mapInstance.removeLayer(searchMarker);
                        }
                        
                        searchMarker = L.marker([place.lat, place.lon]).addTo(mapInstance);
                        
                        const popupContent = `
                            <div class="flex flex-col gap-2 max-w-[200px]">
                                <span class="text-xs font-bold leading-tight">${place.display_name}</span>
                                <button onclick="clearSearchMarker()" class="btn btn-xs btn-error btn-outline flex gap-1 w-full mt-1">
                                    <svg xmlns="http://www.w3.org/2000/svg" class="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" /></svg>
                                    Effacer
                                </button>
                            </div>
                        `;
                        searchMarker.bindPopup(popupContent).openPopup();
                    }
                    
                    resultsContainer.classList.add('hidden');
                    document.getElementById('map-search-input').value = place.display_name.split(',')[0];
                };
                resultsContainer.appendChild(li);
            });
        } catch (error) {
            console.error("Erreur de géocodage :", error);
            resultsContainer.innerHTML = '<li class="p-2 text-center text-xs text-error">Erreur de connexion</li>';
        }
    };

    window.clearSearchMarker = function() {
        if (searchMarker && mapInstance) {
            mapInstance.removeLayer(searchMarker);
            searchMarker = null; // On réinitialise la variable
        }
        document.getElementById('map-search-input').value = ''; // On vide la barre de recherche
    };

    // UX : Fermer les résultats si on clique n'importe où ailleurs sur la carte
    map.on('click', function() {
        document.getElementById('map-search-results').classList.add('hidden');
    });
});