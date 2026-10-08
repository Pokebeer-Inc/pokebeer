// Envoi d'une image au serveur pour analyse d'étiquette, et remplissage du formulaire avec la réponse.
// Partagé par le scanner en direct et par le choix d'une photo : un seul chemin vers le serveur, un seul remplissage.
(function (root) {
    'use strict';

    const MAX_WIDTH = 800;
    const JPEG_QUALITY = 0.8;

    // Champ du formulaire <- clé de la réponse ; `capitalize` : première lettre en majuscule, le reste en minuscules
    const FIELDS = [
        { id: 'id_beer-name', key: 'name', capitalize: true },
        { id: 'id_beer-brewery_name', key: 'brewery', capitalize: true },
        { id: 'id_beer-style', key: 'style' },
        { id: 'id_beer-degree', key: 'degree' },
        { id: 'id_beer-bitterness', key: 'bitterness' },
    ];

    class LabelScanClient {
        /** `eanUrl` : adresse de la recherche par code-barres (facultative si la page ne propose que l'analyse d'étiquette). */
        constructor(url, csrfToken, eanUrl) {
            this.url = url;
            this.csrfToken = csrfToken;
            this.eanUrl = eanUrl;
        }

        async post(url, body) {
            let response;
            try {
                response = await fetch(url, { method: 'POST', body, headers: { 'X-CSRFToken': this.csrfToken }, credentials: 'same-origin' });
            } catch (error) {
                throw new Error('Impossible de joindre le serveur.');
            }
            return response.json().catch(() => ({}));
        }

        /** Réduit une image (vidéo, image ou bitmap) à 800 px de large au plus et la renvoie en JPEG. */
        static toJpeg(source, width, height) {
            const scale = Math.min(1, MAX_WIDTH / width);
            const canvas = document.createElement('canvas');
            canvas.width = Math.round(width * scale);
            canvas.height = Math.round(height * scale);
            canvas.getContext('2d').drawImage(source, 0, 0, canvas.width, canvas.height);
            return new Promise((resolve, reject) => canvas.toBlob(blob => blob ? resolve(blob) : reject(new Error('Image illisible')), 'image/jpeg', JPEG_QUALITY));
        }

        /** Envoie l'image ; renvoie { found: true, data } ou { found: false } ; lève une Error (message affichable) en cas d'échec. */
        async analyze(blob) {
            const body = new FormData();
            body.append('image', blob, 'label.jpg');
            const result = await this.post(this.url, body);
            if (result.success) return { found: true, data: result.data };
            if (result.not_found) return { found: false };
            throw new Error(typeof result.error === 'string' ? result.error : "L'analyse de l'étiquette a échoué.");
        }

        /** Cherche une bière par code-barres : { source: 'catalog', existing } | { found: true, data, ean } | { found: false }. */
        async lookupEan(code) {
            const body = new FormData();
            body.append('ean', code);
            const result = await this.post(this.eanUrl, body);
            if (result.success && result.source === 'catalog') return { source: 'catalog', existing: result.existing };
            if (result.success) return { found: true, data: result.data, ean: result.ean };
            if (result.not_found) return { found: false };
            throw new Error(typeof result.error === 'string' ? result.error : 'La recherche par code-barres a échoué.');
        }
    }

    /** Remplit le formulaire d'ajout avec une bière reconnue ; la photo (si elle existe) illustre aussi l'avis, le code-barres est mémorisé. */
    function fillForm(data, blob, ean) {
        FIELDS.forEach(({ id, key, capitalize }) => {
            const value = data[key];
            const field = document.getElementById(id);
            if (value === null || value === undefined || value === '' || !field) return;
            const text = String(value);
            field.value = capitalize ? text.charAt(0).toUpperCase() + text.slice(1).toLowerCase() : text;
            field.dispatchEvent(new Event('input'));
        });
        const eanField = document.getElementById('id_beer-ean');
        if (eanField) eanField.value = ean || '';
        const photo = document.getElementById('id_drink-photo');
        if (blob && photo && window.ImageFields) {
            window.ImageFields.preset(photo, new File([blob], 'tasting.jpg', { type: 'image/jpeg' }));
        }
    }

    root.LabelScan = { Client: LabelScanClient, fillForm };
})(window);
