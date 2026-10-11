// Vérifie le comportement de pending.js (exécuté par tests/unit/test_pending_feedback.py avec Node) sur un DOM minimal.
const assert = require('node:assert/strict');

class Node_ {
    constructor(tag) {
        this.tag = tag; this.dataset = {}; this.attrs = {}; this.children = []; this.classes = new Set(); this.disabled = false;
        this.classList = {
            add: name => this.classes.add(name), remove: name => this.classes.delete(name), contains: name => this.classes.has(name),
            toggle: (name, force) => (force ? this.classes.add(name) : this.classes.delete(name)),
        };
    }
    setAttribute(name, value) { this.attrs[name] = String(value); }
    removeAttribute(name) { delete this.attrs[name]; }
    matches(selector) { return selector.split(',').map(part => part.trim()).some(part => part === this.tag || (part.startsWith('.') && this.classes.has(part.slice(1)))); }
    prepend(child) { this.children.unshift(child); }
    querySelector() { return this.children.find(child => child.dataset.pendingSpinner !== undefined) || null; }
}
class Button extends Node_ { constructor() { super('button'); } }
Node_.prototype.remove = function () {};
const listeners = {};
global.HTMLButtonElement = Button;
global.HTMLInputElement = class extends Node_ {};
global.document = {
    addEventListener: (type, handler) => { listeners[type] = handler; },
    createElement: tag => { const node = new Node_(tag); node.remove = function () { parent.children.splice(parent.children.indexOf(this), 1); }; return node; },
    querySelectorAll: () => [],
};
global.window = { addEventListener: () => {} };
let parent = null;
require('../../app/static/script/pending.js');
const { Pending } = global.window;

(async () => {
    const button = new Button();
    parent = button;

    // start : grisé, cercle ajouté, aria-busy ; un second appel est ignoré
    assert.equal(Pending.start(button), true);
    assert.equal(button.disabled, true);
    assert.equal(button.attrs['aria-busy'], 'true');
    assert.ok(button.classes.has('pb-pending'));
    assert.equal(button.children.length, 1);
    assert.equal(Pending.start(button), false);
    assert.equal(button.children.length, 1);

    // stop : tout est restitué
    Pending.stop(button);
    assert.equal(button.disabled, false);
    assert.equal(button.attrs['aria-busy'], undefined);
    assert.equal(button.children.length, 0);
    assert.ok(!button.classes.has('pb-pending'));

    // Un bouton déjà désactivé le reste après l'attente
    button.disabled = true;
    Pending.start(button); Pending.stop(button);
    assert.equal(button.disabled, true);
    button.disabled = false;

    // run : rend la valeur, restitue l'élément même en cas d'erreur, ignore l'appui répété
    assert.equal(await Pending.run(button, async () => 42), 42);
    assert.equal(button.disabled, false);
    await assert.rejects(Pending.run(button, async () => { throw new Error('boom'); }), /boom/);
    assert.equal(button.disabled, false);
    assert.ok(!button.dataset.pending);
    let calls = 0;
    const slow = Pending.run(button, () => new Promise(resolve => setTimeout(() => { calls += 1; resolve(1); }, 5)));
    assert.equal(await Pending.run(button, () => { calls += 100; }), undefined);  // appui répété ignoré
    await slow;
    assert.equal(calls, 1);

    // region : estompe et rétablit
    const zone = new Node_('div');
    Pending.region(zone, true);
    assert.ok(zone.classes.has('pb-region') && zone.attrs['aria-busy'] === 'true');
    Pending.region(zone, false);
    assert.ok(!zone.classes.has('pb-region') && zone.attrs['aria-busy'] === undefined);
    Pending.region(null, true);  // sans élément : rien ne se passe

    // htmx : la zone cible est estompée pendant la requête
    const target = new Node_('div');
    listeners['htmx:beforeRequest']({ detail: { target } });
    assert.ok(target.classes.has('pb-region'));
    listeners['htmx:afterRequest']({ detail: { target } });
    assert.ok(!target.classes.has('pb-region'));
    console.log('ok');
})().catch(error => { console.error(error); process.exit(1); });
