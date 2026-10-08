// Vérifie le décodeur EAN sur des codes-barres synthétiques (exécuté par tests/unit/test_label_scanner_front.py avec Node).
const assert = require('node:assert/strict');
const D = require('../../app/static/script/ean_decoder.js');

const L = ['0001101', '0011001', '0010011', '0111101', '0100011', '0110001', '0101111', '0111011', '0110111', '0001011'];
const R = L.map(p => p.split('').map(b => b === '1' ? '0' : '1').join(''));
const G = R.map(p => p.split('').reverse().join('')); // le code G est le miroir du code R
const PARITY = ['LLLLLL', 'LLGLGG', 'LLGGLG', 'LLGGGL', 'LGLLGG', 'LGGLLG', 'LGGGLL', 'LGLGLG', 'LGLGGL', 'LGGLGL'];

function check(code) {
    let total = 0;
    for (let i = code.length - 1, w = 3; i >= 0; i--, w = 4 - w) total += Number(code[i]) * w;
    return String((10 - total % 10) % 10);
}
function modules(code) {
    if (code.length === 13) {
        const left = PARITY[Number(code[0])].split('').map((s, i) => (s === 'L' ? L : G)[Number(code[1 + i])]).join('');
        const right = code.slice(7).split('').map(d => R[Number(d)]).join('');
        return '101' + left + '01010' + right + '101';
    }
    return '101' + code.slice(0, 4).split('').map(d => L[Number(d)]).join('') + '01010' + code.slice(4).split('').map(d => R[Number(d)]).join('') + '101';
}
// Rangée de pixels : `scale` pixels par module, marge claire de 10 modules, flou léger et bruit déterministe optionnels
function row(code, { scale = 3, blur = false, noise = 0, quiet = 10, dark = 30, light = 225 } = {}) {
    const bars = '0'.repeat(quiet) + modules(code) + '0'.repeat(quiet);
    const pixels = [];
    for (const bit of bars) for (let k = 0; k < scale; k++) pixels.push(bit === '1' ? dark : light);
    let out = pixels;
    if (blur) out = pixels.map((v, i) => ((pixels[i - 1] ?? v) + v + (pixels[i + 1] ?? v)) / 3);
    let seed = 7;
    return Float64Array.from(out, v => { seed = (seed * 16807) % 2147483647; return v + noise * ((seed / 2147483647) - 0.5) * 2; });
}
const image = (rowPixels, height = 40) => ({ gray: Uint8ClampedArray.from({ length: rowPixels.length * height }, (_, i) => rowPixels[i % rowPixels.length]), width: rowPixels.length, height });

const EAN13 = ['5410228142218', '3017620422003', '4006381333931', '8712000900045', '0012345678905', '9780201379624'];
const EAN8 = ['96385074', '73513537', '65833254'];

// Les codes de test sont bien valides (le générateur et la clé concordent)
[...EAN13, ...EAN8].forEach(code => assert.equal(D.isValid(code), true, code));

// isValid : clé, longueur, caractères
assert.equal(D.isValid('5410228142219'), false);
assert.equal(D.isValid('012345678905'), true); // UPC-A
assert.equal(D.isValid('541022814221'), false); // longueur à 12 mais clé fausse
['', '123', '54102281422180', '541022814221x', null, undefined, 5410228142218, '٥٤١٠٢٢٨١٤٢٢١٨'].forEach(bad => assert.equal(D.isValid(bad), false, String(bad)));

// Décodage net, plusieurs échelles
for (const code of [...EAN13, ...EAN8]) for (const scale of [2, 3, 4, 6]) assert.equal(D.decodeRow(row(code, { scale })), code, `${code} x${scale}`);

// Code à l'envers
for (const code of ['5410228142218', '96385074']) assert.equal(D.decodeRow(Float64Array.from(row(code)).reverse()), code);

// Flou léger et bruit
for (const code of EAN13) assert.equal(D.decodeRow(row(code, { scale: 4, blur: true, noise: 18 })), code, `bruit ${code}`);

// Éclairage inégal : dégradé ajouté
const base = row('5410228142218', { scale: 4 });
const graded = Float64Array.from(base, (v, i) => v * (0.6 + 0.4 * i / base.length));
assert.equal(D.decodeRow(graded), '5410228142218');

// Une erreur de chiffre n'est jamais prise pour un autre code : on obtient null
const wrong = '5410228142219';
assert.equal(D.decodeRow(row(wrong)), null);

// Pas de code : bruit pur, fond uni, motif régulier, ligne vide
let seed = 99;
const rnd = () => { seed = (seed * 16807) % 2147483647; return seed / 2147483647; };
for (let trial = 0; trial < 200; trial++) assert.equal(D.decodeRow(Float64Array.from({ length: 400 }, () => rnd() * 255)), null);
assert.equal(D.decodeRow(new Float64Array(300).fill(128)), null);
assert.equal(D.decodeRow(Float64Array.from({ length: 300 }, (_, i) => (i % 6 < 3 ? 20 : 230))), null);
assert.equal(D.decodeRow(new Float64Array(0)), null);

// decodeImage : le code n'est lu que sur une partie des lignes (haut de l'image vide)
const { gray, width, height } = image(row('3017620422003', { scale: 3 }), 60);
for (let i = 0; i < width * 15; i++) gray[i] = 200;
assert.equal(D.decodeImage(gray, width, height), '3017620422003');
assert.equal(D.decodeImage(new Uint8ClampedArray(100 * 100).fill(90), 100, 100), null);

console.log('ok');
