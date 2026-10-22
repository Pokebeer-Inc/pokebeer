// Feuille « Mes souvenirs » de la carte : se déplie depuis le bas, et la ligne qui s'arrête en haut de la liste est annoncée à la carte.
// Ce fichier ne connaît que la feuille : il émet « souvenir:focus » ({ slug }) et map.js décide quoi faire sur la carte.
(function () {
    const FOCUS_DELAY_MS = 220;     // pause après le dernier défilement : la carte ne saute pas pendant le glissement
    const TOP_BAND = '0px 0px -60% 0px';  // les 40 % du haut de la liste

    const frame = document.querySelector('[data-sheet]');
    const toggle = frame && frame.querySelector('[data-sheet-toggle]');
    const body = frame && frame.querySelector('#souvenirs-body');
    if (!toggle || !body) return;

    const list = body.querySelector('[data-sheet-list]');
    const rows = list ? Array.from(list.querySelectorAll('[data-souvenir]')) : [];
    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
    const inBand = new Set();
    let observer = null;
    let timer = null;
    let current = null;

    function announce(row, force = false) {
        if (!row || (row === current && !force)) return;
        if (current) current.setAttribute('aria-current', 'false');
        row.setAttribute('aria-current', 'true');
        current = row;
        document.dispatchEvent(new CustomEvent('souvenir:focus', { detail: { slug: row.dataset.souvenir } }));
    }

    // La ligne la plus proche du haut de la liste parmi celles qui touchent la bande du haut
    function closestToTop() {
        const top = list.getBoundingClientRect().top;
        let best = null;
        let bestDistance = Infinity;
        inBand.forEach(row => {
            const distance = Math.abs(row.getBoundingClientRect().top - top);
            if (distance < bestDistance) { best = row; bestDistance = distance; }
        });
        return best;
    }

    function scheduleFocus() {
        clearTimeout(timer);
        timer = setTimeout(() => announce(closestToTop()), FOCUS_DELAY_MS);
    }

    function startObserving() {
        if (!list || observer) return;
        observer = new IntersectionObserver(entries => {
            entries.forEach(entry => (entry.isIntersecting ? inBand.add(entry.target) : inBand.delete(entry.target)));
            scheduleFocus();
        }, { root: list, rootMargin: TOP_BAND, threshold: 0 });
        rows.forEach(row => observer.observe(row));
    }

    function stopObserving() {
        clearTimeout(timer);
        if (observer) observer.disconnect();
        observer = null;
        inBand.clear();
    }

    function setOpen(open) {
        frame.dataset.sheet = open ? 'open' : 'closed';
        toggle.setAttribute('aria-expanded', String(open));
        body.inert = !open;
        if (open) startObserving(); else stopObserving();
    }

    let justDragged = false;  // un glissement ne doit pas être pris pour un toucher sur la poignée

    toggle.addEventListener('click', () => {
        if (justDragged) return;
        setOpen(frame.dataset.sheet !== 'open');
    });

    // Glisser le doigt (ou la souris) sur la poignée ou le rappel : la feuille suit le doigt, puis s'ouvre ou se ferme selon la distance et la vitesse
    const DRAG_THRESHOLD_PX = 6;      // en dessous, c'est un simple toucher
    const FLING_PX_PER_MS = 0.4;      // un geste rapide suffit, même court

    // Hauteurs réelles (px) de la feuille repliée et dépliée, lues sur les variables CSS : une seule définition, dans map.css
    function sheetHeights() {
        const probe = document.createElement('div');
        probe.style.cssText = 'position:absolute;visibility:hidden;pointer-events:none';
        frame.appendChild(probe);
        const measure = name => { probe.style.height = `var(${name})`; return probe.offsetHeight; };
        const heights = { closed: measure('--sheet-closed'), open: measure('--sheet-open') };
        probe.remove();
        return heights;
    }

    function enableDrag(zone) {
        let drag = null;

        zone.addEventListener('pointerdown', event => {
            if (!event.isPrimary || (event.pointerType === 'mouse' && event.button !== 0)) return;
            const heights = sheetHeights();
            drag = { startY: event.clientY, startHeight: frame.dataset.sheet === 'open' ? heights.open : heights.closed, heights, lastY: event.clientY, lastTime: event.timeStamp, velocity: 0, moved: false };
            try { zone.setPointerCapture(event.pointerId); } catch (error) { /* geste déjà terminé : on continue sans capture */ }
        });

        zone.addEventListener('pointermove', event => {
            if (!drag) return;
            const delta = drag.startY - event.clientY;
            if (!drag.moved && Math.abs(delta) < DRAG_THRESHOLD_PX) return;
            if (!drag.moved) { drag.moved = true; frame.classList.add('is-dragging'); }
            const elapsed = event.timeStamp - drag.lastTime;
            if (elapsed > 0) drag.velocity = (drag.lastY - event.clientY) / elapsed;  // positif : vers le haut
            drag.lastY = event.clientY;
            drag.lastTime = event.timeStamp;
            const height = Math.min(drag.heights.open, Math.max(drag.heights.closed, drag.startHeight + delta));
            frame.style.setProperty('--sheet-h', `${height}px`);
        });

        const release = event => {
            if (!drag) return;
            const { moved, velocity, heights } = drag;
            const height = parseFloat(frame.style.getPropertyValue('--sheet-h')) || drag.startHeight;
            drag = null;
            if (!moved) return;
            justDragged = true;
            setTimeout(() => { justDragged = false; }, 0);
            const middle = (heights.closed + heights.open) / 2;
            const open = Math.abs(velocity) > FLING_PX_PER_MS ? velocity > 0 : height > middle;
            frame.classList.remove('is-dragging');
            frame.style.removeProperty('--sheet-h');
            setOpen(open);
        };
        zone.addEventListener('pointerup', release);
        zone.addEventListener('pointercancel', release);
    }

    enableDrag(toggle);
    enableDrag(body.querySelector('.pb-sheet-hint'));

    document.addEventListener('keydown', event => {
        if (event.key === 'Escape' && frame.dataset.sheet === 'open' && !document.querySelector('dialog[open]')) {
            setOpen(false);
            toggle.focus();
        }
    });

    // Toucher une ligne : la carte y va tout de suite, et la ligne vient se placer en haut de la liste
    if (list) {
        list.addEventListener('click', event => {
            const row = event.target.closest('[data-souvenir]');
            if (!row) return;
            clearTimeout(timer);
            announce(row, true);
            row.scrollIntoView({ block: 'start', behavior: reducedMotion.matches ? 'auto' : 'smooth' });
        });
    }
})();
