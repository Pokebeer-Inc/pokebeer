document.addEventListener("DOMContentLoaded", function() {
    let movingMarker = null;
    let mapInstance = null;
    let isMovingMode = false;
    
    // 1. Initialisation de la carte
    const map = L.map('map', {zoomControl: false}).setView([46.603354, 1.888334], 5);
    L.control.zoom({ position: 'bottomleft' }).addTo(map);
    PokebeerBasemap.addTo(map);

    new ResizeObserver(() => {
        map.invalidateSize();
    }).observe(document.getElementById('map'));

    mapInstance = map;

    // Mêmes dimensions pour toutes les bulles (souvenirs, bars, brasseries)
    const POPUP_OPTIONS = { minWidth: 200, maxWidth: 260 };

    // Feuille « Mes souvenirs » (souvenirs_sheet.js) : la partie de la carte qu'elle recouvre ne doit pas cacher une bulle ou un repère centré
    const sheetPanel = document.querySelector('[data-sheet-panel]');
    const sheetHeight = () => (sheetPanel ? sheetPanel.offsetHeight : 0);

    // Recherche et puces du haut : une bulle ne doit pas passer dessous
    const topUi = document.getElementById('map-top-ui');
    const topInset = () => (topUi ? topUi.getBoundingClientRect().bottom - map.getContainer().getBoundingClientRect().top : 0);

    // Une bulle se recadre entre le haut (recherche) et la feuille : on règle les marges juste avant son ouverture (clic, ou ouverture depuis la liste)
    const insetPopup = marker => {
        const popup = marker.getPopup();
        popup.options.autoPanPaddingTopLeft = [10, topInset() + 8];
        popup.options.autoPanPaddingBottomRight = [10, sheetHeight() + 10];
    };

    function bindPopup(marker, content) {
        marker.bindPopup(content, POPUP_OPTIONS);
        marker.on('preclick', () => insetPopup(marker));
    }

    function showPopup(marker) {
        insetPopup(marker);
        marker.openPopup();
    }

    // Ordre d'empilement des repères (zIndexOffset de Leaflet) : mes souvenirs devant tout, puis les brasseries, puis les bars ;
    // le point en cours de déplacement et le résultat de recherche passent devant les souvenirs, ma position devant tout
    const Z_ORDER = { bar: 0, brewery: 100, spot: 1000, moving: 2000, search: 2000, user: 9999 };

    // Repères aux couleurs du thème (scripts/pins.js) ; chaque famille a sa couche, que les puces du haut affichent ou masquent
    const layers = { bar: L.layerGroup().addTo(map), brewery: L.layerGroup().addTo(map), spot: L.layerGroup().addTo(map) };

    // 2. Extraction des données préparées par Django dans le HTML caché
    const spotsContainer = document.getElementById('spots-data-container');
    const spotsData = {};
    const spotMarkers = {}; // slug -> repère, pour la liste « Mes souvenirs »
    const mapBounds = [];

    if (spotsContainer) {
        document.querySelectorAll('.spot-data-item').forEach(item => {
            const slug = item.dataset.slug;
            const lat = parseFloat(item.dataset.lat);
            const lng = parseFloat(item.dataset.lng);
            // On récupère le design HTML du popup déjà formaté par Django
            const popupHtml = item.querySelector('.popup-template').innerHTML;
            
            spotsData[slug] = {
                slug: slug,
                title: item.dataset.title,
                description: item.dataset.desc,
                date: item.dataset.dateVal,
                photo_url: item.dataset.photoUrl,
                lat: lat,
                lng: lng,
                is_owner: item.dataset.isOwner === 'true',
                // Nettoyage des chaînes "slug1,slug2," en vrais tableaux JavaScript
                drink_slugs: item.dataset.drinkSlugs.split(',').filter(Boolean),
                other_beer_slugs: item.dataset.otherBeerSlugs.split(',').filter(Boolean),
                friend_usernames: item.dataset.friendUsernames.split(',').filter(Boolean)
            };

            // Ajout direct du marqueur sur la carte
            const marker = L.marker([lat, lng], {icon: PokebeerPins.spot(), title: item.dataset.title, zIndexOffset: Z_ORDER.spot}).addTo(layers.spot);
            bindPopup(marker, popupHtml);
            spotMarkers[slug] = marker;
            mapBounds.push([lat, lng]);
        });
    }

    // Bulle d'un bar ou d'une brasserie : fragment HTML rendu par Django (échappé), demandé une seule fois par lieu
    const POPUP_LOADING = '<span class="loading loading-spinner loading-sm"></span>';
    const POPUP_ERROR = '<p class="text-xs text-error">Impossible de charger ce lieu.</p>';

    function loadPlacePopupOnOpen(marker, type, slug) {
        marker.once('popupopen', event => {
            fetch(`/map/place/${encodeURIComponent(type)}/${encodeURIComponent(slug)}/`)
                .then(response => (response.ok ? response.text() : Promise.reject(new Error(response.status))))
                .then(html => event.popup.setContent(html))
                .catch(() => {
                    event.popup.setContent(POPUP_ERROR);
                    loadPlacePopupOnOpen(marker, type, slug); // nouvel essai à la prochaine ouverture
                });
        });
    }

    // Fenêtre de la fiche complète d'un bar ou d'une brasserie (lien « Voir la fiche » de la bulle)
    window.openPlaceModal = function(url) {
        // Chemin interne uniquement : jamais une adresse extérieure
        if (typeof url !== 'string' || !url.startsWith('/') || url.startsWith('//')) return;
        map.closePopup();
        const modal = document.getElementById('modal_place');
        const contentDiv = document.getElementById('modal_place_content');
        contentDiv.innerHTML = '<div class="flex justify-center p-20"><span class="loading loading-spinner loading-lg"></span></div>';
        modal.showModal();

        fetch(url)
            .then(response => response.text())
            .then(html => {
                const doc = new DOMParser().parseFromString(html, 'text/html');
                // Extrait UNIQUEMENT le contenu utile (le block content) pour éviter les doublons de navbar
                const extractedContent = doc.querySelector('.p-4.flex-1.mb-16');
                if (!extractedContent) {
                    contentDiv.innerHTML = '<p class="text-center p-10 text-error">Erreur lors du chargement des données.</p>';
                    return;
                }
                contentDiv.innerHTML = extractedContent.innerHTML;
                // La croix de la fenêtre remplace le bouton « Retour » de la page, et la mini-carte ferait doublon avec la carte
                const backBtn = contentDiv.querySelector('a[href="javascript:history.back()"]');
                if (backBtn) backBtn.style.display = 'none';
                const miniMap = contentDiv.querySelector('#place-map');
                if (miniMap) miniMap.parentElement.remove();
            })
            .catch(() => {
                contentDiv.innerHTML = '<p class="text-center p-10 text-error">Impossible de joindre le serveur.</p>';
            });
    };

    // Chargement des Bars et Brasseries
    const placesContainer = document.getElementById('places-data-container');
    const placeMarkers = {}; // « bar:slug » / « brewery:slug » -> marqueur, pour ouvrir un établissement depuis la recherche
    const placeIndex = [];   // { name, haystack (nom sans casse ni accents), marker } : recherche locale, sans requête réseau
    if (placesContainer) {
        document.querySelectorAll('.place-data-item').forEach(item => {
            const lat = parseFloat(item.dataset.lat);
            const lng = parseFloat(item.dataset.lng);
            const type = item.dataset.type;
            const name = item.dataset.name;

            const marker = L.marker([lat, lng], {icon: PokebeerPins.forPlace(type), title: name, zIndexOffset: Z_ORDER[type]}).addTo(type === 'bar' ? layers.bar : layers.brewery);
            placeMarkers[type + ':' + item.dataset.slug] = marker;
            placeIndex.push({ name: name, haystack: normalizeText(name), marker: marker });
            mapBounds.push([lat, lng]);
            
            // Bulle au clic : son contenu (image, nom, description, ville) n'est demandé au serveur qu'à la première ouverture
            bindPopup(marker, POPUP_LOADING);
            loadPlacePopupOnOpen(marker, type, item.dataset.slug);
        });
    }

    // Centrage automatique sur tous les points
    if (mapBounds.length > 0) {
        map.fitBounds(mapBounds, { maxZoom: 5, padding: [30, 30] }); 
    }

    // Arrivée depuis la recherche (?kind=bar&place=slug) : centre la carte et ouvre la fiche. Les paramètres ne servent qu'à
    // retrouver un marqueur déjà présent (clé de dictionnaire) : ils ne sont jamais insérés dans la page.
    const requested = new URLSearchParams(window.location.search);
    const requestedMarker = placeMarkers[requested.get('kind') + ':' + requested.get('place')];
    if (requestedMarker) {
        map.setView(requestedMarker.getLatLng(), 16);
        requestedMarker.fire('click');
    }

    function resetPhotoField(url) {
        window.ImageFields.reset(document.querySelector('#modal_add_spot [data-image-input]'), url);
    }

    function resetDrinkPicker(selection) {
        const picker = document.querySelector('#spot-drinks [data-picker]');
        if (picker) PokebeerPicker.reset(picker, selection);
    }

    // Gestion de l'ouverture de la modale d'édition
    window.openEditModal = function(spotSlug) {
        const data = spotsData[spotSlug];
        if (!data) return;

        document.getElementById('modal-title').innerText = "Modifier le lieu";
        document.getElementById('spot-slug').value = data.slug;
        document.getElementById('spot-title').value = data.title;
        document.getElementById('spot-desc').value = data.description;
        document.getElementById('spot-date').value = data.date;
        document.getElementById('spot-lat').value = data.lat;
        document.getElementById('spot-lng').value = data.lng;
        resetPhotoField(data.photo_url);

        // Dégustations : celles du lieu cochées ; les bières déjà ajoutées par d'autres indisponibles ; les bières retirées masquées sauf si
        // elles sont déjà rattachées (picker.js)
        resetDrinkPicker({ selected: data.drink_slugs, disabledBeers: data.other_beer_slugs });

        // Gestion des droits (créateur)
        const friendsSection = document.getElementById('friends-section');
        const deleteForm = document.getElementById('form-delete-spot');
        
        if (data.is_owner) {
            friendsSection.style.display = 'block';
            document.querySelectorAll('.friend-checkbox').forEach(cb => {
                cb.checked = data.friend_usernames.includes(cb.value);
            });
            deleteForm.action = `/delete-spot/${spotSlug}/`;
            deleteForm.style.display = "block";
        } else {
            friendsSection.style.display = 'none';
            deleteForm.style.display = "none";
        }

        document.getElementById('modal_add_spot').showModal();
    };

    // 4. Création d'un NOUVEAU point : clic sur la carte, ou bouton « Ajouter une dégustation ici » d'un résultat de recherche
    function openNewSpotModal(latlng, title) {
        document.getElementById('modal-title').innerText = "Ajouter un lieu";
        document.getElementById('spot-slug').value = ""; 
        document.getElementById('spot-title').value = title || "";
        document.getElementById('spot-desc').value = "";
        resetPhotoField('');
        
        const today = new Date().toISOString().split('T')[0];
        document.getElementById('spot-date').value = today;
        
        document.getElementById('spot-lat').value = latlng.lat.toFixed(6);
        document.getElementById('spot-lng').value = latlng.lng.toFixed(6);

        // Remise à zéro des champs
        document.querySelectorAll('.friend-checkbox').forEach(cb => cb.checked = false);
        resetDrinkPicker({});
        
        document.getElementById('form-delete-spot').style.display = 'none';
        document.getElementById('friends-section').style.display = 'block';

        document.getElementById('modal_add_spot').showModal();
    }

    map.on('click', function(e) {
        if (isMovingMode) return;
        openNewSpotModal(e.latlng);
    });

    // 5. Gestion de la géolocalisation
    let userMarker = null;
    let geoWatchId = null;

    const userIcon = PokebeerPins.user();

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
                            zIndexOffset: Z_ORDER.user
                        }).addTo(map);
                        userMarker.bindPopup("<div class='text-center font-bold mb-0'>Vous êtes ici</div>");
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
            icon: PokebeerPins.spot(),
            draggable: true,
            zIndexOffset: Z_ORDER.moving
        }).addTo(mapInstance);

        movingMarker.bindTooltip("Faites-moi glisser !", {permanent: true, direction: 'top', offset: [0,-34]}).openTooltip();
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

    // Liste « Mes souvenirs » : la carte se centre sur le souvenir annoncé, dans la partie que la feuille ne recouvre pas, puis ouvre sa bulle
    const FOCUS_MIN_ZOOM = 15;
    const MARKER_CLEARANCE = 56; // px entre le repère et le haut de la feuille
    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');

    function focusSpot(slug) {
        const marker = spotMarkers[slug];
        if (!marker) return;
        if (!map.hasLayer(layers.spot)) document.querySelector('[data-layer="spot"]')?.click(); // couche masquée par la puce : on la rétablit
        const zoom = Math.max(map.getZoom(), FOCUS_MIN_ZOOM);
        // Le repère se place juste au-dessus de la feuille : toute la place visible au-dessus de lui sert à sa bulle
        const markerY = map.getSize().y - sheetHeight() - MARKER_CLEARANCE;
        const target = map.unproject(map.project(marker.getLatLng(), zoom).add([0, map.getSize().y / 2 - markerY]), zoom);
        const openPopup = () => showPopup(marker);
        if (map.getZoom() === zoom && map.getCenter().distanceTo(target) < 1) return openPopup();
        map.once('moveend', openPopup);
        if (reducedMotion.matches) map.setView(target, zoom, { animate: false }); else map.flyTo(target, zoom, { duration: 0.6 });
    }

    document.addEventListener('souvenir:focus', event => focusSpot(event.detail.slug));

    // Puces du haut : affichent ou masquent les bars, les brasseries et les souvenirs
    document.querySelectorAll('[data-layer]').forEach(chip => {
        chip.addEventListener('click', () => {
            const layer = layers[chip.dataset.layer];
            const visible = map.hasLayer(layer);
            if (visible) map.removeLayer(layer); else map.addLayer(layer);
            chip.classList.toggle('is-on', !visible);
            chip.setAttribute('aria-pressed', String(!visible));
        });
    });

    // --- MOTEUR DE RECHERCHE DE LIEUX (Nominatim) ---
    let searchMarker = null;
    let searchTitle = '';

    const MIN_QUERY_LENGTH = 3;
    const MAX_LOCAL_RESULTS = 5;
    const remoteCache = new Map(); // requête normalisée -> résultats Nominatim : « Paris » et « paris » ne coûtent qu'un appel

    const searchInput = () => document.getElementById('map-search-input');
    const resultsList = () => document.getElementById('map-search-results');

    // Bars et brasseries déjà chargés sur la carte : aucun appel réseau, insensible à la casse et aux accents
    function findLocalPlaces(query) {
        const words = normalizeText(query).split(/\s+/).filter(Boolean);
        return placeIndex.filter(entry => words.every(word => entry.haystack.includes(word))).slice(0, MAX_LOCAL_RESULTS);
    }

    // Géocodage Nominatim : uniquement sur action explicite (Entrée ou bouton), jamais pendant la frappe ; un même terme n'est demandé qu'une fois
    async function findRemotePlaces(query) {
        const key = normalizeText(query);
        if (!remoteCache.has(key)) {
            const response = await fetch(`https://nominatim.openstreetmap.org/search?format=json&q=${encodeURIComponent(query)}&limit=8`);
            if (!response.ok) throw new Error('Nominatim ' + response.status);
            const data = await response.json();
            remoteCache.set(key, Array.isArray(data) ? data : []);
        }
        return remoteCache.get(key);
    }

    // Une ligne de la liste ; le libellé vient de la base ou d'un service tiers : toujours textContent
    function addResultRow(label, onSelect) {
        const li = document.createElement('li');
        li.setAttribute('role', 'option');
        li.innerHTML = `<a class="text-sm py-2 border-b border-base-300 last:border-none cursor-pointer block w-full hover:bg-primary/30 font-medium">
                            <span class="truncate block w-full"></span>
                        </a>`;
        li.querySelector('span').textContent = label;
        li.onclick = () => {
            onSelect();
            resultsList().classList.add('hidden');
            searchInput().value = label.split(',')[0];
        };
        resultsList().appendChild(li);
    }

    function addResultNote(text, classes) {
        const li = document.createElement('li');
        li.className = classes;
        li.textContent = text;
        resultsList().appendChild(li);
    }

    function showLocalPlace(entry) {
        mapInstance.setView(entry.marker.getLatLng(), 16);
        entry.marker.fire('click');
    }

    function showRemotePlace(place) {
        mapInstance.setView([place.lat, place.lon], 16);
        if (searchMarker) mapInstance.removeLayer(searchMarker);

        searchTitle = place.display_name.split(',')[0].trim().slice(0, 150);
        searchMarker = L.marker([place.lat, place.lon], {icon: PokebeerPins.search(), zIndexOffset: Z_ORDER.search}).addTo(mapInstance);

        // Le bouton lit la position du repère de recherche : aucune valeur du service tiers n'est copiée dans un attribut
        const popupContent = `
            <div class="flex flex-col gap-2 max-w-[220px]">
                <span class="text-sm font-bold leading-tight">${escapeHtml(place.display_name)}</span>
                <button type="button" data-on-click="addSpotAtSearchResult" data-no-event class="btn btn-sm btn-primary border-secondary text-black normal-case w-full mt-1">
                    <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2" aria-hidden="true"><path stroke-linecap="round" stroke-linejoin="round" d="M12 4v16m8-8H4" /></svg>
                    Ajouter une dégustation ici
                </button>
                <button type="button" data-on-click="clearSearchMarker" data-no-event class="btn btn-xs btn-outline border-error text-error flex gap-1 w-full">
                    <svg xmlns="http://www.w3.org/2000/svg" class="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" /></svg>
                    Effacer
                </button>
            </div>
        `;
        searchMarker.bindPopup(popupContent).openPopup();
    }

    window.searchLocation = async function() {
        const query = searchInput().value.trim();
        const resultsContainer = resultsList();

        // Empêche les requêtes inutiles pour 1 ou 2 lettres
        if (query.length < MIN_QUERY_LENGTH) {
            resultsContainer.classList.add('hidden');
            return;
        }

        resultsContainer.replaceChildren();
        resultsContainer.classList.remove('hidden');
        findLocalPlaces(query).forEach(entry => addResultRow(entry.name, () => showLocalPlace(entry)));

        // Loader pendant l'appel au service gratuit OpenStreetMap
        const loader = document.createElement('li');
        loader.className = 'p-2 flex justify-center';
        loader.innerHTML = '<span class="loading loading-spinner loading-sm"></span>';
        resultsContainer.appendChild(loader);

        try {
            const data = await findRemotePlaces(query);
            loader.remove();
            data.forEach(place => addResultRow(place.display_name, () => showRemotePlace(place)));
            if (!resultsContainer.children.length) addResultNote('Aucun résultat trouvé', 'p-2 text-center text-xs text-gray-500 italic');
        } catch (error) {
            console.error("Erreur de géocodage :", error);
            loader.remove();
            // Les lieux locaux restent utilisables même si le service tiers ne répond pas
            addResultNote('Erreur de connexion', 'p-2 text-center text-xs text-error');
        }
    };

    // Depuis la bulle d'un résultat : ouvre la fenêtre d'ajout, positionnée sur le résultat et nommée d'après lui
    window.addSpotAtSearchResult = function() {
        if (!searchMarker) return;
        const position = searchMarker.getLatLng();
        searchMarker.closePopup();
        openNewSpotModal(position, searchTitle);
    };

    window.clearSearchMarker = function() {
        if (searchMarker && mapInstance) {
            mapInstance.removeLayer(searchMarker);
            searchMarker = null; // On réinitialise la variable
            searchTitle = '';
        }
        document.getElementById('map-search-input').value = ''; // On vide la barre de recherche
    };

    // UX : Fermer les résultats si on clique n'importe où ailleurs sur la carte
    map.on('click', function() {
        document.getElementById('map-search-results').classList.add('hidden');
    });
});