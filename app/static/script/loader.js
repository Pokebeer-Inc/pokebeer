document.addEventListener('DOMContentLoaded', () => {
    const loader = document.getElementById('global-loader');
    if (!loader) return;

    const showLoader = () => {
        loader.classList.remove('hidden');
        loader.classList.add('flex');
    };

    const hideLoader = () => {
        loader.classList.add('hidden');
        loader.classList.remove('flex');
    };

    // 1. Interception des clics sur les liens
    document.addEventListener('click', (e) => {
        // Remonte l'arbre DOM pour trouver si le clic vient d'une balise <a>
        const link = e.target.closest('a');
        if (!link) return;

        const href = link.getAttribute('href');
        const target = link.getAttribute('target');
        const isAnchor = href && href.startsWith('#');
        const isJs = href && href.startsWith('javascript:');
        const isTel = href && href.startsWith('tel:');
        const isMailto = href && href.startsWith('mailto:');
        const isNewTab = target === '_blank';
        const hasDownload = link.hasAttribute('download');

        // Ne déclenche le loader que si c'est une vraie navigation vers une autre page (on exclut l'ouverture des apps natives)
        if (href && !isAnchor && !isJs && !isTel && !isMailto && !isNewTab && !hasDownload) {
            showLoader();
        }
    });

    // 2. Interception des soumissions de formulaires
    document.addEventListener('submit', (e) => {
        const form = e.target;

        if (form.id === 'age-form') {
            return;
        }

        // On ignore les formulaires de fermeture de modale DaisyUI
        if (form.getAttribute('method') === 'dialog') {
            return;
        }

        // On ignore les formulaires qui s'ouvrent dans un nouvel onglet
        if (form.getAttribute('target') === '_blank') {
            return;
        }

        showLoader();
    });

    // 3. Sécurité BFCache (Empêche le loader de rester affiché si l'utilisateur clique sur le bouton "Précédent" du navigateur)
    window.addEventListener('pageshow', (e) => {
        if (e.persisted) {
            hideLoader();
        }
    });
});