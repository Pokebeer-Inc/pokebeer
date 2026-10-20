// Comparaison de textes sans tenir compte de la casse ni des accents (même règle que app/domain/text.py côté serveur).
function normalizeText(value) {
    return String(value || '').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '').trim();
}
