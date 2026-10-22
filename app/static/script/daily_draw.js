// Tirage du jour de l'accueil : cinq cartes face cachée, révélées une à une (retournement, lueur et confettis à la couleur de la rareté).
// Le serveur tire les cartes et retient celles déjà retournées (services/catalog/daily_draw.py) : en revenant, on reprend à la première carte
// non retournée, et les pastilles de progression permettent de revoir les cartes déjà ouvertes sans attendre. Les textes viennent de la base :
// ils sont posés avec textContent, jamais avec innerHTML.
(function () {
    const entry = document.getElementById('daily-draw-entry');
    if (!entry) return;
    const overlay = document.getElementById('daily-draw');
    const opener = entry.querySelector('[data-draw-open]');
    const stage = overlay.querySelector('[data-draw-stage]');
    const dots = overlay.querySelector('[data-draw-dots]');
    const reduced = Pokebeer.confetti.reduced;

    // Effets par rareté : nombre de confettis, couleurs, suspense avant le retournement (ms), éclair et vibration
    const EFFECTS = {
        common: { count: 0, colors: [], suspense: 0 },
        rare: { count: 45, colors: ['#3b82c4', '#8ec1ef', '#f7f3f0'], suspense: 0 },
        epic: { count: 90, colors: ['#8e44ad', '#c58be0', '#f7f3f0', '#f1c40f'], suspense: 700 },
        legendary: { count: 160, colors: ['#f1c40f', '#ffe27a', '#eca054', '#f7f3f0'], suspense: 1100, flash: true, vibrate: [60, 40, 120] },
    };

    let cards = [];
    let index = 0;     // carte affichée
    let revealed = 0;  // cartes déjà retournées (d'après le serveur, puis au fil du tirage)

    const template = id => document.getElementById(id).content.firstElementChild.cloneNode(true);
    const pause = ms => new Promise(resolve => setTimeout(resolve, reduced() ? 0 : ms));
    const finished = () => revealed >= cards.length;

    function el(tag, className, text) {
        const node = document.createElement(tag);
        if (className) node.className = className;
        if (text !== undefined) node.textContent = text;
        return node;
    }

    function post(url, body) {
        const headers = { 'X-CSRFToken': Pokebeer.csrfToken() };
        if (body) headers['Content-Type'] = 'application/json';
        return fetch(url, { method: 'POST', headers, body: body && JSON.stringify(body) });
    }

    function toast(message) {
        if (typeof window.showToast === 'function') window.showToast({ message, type: 'error' });
    }

    function cardMeta(card) {
        return [card.brewery, card.style, `${card.degree} %`].filter(Boolean).join(' · ');
    }

    // ---- Ouverture et fermeture -------------------------------------------------------------

    async function open() {
        const data = await Pending.run(opener, async () => {
            try {
                const response = await post(entry.dataset.openUrl);
                const body = await response.json();
                if (!body.success) { toast(body.error || 'Le tirage est indisponible.'); return null; }
                return body;
            } catch (error) {
                toast('Le tirage est indisponible, réessayez.');
                return null;
            }
        });
        if (!data) return;
        cards = data.cards;
        revealed = data.revealed;
        overlay.classList.remove('hidden');
        document.documentElement.classList.add('draw-open');
        Pokebeer.confetti.attach(overlay.querySelector('[data-draw-canvas]'));
        buildDots();
        if (finished()) summary(); else go(revealed); // reprise à la première carte non retournée ; un tirage terminé s'ouvre sur ses cinq bières
    }

    function close() {
        overlay.classList.add('hidden');
        document.documentElement.classList.remove('draw-open');
        stage.replaceChildren();
        entry.dataset.state = finished() ? 'done' : 'in_progress';
        opener.focus();
    }

    // ---- Progression ------------------------------------------------------------------------

    // Une pastille par carte : celles déjà retournées prennent la couleur de leur rareté et permettent d'y revenir
    function buildDots() {
        dots.replaceChildren(...cards.map((card, position) => {
            const dot = el('button');
            dot.type = 'button';
            dot.addEventListener('click', () => go(position));
            return dot;
        }));
    }

    function updateDots(showing = true) {
        [...dots.children].forEach((dot, position) => {
            const known = position < revealed;
            dot.disabled = !known || finished(); // tirage terminé : seul le résumé reste, on ne revient plus carte par carte
            dot.classList.toggle('is-current', showing && position === index);
            dot.setAttribute('aria-label', known ? `Revoir la carte ${position + 1} : ${cards[position].rarity_label}` : `Carte ${position + 1}`);
            if (known) dot.dataset.rarity = cards[position].rarity; else delete dot.dataset.rarity;
        });
    }

    // ---- Une carte --------------------------------------------------------------------------

    function buildCard(card, known) {
        const button = el('button', `draw-card ${known ? 'is-flipped is-instant' : 'is-entering'}`);
        button.type = 'button';
        button.dataset.rarity = card.rarity;
        button.setAttribute('aria-label', known ? `${card.rarity_label} : ${card.name}` : `Carte ${index + 1} sur ${cards.length} : retourner`);

        const inner = el('span', 'draw-card-inner');
        const back = el('span', 'draw-face draw-back');
        back.append(template('draw-back-icon'));

        const front = el('span', 'draw-face draw-front');
        const picture = el('span', 'draw-front-image');
        if (card.image) {
            const image = el('img');
            image.src = card.image;
            image.alt = '';
            image.decoding = 'async';
            picture.append(image);
        } else {
            picture.append(template('draw-beer-icon'));
        }
        const body = el('span', 'draw-front-body');
        body.append(el('span', 'draw-front-name', card.name), el('span', 'draw-front-meta', cardMeta(card)));
        front.append(picture, body, el('span', 'draw-ribbon', card.rarity_label));

        inner.append(back, front);
        button.append(inner);
        return button;
    }

    // Affiche la carte `position` : déjà retournée, elle apparaît face visible avec ses actions ; sinon, face cachée à retourner
    function go(position) {
        index = position;
        const card = cards[index];
        const known = index < revealed;
        const button = buildCard(card, known);
        const hint = el('p', 'draw-hint', known ? card.rarity_label : 'Touchez la carte pour la retourner');
        stage.replaceChildren(button, hint);
        if (known) {
            overlay.dataset.rarity = card.rarity;
            stage.append(buildActions(card));
        } else {
            overlay.removeAttribute('data-rarity');
            button.addEventListener('click', () => reveal(button, hint), { once: true });
        }
        updateDots();
        button.focus({ preventScroll: true });
    }

    async function reveal(button, hint) {
        const card = cards[index];
        const effect = EFFECTS[card.rarity];
        button.disabled = true;
        hint.textContent = '';
        if (effect.suspense) {
            button.classList.add('is-charging');
            await pause(effect.suspense);
            button.classList.remove('is-charging');
        }
        button.classList.remove('is-entering');
        button.classList.add('is-flipped');
        button.setAttribute('aria-label', `${card.rarity_label} : ${card.name}`);
        overlay.dataset.rarity = card.rarity;
        revealed = Math.max(revealed, index + 1);
        updateDots();
        save();
        await pause(450);
        celebrate(button, effect);
        hint.textContent = card.rarity_label;
        stage.append(buildActions(card));
    }

    // Le serveur retient la progression ; un échec n'interrompt pas le tirage (la reprise se fera alors un peu plus tôt)
    function save() {
        post(entry.dataset.revealUrl, { count: revealed }).catch(() => {});
    }

    function celebrate(button, effect) {
        if (!effect.count) return;
        const box = button.getBoundingClientRect();
        const x = box.left + box.width / 2;
        const y = box.top + box.height / 2;
        Pokebeer.confetti.burst(x, y, effect.count, Math.PI * 1.4, effect.colors);
        if (effect.flash && !reduced()) {
            overlay.classList.add('is-flash');
            setTimeout(() => overlay.classList.remove('is-flash'), 700);
            setTimeout(() => Pokebeer.confetti.burst(x, y, effect.count, Math.PI * 1.8, effect.colors), 350);
        }
        if (effect.vibrate && navigator.vibrate) navigator.vibrate(effect.vibrate);
    }

    // ---- Actions après la révélation ---------------------------------------------------------

    function buildActions(card) {
        const isLast = index === cards.length - 1;
        const actions = el('div', 'draw-actions');

        // La liste « À goûter » passe par wishlist.js (toggleWishlist) : même point d'entrée et mêmes icônes que le reste du site
        const wishlist = el('button', 'btn btn-outline btn-sm');
        wishlist.type = 'button';
        wishlist.dataset.onClick = 'toggleWishlist';
        wishlist.dataset.args = JSON.stringify([card.slug]);
        const icon = template('draw-wishlist-icon');
        icon.id = `wishlist-icon-${card.slug}`;
        icon.setAttribute('fill', card.in_wishlist ? 'currentColor' : 'none');
        wishlist.append(icon, 'À goûter');

        const tasted = el('a', 'btn btn-outline btn-sm', 'Déjà goûtée ?');
        tasted.href = card.rate_url;

        // Revoir une carte déjà ouverte : « Suivante » avance d'une carte, sans attendre ; la dernière mène au résumé
        const label = isLast ? 'Voir mon tirage' : `Carte suivante (${index + 2}/${cards.length})`;
        const next = el('button', 'btn btn-primary', label);
        next.type = 'button';
        next.addEventListener('click', () => (isLast ? summary() : go(index + 1)), { once: true });

        const details = el('a', 'btn btn-ghost btn-sm', 'Voir la fiche');
        details.href = card.beer_url;

        const row = el('div', 'draw-actions-row');
        row.append(wishlist, tasted);
        actions.append(row, next, details);
        next.focus({ preventScroll: true });
        return actions;
    }

    // ---- Résumé -----------------------------------------------------------------------------

    function summary() {
        updateDots(false);
        overlay.removeAttribute('data-rarity');
        const grid = el('div', 'draw-summary');
        cards.forEach((card, position) => {
            const link = el('a');
            link.href = card.beer_url;
            link.dataset.rarity = card.rarity;
            link.style.animationDelay = `${position * 80}ms`;
            link.append(el('small', '', card.rarity_label), el('span', 'font-semibold leading-tight line-clamp-2', card.name));
            grid.append(link);
        });
        const done = el('button', 'btn btn-primary w-full max-w-xs', 'Terminer');
        done.type = 'button';
        done.addEventListener('click', close);
        stage.replaceChildren(el('p', 'draw-hint', `Vos ${cards.length} bières du jour. Revenez demain !`), grid, done);
        done.focus({ preventScroll: true });
    }

    opener.addEventListener('click', open);
    overlay.querySelector('[data-draw-close]').addEventListener('click', close);
    document.addEventListener('keydown', event => {
        if (event.key === 'Escape' && !overlay.classList.contains('hidden')) close();
    });
})();
