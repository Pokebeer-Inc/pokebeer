// Repères de carte aux couleurs de Pokebeer, dessinés en SVG intégré (aucune image tierce à charger) :
// bars en jaune, brasseries en orange, souvenirs en cuivre, position du membre en rond sombre, recherche en rouge.
// Le SVG est écrit ici, jamais construit à partir d'une donnée de l'utilisateur.
(function (root) {
    const PIN = 'M16 1C8 1 1.5 7.2 1.5 15c0 9.6 14.5 22.5 14.5 22.5S30.5 24.6 30.5 15C30.5 7.2 24 1 16 1z';
    const GLYPHS = {
        bar: '<path d="M10.5 9.5h9v9.5a2 2 0 01-2 2h-5a2 2 0 01-2-2V9.5zm9 2h1.6a1.4 1.4 0 011.4 1.4v2.2a1.4 1.4 0 01-1.4 1.4h-1.6M11 7.8c.3-1 1.2-1.6 2.2-1.6.5-.8 1.3-1.2 2.3-1.2s1.8.4 2.3 1.2c1 0 1.9.6 2.2 1.6" />',
        brewery: '<path d="M9.5 21V9.5a1 1 0 011-1H16a1 1 0 011 1V21M17 21h4.5v-7.5a1 1 0 00-1-1H17M12 12h2M12 15.5h2M12 19h2" />',
        spot: '<path d="M16 6.5l2.3 4.7 5.2.8-3.8 3.7.9 5.2L16 18.4l-4.6 2.5.9-5.2-3.8-3.7 5.2-.8L16 6.5z" />',
    };
    const FILL = { bar: '#f1c40f', brewery: '#eca054', spot: '#b87e44', search: '#cd1904' };

    function pin(kind, glyph) {
        return L.divIcon({
            className: 'pb-pin-wrap',
            html: '<span class="pb-pin"><svg viewBox="0 0 32 40" width="32" height="40" aria-hidden="true" focusable="false">'
                + '<path d="' + PIN + '" fill="' + FILL[kind] + '" stroke="#333" stroke-width="2" stroke-linejoin="round"/>'
                + '<g fill="none" stroke="#333" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">' + (GLYPHS[glyph || kind] || '') + '</g>'
                + '</svg></span>',
            iconSize: [32, 40], iconAnchor: [16, 38], popupAnchor: [0, -34], tooltipAnchor: [0, -34],
        });
    }

    root.PokebeerPins = {
        bar: () => pin('bar'),
        brewery: () => pin('brewery'),
        spot: () => pin('spot'),
        search: () => pin('search', 'spot'),
        forPlace: kind => (kind === 'bar' ? pin('bar') : pin('brewery')),
        // Position du membre : rond sombre cerclé de jaune, avec une onde discrète
        user: () => L.divIcon({
            className: 'pb-pin-wrap',
            html: '<span class="pb-user"><i></i></span>',
            iconSize: [28, 28], iconAnchor: [14, 14], popupAnchor: [0, -14],
        }),
    };
})(window);
