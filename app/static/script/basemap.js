// Fond de carte commun à toutes les cartes du site (carte principale, mini-carte d'un lieu, carte admin des lieux, carte analytics).
//
// Les tuiles OpenStreetMap classiques sont des images : impossible d'en retirer les noms de routes ou de commerces. On utilise donc les
// tuiles vectorielles gratuites d'OpenFreeMap (données OpenStreetMap, sans clé) dessinées par MapLibre GL, et le style ci-dessous ne
// garde que l'essentiel : relief, eau, parcs, frontières, quelques grands axes sans nom, villes, et les noms des bars et restaurants
// seulement quand on est assez près. Tout le style est ici ; les cartes n'appellent que `PokebeerBasemap.addTo(map)`.
//
// Les zooms du style sont ceux de MapLibre, soit le zoom Leaflet moins 1 (tuiles de 512 px).
// Sans WebGL, on retombe sur les tuiles d'images d'OpenStreetMap.
(function (root) {
    const TILE_SOURCE = 'https://tiles.openfreemap.org/planet';
    const GLYPHS = 'https://tiles.openfreemap.org/fonts/{fontstack}/{range}.pbf';
    const ATTRIBUTION = '<a href="https://openfreemap.org" target="_blank" rel="noopener">OpenFreeMap</a> '
        + '&copy; <a href="https://www.openmaptiles.org/" target="_blank" rel="noopener">OpenMapTiles</a> '
        + 'Données <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a>';
    const RASTER_URL = 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png';
    const MAX_ZOOM = 19;
    const FONT = ['Noto Sans Regular'];
    const FONT_BOLD = ['Noto Sans Bold'];
    // Rues nommées (sans les voies de service et les chemins)
    const STREET_CLASSES = ['motorway', 'trunk', 'primary', 'secondary', 'tertiary', 'minor'];

    // Établissements nommés sur la carte (sous-classes OpenStreetMap) et zoom MapLibre à partir duquel leur nom s'affiche
    const VENUES = [
        { id: 'poi-bars', subclasses: ['bar', 'pub', 'biergarten'], minzoom: 14 },
        { id: 'poi-restaurants', subclasses: ['restaurant'], minzoom: 16 },
    ];

    // Couleurs du thème « beer » lues sur les variables CSS de l'application (valeurs du thème en repli, par ex. dans l'administration)
    const THEME = {
        land: ['--color-base-100', '#ede6e0'], paper: ['--color-base-200', '#f7f3f0'], ink: ['--color-secondary', '#333333'],
        gold: ['--color-primary', '#f1c40f'], amber: ['--color-accent', '#eca054'], copper: ['--color-success', '#b87e44'],
    };

    function palette() {
        const styles = getComputedStyle(document.documentElement);
        const color = {};
        Object.entries(THEME).forEach(([key, [variable, fallback]]) => { color[key] = styles.getPropertyValue(variable).trim() || fallback; });
        return color;
    }

    function zoomWidth(...stops) {
        return ['interpolate', ['linear'], ['zoom'], ...stops];
    }

    function inClasses(property, values) {
        return ['in', ['get', property], ['literal', values]];
    }

    const name = ['coalesce', ['get', 'name:fr'], ['get', 'name']];

    function label(id, sourceLayer, filter, extra) {
        const { layout = {}, paint = {}, minzoom, maxzoom } = extra;
        return {
            id, type: 'symbol', source: 'omt', 'source-layer': sourceLayer, filter, minzoom, maxzoom,
            layout: { 'text-field': name, 'text-font': FONT, 'text-max-width': 8, ...layout },
            paint: { 'text-halo-width': 1.4, ...paint },
        };
    }

    function buildStyle() {
        const c = palette();
        const text = { 'text-color': c.ink, 'text-opacity': 0.7, 'text-halo-color': c.land };
        const road = (id, classes, minzoom, width) => ({
            id, type: 'line', source: 'omt', 'source-layer': 'transportation', minzoom,
            filter: ['all', inClasses('class', classes), ['!', ['has', 'brunnel']]],
            layout: { 'line-cap': 'round', 'line-join': 'round' },
            paint: { 'line-color': c.paper, 'line-width': width },
        });
        return {
            version: 8,
            glyphs: GLYPHS,
            sources: { omt: { type: 'vector', url: TILE_SOURCE, attribution: ATTRIBUTION } },
            layers: [
                { id: 'land', type: 'background', paint: { 'background-color': c.land } },
                { id: 'green', type: 'fill', source: 'omt', 'source-layer': 'landcover', filter: inClasses('class', ['wood', 'grass']), paint: { 'fill-color': c.amber, 'fill-opacity': 0.12 } },
                { id: 'parks', type: 'fill', source: 'omt', 'source-layer': 'park', minzoom: 8, filter: inClasses('class', ['park', 'nature_reserve']), paint: { 'fill-color': c.amber, 'fill-opacity': 0.2 } },
                { id: 'water', type: 'fill', source: 'omt', 'source-layer': 'water', paint: { 'fill-color': c.gold, 'fill-opacity': 0.22 } },
                // Grands axes sans nom, de plus en plus fins ; les petites rues n'apparaissent qu'à l'échelle d'un quartier
                road('roads-major', ['motorway', 'trunk', 'primary'], 7, zoomWidth(7, 0.4, 14, 1.6)),
                road('roads-medium', ['secondary', 'tertiary'], 11, zoomWidth(11, 0.4, 16, 1.8)),
                road('roads-minor', ['minor', 'service'], 13.5, zoomWidth(13.5, 0.4, 17, 2)),
                { id: 'buildings', type: 'fill', source: 'omt', 'source-layer': 'building', minzoom: 14.5, paint: { 'fill-color': c.ink, 'fill-opacity': 0.06 } },
                { id: 'borders', type: 'line', source: 'omt', 'source-layer': 'boundary', filter: ['<=', ['get', 'admin_level'], 4], paint: { 'line-color': c.ink, 'line-opacity': 0.3, 'line-width': 0.8, 'line-dasharray': [3, 2] } },
                label('place-country', 'place', ['==', ['get', 'class'], 'country'], { minzoom: 2, maxzoom: 6, layout: { 'text-font': FONT_BOLD, 'text-transform': 'uppercase', 'text-size': 11 }, paint: text }),
                label('place-city', 'place', ['==', ['get', 'class'], 'city'], { minzoom: 5, layout: { 'text-font': FONT_BOLD, 'text-size': zoomWidth(5, 11, 12, 16) }, paint: text }),
                label('place-town', 'place', ['==', ['get', 'class'], 'town'], { minzoom: 9, layout: { 'text-size': zoomWidth(9, 11, 13, 14) }, paint: text }),
                label('place-village', 'place', ['==', ['get', 'class'], 'village'], { minzoom: 12, layout: { 'text-size': 12 }, paint: text }),
                label('place-suburb', 'place', inClasses('class', ['suburb', 'neighbourhood']), { minzoom: 13, layout: { 'text-size': 11 }, paint: text }),
                // Noms de rues : uniquement très près, pour se repérer à l'endroit précis où l'on regarde
                label('street-names', 'transportation_name', inClasses('class', STREET_CLASSES), {
                    minzoom: 15,
                    layout: { 'symbol-placement': 'line', 'text-size': 11, 'text-letter-spacing': 0.02, 'text-max-angle': 30 },
                    paint: { ...text, 'text-opacity': 0.55 },
                }),
                // Noms des bars en zoom rapproché, ceux des restaurants encore plus près : la carte reste lisible en centre-ville
                ...VENUES.map(venue => label(venue.id, 'poi', inClasses('subclass', venue.subclasses), {
                    minzoom: venue.minzoom,
                    layout: { 'text-size': 11, 'text-optional': true },
                    paint: { ...text, 'text-color': c.copper, 'text-opacity': 1 },
                })),
            ],
        };
    }

    function webglAvailable() {
        try {
            const canvas = document.createElement('canvas');
            return Boolean(root.maplibregl && root.L.maplibreGL && (canvas.getContext('webgl2') || canvas.getContext('webgl')));
        } catch (e) {
            return false;
        }
    }

    // Le moteur de dessin tourne dans un fichier du site (la CSP interdit les workers créés à la volée) : son adresse est portée par la balise <script>
    function configureWorker() {
        const tag = document.querySelector('script[data-maplibre-worker]');
        if (tag && root.maplibregl) root.maplibregl.setWorkerUrl(tag.dataset.maplibreWorker);
    }

    function vectorLayer() {
        configureWorker();
        return root.L.maplibreGL({ style: buildStyle(), attributionControl: false });
    }

    function rasterLayer() {
        return root.L.tileLayer(RASTER_URL, { maxZoom: MAX_ZOOM, attribution: '&copy; OpenStreetMap' });
    }

    // Ajoute le fond à une carte Leaflet et le renvoie (à retirer avec `map.removeLayer`)
    function addTo(map) {
        const vector = webglAvailable();
        const layer = vector ? vectorLayer() : rasterLayer();
        map.setMaxZoom(MAX_ZOOM);
        layer.addTo(map);
        if (vector && map.attributionControl) map.attributionControl.addAttribution(ATTRIBUTION);
        return layer;
    }

    root.PokebeerBasemap = { addTo, buildStyle };
})(window);
