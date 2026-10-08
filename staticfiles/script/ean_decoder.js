// Lecture de codes-barres EAN-13 et EAN-8 sur une image en niveaux de gris, sans bibliothèque extérieure.
// Principe : une ligne de pixels est binarisée, découpée en barres et espaces, puis comparée aux motifs EAN ; la clé de contrôle
// valide le résultat (une erreur de lecture passe pour un code inconnu, jamais pour un autre code). Fonctions pures, testées avec Node.
(function (root) {
    'use strict';

    // Largeurs (en modules) des quatre éléments de chaque chiffre : espace, barre, espace, barre pour la moitié gauche
    const L = [[3, 2, 1, 1], [2, 2, 2, 1], [2, 1, 2, 2], [1, 4, 1, 1], [1, 1, 3, 2], [1, 2, 3, 1], [1, 1, 1, 4], [1, 3, 1, 2], [1, 2, 1, 3], [3, 1, 1, 2]];
    const G = L.map(pattern => pattern.slice().reverse());
    // Parité des six chiffres de gauche : elle porte le premier chiffre de l'EAN-13
    const PARITY = ['LLLLLL', 'LLGLGG', 'LLGGLG', 'LLGGGL', 'LGLLGG', 'LGGLLG', 'LGGGLL', 'LGLGLG', 'LGLGGL', 'LGGLGL'];
    const MAX_DIGIT_ERROR = 1.0;   // écart toléré (en modules) entre un chiffre lu et son motif
    const MAX_GUARD_SKEW = 0.6;    // les trois éléments d'un repère de bord doivent avoir à peu près la même largeur
    const MIN_CONTRAST = 40;       // écart de gris minimal dans un voisinage pour y voir des barres
    const QUIET_ZONE = 4;          // marge claire minimale avant le code, en largeurs de repère

    /** Clé de contrôle EAN valide ? (8, 12 ou 13 chiffres) */
    function isValid(code) {
        if (typeof code !== 'string' || ![8, 12, 13].includes(code.length) || !/^[0-9]+$/.test(code)) return false;
        let total = 0;
        for (let i = code.length - 2, weight = 3; i >= 0; i--, weight = 4 - weight) total += Number(code[i]) * weight;
        return (10 - total % 10) % 10 === Number(code[code.length - 1]);
    }

    /** Ligne de gris -> tableau de booléens (vrai = sombre). Seuil local au milieu de l'étendue des gris voisins, pour tolérer
     *  un éclairage inégal ; une zone presque uniforme (marge blanche, bruit du capteur) est toujours claire. */
    function binarize(row) {
        const n = row.length;
        const half = Math.max(15, Math.floor(n / 8)) >> 1;
        const dark = new Array(n);
        for (let i = 0; i < n; i++) {
            let low = Infinity, high = -Infinity;
            for (let j = Math.max(0, i - half), end = Math.min(n, i + half + 1); j < end; j++) {
                if (row[j] < low) low = row[j];
                if (row[j] > high) high = row[j];
            }
            dark[i] = high - low >= MIN_CONTRAST && row[i] < (low + high) / 2;
        }
        return dark;
    }

    /** Suite de [sombre, largeur] pour chaque barre ou espace de la ligne. */
    function runLengths(dark) {
        const runs = [];
        let start = 0;
        for (let i = 1; i <= dark.length; i++) {
            if (i === dark.length || dark[i] !== dark[start]) {
                runs.push([dark[start], i - start]);
                start = i;
            }
        }
        return runs;
    }

    /** Fusionne les éclats d'un seul pixel (bruit du capteur près d'un bord) avec les barres voisines. */
    function despeckle(runs) {
        const cleaned = [];
        for (let i = 0; i < runs.length; i++) {
            const run = runs[i];
            if (run[1] === 1 && cleaned.length && i + 1 < runs.length) {
                // un pixel isolé prend la couleur de ses voisins : il s'ajoute au précédent, et le suivant (de la même couleur) le rejoint
                cleaned[cleaned.length - 1][1] += 1 + runs[i + 1][1];
                i++;
            } else if (cleaned.length && cleaned[cleaned.length - 1][0] === run[0]) {
                cleaned[cleaned.length - 1][1] += run[1];
            } else {
                cleaned.push([run[0], run[1]]);
            }
        }
        return cleaned;
    }

    /** Chiffre dont le motif ressemble le plus aux quatre largeurs ; renvoie { digit, set } ou null. */
    function matchDigit(widths, sets) {
        const total = widths[0] + widths[1] + widths[2] + widths[3];
        let best = null;
        for (const set of sets) {
            const table = set === 'G' ? G : L;
            for (let digit = 0; digit < 10; digit++) {
                let error = 0;
                for (let k = 0; k < 4; k++) error += Math.abs(widths[k] / total * 7 - table[digit][k]);
                if (!best || error < best.error) best = { digit, set, error };
            }
        }
        return best && best.error <= MAX_DIGIT_ERROR ? best : null;
    }

    function widthsAt(runs, index) {
        return [runs[index][1], runs[index + 1][1], runs[index + 2][1], runs[index + 3][1]];
    }

    /** Repère de bord à partir de `index` : trois éléments de largeurs voisines, le premier sombre. */
    function isGuard(runs, index, pattern) {
        if (index + pattern.length > runs.length) return false;
        const sample = runs.slice(index, index + pattern.length);
        if (sample.some((run, i) => run[0] !== pattern[i])) return false;
        const mean = sample.reduce((sum, run) => sum + run[1], 0) / sample.length;
        return sample.every(run => Math.abs(run[1] - mean) / mean <= MAX_GUARD_SKEW);
    }

    /** Lit un code dont le repère de début commence à runs[start] ; `digitsPerHalf` vaut 6 (EAN-13) ou 4 (EAN-8). */
    function readFrom(runs, start, digitsPerHalf) {
        const body = 3 + digitsPerHalf * 4 + 5 + digitsPerHalf * 4 + 3;
        if (start + body > runs.length) return null;
        const centre = start + 3 + digitsPerHalf * 4;
        const right = centre + 5;
        const end = right + digitsPerHalf * 4;
        if (!isGuard(runs, start, [true, false, true]) || !isGuard(runs, centre, [false, true, false, true, false]) || !isGuard(runs, end, [true, false, true])) return null;

        const left = [];
        for (let k = 0; k < digitsPerHalf; k++) {
            const match = matchDigit(widthsAt(runs, start + 3 + k * 4), digitsPerHalf === 6 ? ['L', 'G'] : ['L']);
            if (!match) return null;
            left.push(match);
        }
        let digits = left.map(match => match.digit).join('');
        let prefix = '';
        if (digitsPerHalf === 6) {
            const first = PARITY.indexOf(left.map(match => match.set).join(''));
            if (first < 0) return null;
            prefix = String(first);
        }
        for (let k = 0; k < digitsPerHalf; k++) {
            const match = matchDigit(widthsAt(runs, right + k * 4), ['L']);
            if (!match) return null;
            digits += match.digit;
        }
        const code = prefix + digits;
        return isValid(code) ? code : null;
    }

    /** Code lu sur une ligne de gris, ou null. Essaie l'EAN-13 puis l'EAN-8, dans les deux sens (code à l'envers). */
    function decodeRow(row) {
        const direction = [row, Array.from(row).reverse()];
        for (const candidate of direction) {
            const runs = despeckle(runLengths(binarize(candidate)));
            for (let i = 1; i < runs.length; i++) {
                if (!runs[i][0] || runs[i - 1][0]) continue; // début de barre précédé d'un espace
                const guardWidth = runs[i][1];
                if (i - 1 === 0 ? false : runs[i - 1][1] < guardWidth * QUIET_ZONE) continue;
                const code = readFrom(runs, i, 6) || readFrom(runs, i, 4);
                if (code) return code;
            }
        }
        return null;
    }

    /** Code lu sur une image en niveaux de gris (plusieurs lignes au milieu, chacune lissée sur trois pixels de hauteur). */
    function decodeImage(gray, width, height, rows = 11) {
        for (let r = 0; r < rows; r++) {
            const y = Math.round(height * (0.25 + 0.5 * r / Math.max(1, rows - 1)));
            const row = new Float64Array(width);
            for (let x = 0; x < width; x++) {
                let sum = 0, count = 0;
                for (let dy = -1; dy <= 1; dy++) {
                    const yy = y + dy;
                    if (yy >= 0 && yy < height) { sum += gray[yy * width + x]; count++; }
                }
                row[x] = sum / count;
            }
            const code = decodeRow(row);
            if (code) return code;
        }
        return null;
    }

    const api = { isValid, decodeRow, decodeImage };
    if (typeof module !== 'undefined' && module.exports) module.exports = api;
    else root.EanDecoder = api;
})(typeof window !== 'undefined' ? window : globalThis);
