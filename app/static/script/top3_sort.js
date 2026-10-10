// Top 3 du profil : glisser la poignée (souris, doigt) ou utiliser les flèches haut et bas pour réordonner ; toucher une ligne ouvre le choix de la bière.
// Le nouvel ordre est envoyé au serveur (permutation des emplacements 1, 2, 3) puis la page se recharge pour rester fidèle à la base.
(function () {
    const list = document.getElementById('top-beers-container');
    if (!list) return;
    const status = document.getElementById('top-status');
    const token = (document.querySelector('meta[name="csrf-token"]') || {}).content || '';
    const DRAG_CLASSES = ['ring-2', 'ring-primary', 'shadow-lg', 'scale-[1.02]', 'z-10', 'relative'];
    let dragged = null;
    let startOrder = null;
    let saveTimer = null;

    const rows = () => Array.from(list.children);
    const order = () => rows().map(row => row.dataset.slot);
    const announce = message => { if (status) status.textContent = message; };

    function renumber() {
        rows().forEach((row, index) => { row.querySelector('[data-rank]').textContent = '#' + (index + 1); });
    }

    function save() {
        clearTimeout(saveTimer);
        const now = order();
        if (!startOrder || now.join() === startOrder.join()) { startOrder = null; return; }
        fetch(list.dataset.url, {
            method: 'POST',
            credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': token },
            body: JSON.stringify({ order: now.map(Number) }),
        }).then(response => response.json()).catch(() => null).then(() => window.location.reload());
    }

    // Toucher une ligne : choisir ou changer la bière de cet emplacement
    list.addEventListener('click', event => {
        const open = event.target.closest('[data-open-top]');
        if (!open) return;
        const dialog = document.getElementById('modal_top_beer_' + open.closest('li').dataset.slot);
        if (dialog) dialog.showModal();
    });

    // Glisser : la ligne est déplacée dans la liste au fur et à mesure que le doigt passe le milieu des autres
    list.addEventListener('pointerdown', event => {
        const handle = event.target.closest('[data-drag-handle]');
        if (!handle) return;
        event.preventDefault();
        dragged = handle.closest('li');
        startOrder = order();
        handle.setPointerCapture(event.pointerId);
        dragged.classList.add(...DRAG_CLASSES);
    });

    list.addEventListener('pointermove', event => {
        if (!dragged) return;
        const others = rows().filter(row => row !== dragged);
        const target = others.filter(row => {
            const box = row.getBoundingClientRect();
            return box.top + box.height / 2 < event.clientY;
        }).length;
        if (target !== rows().indexOf(dragged)) {
            list.insertBefore(dragged, others[target] || null);
            renumber();
        }
    });

    function drop() {
        if (!dragged) return;
        dragged.classList.remove(...DRAG_CLASSES);
        dragged = null;
        save();
    }
    list.addEventListener('pointerup', drop);
    list.addEventListener('pointercancel', drop);

    // Clavier : la poignée prend le focus ; flèches haut et bas déplacent la bière d'un cran
    list.addEventListener('keydown', event => {
        const handle = event.target.closest('[data-drag-handle]');
        if (!handle || !['ArrowUp', 'ArrowDown'].includes(event.key)) return;
        event.preventDefault();
        const row = handle.closest('li');
        if (!startOrder) startOrder = order();
        if (event.key === 'ArrowUp' && row.previousElementSibling) list.insertBefore(row, row.previousElementSibling);
        if (event.key === 'ArrowDown' && row.nextElementSibling) list.insertBefore(row.nextElementSibling, row);
        renumber();
        handle.focus();
        announce('Position ' + (rows().indexOf(row) + 1) + ' sur ' + rows().length);
        clearTimeout(saveTimer);
        saveTimer = setTimeout(save, 700);
    });
})();
