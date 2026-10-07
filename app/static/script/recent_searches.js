// Recherches récentes : conservées uniquement dans cet appareil (stockage local du navigateur), jamais envoyées au serveur.
// Une clé par compte : deux membres qui partagent un appareil ne voient pas les recherches l'un de l'autre.
(function () {
    const form = document.getElementById('search-form');
    const input = document.getElementById('search-input');
    const box = document.getElementById('recent-searches');
    const results = document.getElementById('search-results');
    if (!form || !input || !box || !results) return;

    const KEY = 'pokebeer_recent_searches_' + (form.dataset.user || '');
    const MAX_ITEMS = 8;
    const MAX_LENGTH = 100;

    function read() {
        try {
            const stored = JSON.parse(localStorage.getItem(KEY));
            // Donnée non fiable (modifiable par l'utilisateur ou une extension) : seules des chaînes courtes sont gardées
            return Array.isArray(stored) ? stored.filter(item => typeof item === 'string' && item.trim()).map(item => item.slice(0, MAX_LENGTH)).slice(0, MAX_ITEMS) : [];
        } catch (error) {
            return [];
        }
    }

    function write(items) {
        try {
            if (items.length) localStorage.setItem(KEY, JSON.stringify(items));
            else localStorage.removeItem(KEY);
        } catch (error) { /* stockage indisponible (navigation privée) : la fonction s'éteint sans erreur */ }
    }

    function remember(query) {
        const clean = (query || '').trim().slice(0, MAX_LENGTH);
        if (clean.length < 2) return;
        write([clean, ...read().filter(item => item.toLowerCase() !== clean.toLowerCase())].slice(0, MAX_ITEMS));
    }

    // Croix dessinée en SVG (aucun caractère décoratif dans le code)
    function crossIcon() {
        const namespace = 'http://www.w3.org/2000/svg';
        const svg = document.createElementNS(namespace, 'svg');
        svg.setAttribute('viewBox', '0 0 24 24');
        svg.setAttribute('class', 'h-3 w-3');
        svg.setAttribute('fill', 'none');
        svg.setAttribute('stroke', 'currentColor');
        svg.setAttribute('stroke-width', '3');
        svg.setAttribute('aria-hidden', 'true');
        const path = document.createElementNS(namespace, 'path');
        path.setAttribute('stroke-linecap', 'round');
        path.setAttribute('d', 'M6 18L18 6M6 6l12 12');
        svg.appendChild(path);
        return svg;
    }

    function chip(text) {
        const wrapper = document.createElement('span');
        wrapper.className = 'inline-flex items-center rounded-full bg-base-200 text-xs';
        const pick = document.createElement('button');
        pick.type = 'button';
        pick.className = 'pl-3 pr-1 py-1.5';
        pick.textContent = text;
        pick.addEventListener('click', () => {
            input.value = text;
            input.dispatchEvent(new Event('input', { bubbles: true }));
            input.focus();
        });
        const remove = document.createElement('button');
        remove.type = 'button';
        remove.className = 'pl-1 pr-2 py-1.5 text-gray-400 hover:text-error';
        remove.setAttribute('aria-label', 'Retirer « ' + text + ' » des recherches récentes');
        remove.appendChild(crossIcon());
        remove.addEventListener('click', () => { write(read().filter(item => item !== text)); render(); });
        wrapper.append(pick, remove);
        return wrapper;
    }

    function render() {
        const items = read();
        box.replaceChildren();
        box.classList.toggle('hidden', input.value !== '' || items.length === 0);
        if (input.value !== '' || items.length === 0) return;
        const header = document.createElement('div');
        header.className = 'flex items-center justify-between mb-1 text-[10px] font-bold uppercase tracking-wider text-gray-500';
        const title = document.createElement('span');
        title.textContent = 'Recherches récentes';
        const clear = document.createElement('button');
        clear.type = 'button';
        clear.className = 'normal-case font-semibold text-primary';
        clear.textContent = 'Tout effacer';
        clear.addEventListener('click', () => { write([]); render(); });
        header.append(title, clear);
        const chips = document.createElement('div');
        chips.className = 'flex flex-wrap gap-2';
        items.forEach(item => chips.appendChild(chip(item)));
        box.append(header, chips);
    }

    input.addEventListener('input', render);
    form.addEventListener('submit', () => remember(input.value));
    // Ouvrir un résultat valide la recherche ; les onglets et « Voir tout » n'en sont pas
    results.addEventListener('click', event => {
        const link = event.target.closest('a[href]');
        if (link && !link.hasAttribute('data-tab')) remember(input.value);
    });
    render();
})();
