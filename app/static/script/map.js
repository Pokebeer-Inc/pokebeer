document.addEventListener("DOMContentLoaded", function() {
    let movingMarker = null;
    let mapInstance = null;
    let isMovingMode = false;
    
    // 1. Initialisation de la carte
    const map = L.map('map', {zoomControl: false}).setView([46.603354, 1.888334], 5);
    L.control.zoom({ position: 'topright' }).addTo(map);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 19 }).addTo(map);

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

    // 2. Extraction des données préparées par Django dans le HTML caché
    const spotsContainer = document.getElementById('spots-data-container');
    const spotsData = {};

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
        });
    }

    // 3. Gestion de l'ouverture de la modale d'édition
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
    const geolocBtn = document.getElementById('geoloc-btn');
    if (geolocBtn) {
        geolocBtn.addEventListener('click', function() {
            if(navigator.geolocation) {
                const originalHtml = this.innerHTML;
                this.innerHTML = '<span class="loading loading-spinner loading-xs"></span>';
                
                navigator.geolocation.getCurrentPosition((position) => {
                    this.innerHTML = originalHtml;
                    map.setView([position.coords.latitude, position.coords.longitude], 16);
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
});