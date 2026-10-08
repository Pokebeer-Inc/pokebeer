// Mesures sur une image réduite en niveaux de gris, pour décider quand une étiquette est « prête à être analysée » :
// nette, contrastée (il y a du texte ou un dessin, pas un mur) et immobile. Fonctions pures : aucune caméra, aucun DOM.
(function (root) {
    'use strict';

    // Seuils réglés pour une image réduite à ~160 px de large ; ajustables sans toucher à la logique
    const THRESHOLDS = Object.freeze({
        sharpness: 80,   // variance du laplacien : un flou franc donne moins de 40, une étiquette nette plusieurs centaines
        contrast: 25,    // écart-type des gris (0-255) : un fond uni est sous 10
        motion: 0.03,    // différence moyenne entre deux images (0-1) : au-delà, la caméra bouge
        holdMs: 1000,    // durée pendant laquelle les trois conditions doivent tenir
        graceMs: 300,    // un à-coup plus court que cela ne remet pas le compte à zéro
    });

    /** Niveaux de gris (Uint8ClampedArray width*height) depuis des pixels RGBA (ImageData.data). */
    function toGray(rgba, width, height) {
        const gray = new Uint8ClampedArray(width * height);
        for (let i = 0, p = 0; i < gray.length; i++, p += 4) {
            gray[i] = (rgba[p] * 299 + rgba[p + 1] * 587 + rgba[p + 2] * 114) / 1000;
        }
        return gray;
    }

    /** Netteté : variance du laplacien (noyau 4-voisins), classique pour détecter le flou. */
    function sharpness(gray, width, height) {
        if (width < 3 || height < 3) return 0;
        let sum = 0, sumSquares = 0, count = 0;
        for (let y = 1; y < height - 1; y++) {
            for (let x = 1; x < width - 1; x++) {
                const i = y * width + x;
                const laplacian = 4 * gray[i] - gray[i - 1] - gray[i + 1] - gray[i - width] - gray[i + width];
                sum += laplacian;
                sumSquares += laplacian * laplacian;
                count++;
            }
        }
        const mean = sum / count;
        return sumSquares / count - mean * mean;
    }

    /** Contraste : écart-type des niveaux de gris. */
    function contrast(gray) {
        if (!gray.length) return 0;
        let sum = 0, sumSquares = 0;
        for (let i = 0; i < gray.length; i++) {
            sum += gray[i];
            sumSquares += gray[i] * gray[i];
        }
        const mean = sum / gray.length;
        return Math.sqrt(Math.max(0, sumSquares / gray.length - mean * mean));
    }

    /** Mouvement : différence absolue moyenne entre deux images de même taille, de 0 (identiques) à 1. */
    function motion(previous, current) {
        if (!previous || previous.length !== current.length || !current.length) return 1;
        let total = 0;
        for (let i = 0; i < current.length; i++) total += Math.abs(current[i] - previous[i]);
        return total / current.length / 255;
    }

    /** Une image remplit-elle les conditions d'une étiquette prête à être lue ? */
    function isReady(measures, thresholds = THRESHOLDS) {
        return measures.sharpness >= thresholds.sharpness && measures.contrast >= thresholds.contrast && measures.motion <= thresholds.motion;
    }

    /** Suit la durée pendant laquelle l'image reste prête ; `update` renvoie { ready, progress } (progress de 0 à 1). */
    class StabilityTracker {
        constructor(thresholds = THRESHOLDS) {
            this.thresholds = thresholds;
            this.reset();
        }

        reset() {
            this.since = null;
            this.lastGood = null;
        }

        update(measures, now) {
            const { holdMs, graceMs } = this.thresholds;
            if (isReady(measures, this.thresholds)) {
                if (this.since === null) this.since = now;
                this.lastGood = now;
            } else if (this.lastGood === null || now - this.lastGood > graceMs) {
                this.reset();
            }
            const held = this.since === null ? 0 : now - this.since;
            return { ready: held >= holdMs, progress: Math.min(1, held / holdMs) };
        }
    }

    const api = { THRESHOLDS, toGray, sharpness, contrast, motion, isReady, StabilityTracker };
    if (typeof module !== 'undefined' && module.exports) module.exports = api;
    else root.FrameMetrics = api;
})(typeof window !== 'undefined' ? window : globalThis);
