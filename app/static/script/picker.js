// Sélecteur de dégustations (partials/drink_picker.html) : recherche côté serveur, chargement progressif, sélection conservée d'une page à
// l'autre. Seules les premières lignes sont dans la page : la sélection vit dans un ensemble (Set), appliqué à chaque ligne chargée, et les
// choix qui ne sont pas affichés partent avec le formulaire sous forme de champs cachés. Les lignes viennent du serveur (gabarit échappé).
(function () {
    const SEARCH_DELAY = 300;
    const states = new WeakMap();
    const split = value => (value || '').split(',').filter(Boolean);
    const inputsOf = picker => Array.from(picker.querySelectorAll('[data-picker-rows] [data-picker-item] input'));

    function state(picker) {
        if (!states.has(picker)) {
            states.set(picker, {
                selected: new Set(split(picker.dataset.selected)),
                disabledBeers: new Set(split(picker.dataset.disabledBeers)),
                offset: inputsOf(picker).length,
                query: '',
            });
        }
        return states.get(picker);
    }

    function isRadio(picker) {
        return picker.querySelector('[data-picker-item] input')?.type === 'radio';
    }

    // Applique la sélection en cours aux lignes affichées (cases cochées, bières indisponibles, bières retirées masquées)
    function render(picker) {
        const current = state(picker);
        const hideDeleted = picker.dataset.hideDeleted === 'true';
        picker.querySelectorAll('[data-picker-item]').forEach(row => {
            const input = row.querySelector('input');
            const chosen = input.value ? current.selected.has(input.value) : current.selected.size === 0;
            input.checked = chosen;
            input.disabled = !chosen && current.disabledBeers.has(row.dataset.beerSlug);
            row.classList.toggle('opacity-50', input.disabled);
            row.hidden = hideDeleted && row.dataset.isDeleted === 'true' && !chosen;
        });
        const count = picker.querySelector('[data-picker-count]');
        if (count) count.textContent = current.selected.size;
        picker.dispatchEvent(new CustomEvent('picker:rows', { bubbles: true }));
    }

    function load(picker, append) {
        const current = state(picker);
        const url = new URL(picker.dataset.pickerUrl, window.location.origin);
        url.searchParams.set('offset', append ? current.offset : 0);
        if (current.query) url.searchParams.set('q', current.query);
        const more = picker.querySelector('[data-picker-more]');
        if (more) more.disabled = true;
        return fetch(url, { headers: { 'X-Requested-With': 'XMLHttpRequest' }, credentials: 'same-origin' })
            .then(response => {
                if (!response.ok) throw new Error('Chargement impossible');
                return response.json();
            })
            .then(data => {
                const rows = picker.querySelector('[data-picker-rows]');
                if (!append) rows.textContent = '';
                rows.insertAdjacentHTML('beforeend', data.html || '');
                current.offset = inputsOf(picker).length;
                if (more) more.hidden = !data.has_more;
                picker.querySelector('[data-picker-empty]').hidden = current.offset > 0;
                render(picker);
            })
            .catch(() => { if (more) more.hidden = false; })
            .finally(() => { if (more) more.disabled = false; });
    }

    const searchLater = new WeakMap();
    document.addEventListener('input', event => {
        const picker = event.target.closest('[data-picker]');
        if (!picker || !event.target.matches('[data-picker-search]')) return;
        state(picker).query = event.target.value.trim();
        clearTimeout(searchLater.get(picker));
        searchLater.set(picker, setTimeout(() => load(picker, false), SEARCH_DELAY));
    });

    document.addEventListener('change', event => {
        const picker = event.target.closest('[data-picker]');
        if (!picker || !event.target.matches('[data-picker-item] input')) return;
        const { selected } = state(picker);
        const input = event.target;
        if (input.type === 'radio') {
            selected.clear();
            if (input.value) selected.add(input.value);
        } else if (input.checked) {
            selected.add(input.value);
        } else {
            selected.delete(input.value);
        }
        render(picker);
    });

    document.addEventListener('click', event => {
        const picker = event.target.closest('[data-picker]');
        if (!picker) return;
        if (event.target.closest('[data-picker-more]')) {
            load(picker, true);
        } else if (event.target.closest('[data-picker-all]')) {
            inputsOf(picker).forEach(input => {
                if (!input.disabled && !input.closest('[data-picker-item]').hidden) state(picker).selected.add(input.value);
            });
            render(picker);
        } else if (event.target.closest('[data-picker-none]')) {
            state(picker).selected.clear();
            render(picker);
        }
    });

    // Entrée dans la recherche ne doit pas envoyer le formulaire
    document.addEventListener('keydown', event => {
        if (event.key === 'Enter' && event.target.matches && event.target.matches('[data-picker-search]')) event.preventDefault();
    });

    // À l'envoi : les choix qui ne sont pas parmi les lignes affichées partent en champs cachés (même nom que les cases)
    document.addEventListener('submit', event => {
        event.target.querySelectorAll('[data-picker]').forEach(picker => {
            picker.querySelectorAll('input[data-picker-hidden]').forEach(input => input.remove());
            const shown = new Set(inputsOf(picker).filter(input => input.checked).map(input => input.value));
            state(picker).selected.forEach(value => {
                if (shown.has(value)) return;
                const hidden = document.createElement('input');
                hidden.type = 'hidden';
                hidden.name = picker.dataset.pickerName;
                hidden.value = value;
                hidden.dataset.pickerHidden = '';
                picker.appendChild(hidden);
            });
        });
    }, true);

    // Réinitialise un sélecteur (ex. la fenêtre de la carte qui passe d'un lieu à l'autre)
    window.PokebeerPicker = {
        reset(picker, { selected = [], disabledBeers = [] } = {}) {
            const current = state(picker);
            current.selected = new Set(selected);
            current.disabledBeers = new Set(disabledBeers);
            render(picker);
        },
    };

    function initAll() {
        document.querySelectorAll('[data-picker]').forEach(render);
    }
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', initAll); else initAll();
})();
