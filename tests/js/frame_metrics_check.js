// Vérifie les mesures d'images du scanner (exécuté par tests/unit/test_label_scanner_front.py avec Node).
const assert = require('node:assert/strict');
const M = require('../../app/static/script/frame_metrics.js');

const W = 40, H = 30;
const flat = value => new Uint8ClampedArray(W * H).fill(value);
// Damier fin : beaucoup de contours et de contraste, comme du texte net
const checker = () => Uint8ClampedArray.from({ length: W * H }, (_, i) => ((i % W) + Math.floor(i / W)) % 2 ? 255 : 0);
// Dégradé doux : contraste mais aucun contour (image floue)
const gradient = () => Uint8ClampedArray.from({ length: W * H }, (_, i) => Math.round(((i % W) / (W - 1)) * 255));

// toGray : pondération de la luminance
assert.deepEqual(Array.from(M.toGray(Uint8ClampedArray.of(255, 0, 0, 255, 0, 255, 0, 255, 0, 0, 255, 255), 3, 1)), [76, 150, 29]);

// sharpness : plat ~0, flou faible, net élevé ; trop petit => 0
assert.equal(M.sharpness(flat(128), W, H), 0);
assert.ok(M.sharpness(gradient(), W, H) < 1);
assert.ok(M.sharpness(checker(), W, H) > 10000);
assert.equal(M.sharpness(new Uint8ClampedArray(4), 2, 2), 0);

// contrast
assert.equal(M.contrast(flat(200)), 0);
assert.ok(M.contrast(checker()) > 120);
assert.equal(M.contrast(new Uint8ClampedArray(0)), 0);

// motion : identique 0, inverse 1, tailles différentes ou absence d'image => 1 (par prudence)
assert.equal(M.motion(flat(10), flat(10)), 0);
assert.equal(M.motion(flat(0), flat(255)), 1);
assert.equal(M.motion(null, flat(10)), 1);
assert.equal(M.motion(new Uint8ClampedArray(3), flat(10)), 1);

// isReady : trois conditions à la fois
const good = { sharpness: 200, contrast: 50, motion: 0.01 };
assert.equal(M.isReady(good), true);
assert.equal(M.isReady({ ...good, sharpness: 10 }), false);
assert.equal(M.isReady({ ...good, contrast: 5 }), false);
assert.equal(M.isReady({ ...good, motion: 0.2 }), false);

// StabilityTracker
const { holdMs, graceMs } = M.THRESHOLDS;
let tracker = new M.StabilityTracker();
assert.deepEqual(tracker.update({ ...good, sharpness: 0 }, 0), { ready: false, progress: 0 });
tracker.update(good, 1000);
let half = tracker.update(good, 1000 + holdMs / 2);
assert.equal(half.ready, false);
assert.ok(Math.abs(half.progress - 0.5) < 1e-9);
assert.deepEqual(tracker.update(good, 1000 + holdMs), { ready: true, progress: 1 });

// un à-coup bref est toléré, un trou long remet à zéro
tracker = new M.StabilityTracker();
tracker.update(good, 0);
const blip = tracker.update({ ...good, motion: 0.5 }, graceMs - 1);
assert.ok(blip.progress > 0);
const after = tracker.update({ ...good, motion: 0.5 }, graceMs + 50);
assert.deepEqual(after, { ready: false, progress: 0 });
assert.equal(tracker.update(good, 5000).progress, 0); // le compte repart de zéro

// reset
tracker = new M.StabilityTracker();
tracker.update(good, 0);
tracker.reset();
assert.equal(tracker.update({ ...good, motion: 1 }, 10).progress, 0);

// Des seuils personnalisés sont respectés
const strict = new M.StabilityTracker({ ...M.THRESHOLDS, holdMs: 100 });
strict.update(good, 0);
assert.equal(strict.update(good, 100).ready, true);

console.log('ok');
