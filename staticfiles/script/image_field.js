// Champs photo des dégustations (partials/image_field.html) : aperçu, retrait et réduction avant envoi.
// Délégation d'événements : les modales chargées dynamiquement (« voir plus ») fonctionnent sans initialisation.
(function () {
    const MAX_SIDE = 1280;
    const QUALITY = 0.85;

    // Les photos de téléphone dépassent la limite de taille des requêtes : on les réduit côté navigateur (le serveur revalide et ré-encode)
    function shrink(file) {
        return new Promise(resolve => {
            const url = URL.createObjectURL(file);
            const img = new Image();
            img.onload = () => {
                URL.revokeObjectURL(url);
                const ratio = Math.min(1, MAX_SIDE / Math.max(img.width, img.height));
                const canvas = document.createElement('canvas');
                canvas.width = Math.round(img.width * ratio);
                canvas.height = Math.round(img.height * ratio);
                canvas.getContext('2d').drawImage(img, 0, 0, canvas.width, canvas.height);
                canvas.toBlob(blob => resolve(blob ? new File([blob], 'tasting.jpg', { type: 'image/jpeg' }) : file), 'image/jpeg', QUALITY);
            };
            img.onerror = () => { URL.revokeObjectURL(url); resolve(file); };
            img.src = url;
        });
    }

    function parts(input) {
        const root = input.closest('[data-image-field]');
        return {
            root,
            preview: root.querySelector('[data-image-preview]'),
            clear: root.querySelector('[data-image-clear]'),
            remove: root.querySelector('[data-image-remove]'),
            label: root.querySelector('[data-image-label]'),
            hint: root.querySelector('[data-image-hint]'),
        };
    }

    function show(input, src) {
        const { preview, clear, label } = parts(input);
        if (preview.dataset.objectUrl) URL.revokeObjectURL(preview.dataset.objectUrl);
        preview.dataset.objectUrl = src && src.startsWith('blob:') ? src : '';
        preview.src = src || '';
        preview.classList.toggle('hidden', !src);
        clear.classList.toggle('hidden', !src);
        label.textContent = src ? 'Changer' : 'Ajouter une photo';
    }

    async function setFile(input, file) {
        const reduced = await shrink(file);
        try {
            const transfer = new DataTransfer();
            transfer.items.add(reduced);
            input.files = transfer.files;
        } catch (error) {
            return; // navigateur sans DataTransfer : le fichier choisi reste tel quel
        }
        const { remove, hint } = parts(input);
        if (remove) remove.checked = false;
        if (hint) hint.classList.add('hidden');
        show(input, URL.createObjectURL(reduced));
    }

    document.addEventListener('change', event => {
        const input = event.target.closest('[data-image-input]');
        if (input && input.files[0]) setFile(input, input.files[0]);
    });

    document.addEventListener('click', event => {
        const button = event.target.closest('[data-image-clear]');
        if (!button) return;
        const input = button.closest('[data-image-field]').querySelector('[data-image-input]');
        const { root, remove, hint } = parts(input);
        input.value = '';
        if (hint) hint.classList.add('hidden');
        if (remove) remove.checked = Boolean(root.dataset.originalUrl);
        show(input, '');
    });

    // Prérempli une photo (ex. celle prise pour l'analyse IA) ; sans effet si le membre en a déjà choisi une
    window.ImageFields = {
        preset(input, file) {
            if (!input || input.files.length) return;
            setFile(input, file).then(() => {
                const { hint } = parts(input);
                if (hint && input.files.length) hint.classList.remove('hidden');
            });
        },
    };
})();
