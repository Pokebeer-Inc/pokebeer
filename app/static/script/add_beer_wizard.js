// Ajout d'une bière par étapes. Un seul formulaire, des panneaux affichés un par un : le scanner, la vérification des doublons et
// tous les champs fonctionnent comme avant. Chaque étape validée est enregistrée côté serveur (brouillon) ; quitter la page enregistre aussi
// ce qui est saisi, sans validation. Sans JavaScript, toutes les étapes restent visibles.
document.addEventListener('DOMContentLoaded', function () {
    const form = document.getElementById('beer-wizard');
    if (!form) return;
    const panels = Array.from(form.querySelectorAll('[data-step]'));
    const total = panels.length;
    const numberEl = document.getElementById('wizard-number');
    const titleEl = document.getElementById('wizard-title');
    const bar = document.getElementById('wizard-bar');
    const progress = form.querySelector('.wizard-progress');
    const backBtn = document.getElementById('wizard-back');
    const nextBtn = document.getElementById('wizard-next');
    const errorsBox = document.getElementById('wizard-errors');
    const recap = document.getElementById('wizard-recap');
    const csrf = form.querySelector('[name=csrfmiddlewaretoken]').value;
    const eanField = form.querySelector('[name="beer-ean"]');
    const menuMode = form.dataset.mode === 'menu';  // ajout depuis la carte d'un bar : pas d'avis ni de contexte
    let current = 1;
    let dirty = false;
    let submitting = false;

    form.classList.add('wizard-on');

    const panelOf = number => panels[number - 1];

    function clearErrors() {
        errorsBox.classList.add('hidden');
        errorsBox.classList.remove('flex');
        errorsBox.replaceChildren();
    }

    function showErrors(messages, fieldIds) {
        errorsBox.replaceChildren(...messages.map(text => { const p = document.createElement('p'); p.textContent = text; return p; }));
        errorsBox.classList.remove('hidden');
        errorsBox.classList.add('flex');
        const field = fieldIds && fieldIds.length ? document.getElementById(fieldIds[0]) : null;
        (field || errorsBox).focus({ preventScroll: false });
    }

    function show(number, { push = true } = {}) {
        current = Math.min(Math.max(number, 1), total);
        panels.forEach((panel, index) => panel.classList.toggle('is-current', index + 1 === current));
        form.classList.toggle('on-last-step', current === total);
        numberEl.textContent = current;
        titleEl.textContent = panelOf(current).dataset.title;
        bar.style.width = (current / total * 100) + '%';
        progress.setAttribute('aria-valuenow', current);
        backBtn.disabled = current === 1;
        backBtn.classList.toggle('opacity-40', current === 1);
        clearErrors();
        if (current === total) buildRecap();
        if (push) history.pushState({ step: current }, '', '#step-' + current);
        window.scrollTo({ top: 0, behavior: 'smooth' });
    }

    // Champs d'une étape (hors fichiers, que le brouillon ne conserve pas)
    function controlsOf(panel, number) {
        const controls = Array.from(panel.querySelectorAll('input, select, textarea')).filter(c => c.type !== 'file' && c.name);
        if (number === 1 && eanField) controls.push(eanField);
        return controls;
    }

    function formDataFor(controls, step, strict) {
        const data = new FormData();
        data.append('csrfmiddlewaretoken', csrf);
        data.append('step', step);
        data.append('strict', strict ? '1' : '0');
        data.append('mode', form.dataset.mode || '');
        controls.forEach(control => {
            if ((control.type === 'radio' || control.type === 'checkbox') && !control.checked) return;
            data.append(control.name, control.value);
        });
        if (!menuMode && (controls.some(c => c.name === 'notebooks') || panelOf(step) === panels[4])) data.append('notebooks_present', '1');
        return data;
    }

    function nativeValid(panel) {
        const invalid = Array.from(panel.querySelectorAll('input, select, textarea')).find(c => c.type !== 'file' && !c.checkValidity());
        if (!invalid) return true;
        invalid.reportValidity();
        return false;
    }

    async function next() {
        const panel = panelOf(current);
        if (!nativeValid(panel)) return;
        if (!Pending.start(nextBtn)) return;
        clearErrors();
        try {
            const response = await fetch(form.dataset.draftUrl, { method: 'POST', credentials: 'same-origin', body: formDataFor(controlsOf(panel, current), current, true) });
            if (response.ok) { dirty = false; show(current + 1); return; }
            const data = await response.json().catch(() => ({ errors: ['Enregistrement impossible. Réessayez.'] }));
            showErrors(data.errors && data.errors.length ? data.errors : ['Enregistrement impossible. Réessayez.'], data.fields);
        } catch (error) {
            showErrors(['Connexion impossible. Vérifiez votre réseau puis réessayez.']);
        } finally {
            Pending.stop(nextBtn);
        }
    }

    function back() {
        if (current === 1) return;
        saveSoft(current); // on garde ce qui est saisi, sans le valider
        show(current - 1);
    }

    // Enregistrement sans validation : retour en arrière et fermeture de la page
    function saveSoft(step) {
        if (!dirty) return;
        const controls = Array.from(form.querySelectorAll('input, select, textarea')).filter(c => c.type !== 'file' && c.name && c.name !== 'csrfmiddlewaretoken');
        const data = formDataFor(controls, step, false);
        if (!menuMode) data.append('notebooks_present', '1');
        if (navigator.sendBeacon) navigator.sendBeacon(form.dataset.draftUrl, data);
        else fetch(form.dataset.draftUrl, { method: 'POST', credentials: 'same-origin', body: data, keepalive: true });
        dirty = false;
    }

    // Récapitulatif construit avec textContent : rien de saisi n'est inséré comme HTML
    function valueOf(name) {
        const control = form.querySelector('[name="' + name + '"]');
        return control && control.value ? control.value.trim() : '';
    }
    function choiceOf(name) {
        const checked = form.querySelector('[name="' + name + '"]:checked');
        if (!checked || !checked.value) return '';
        const label = checked.closest('label');
        return label ? label.textContent.trim() : checked.value;
    }
    function fileOf(name) {
        const input = form.querySelector('[name="' + name + '"]');
        return input && input.files && input.files.length ? input.files[0].name : '';
    }

    function buildRecap() {
        const rows = [
            ['Bière', valueOf('beer-name'), 1], ['Brasserie', valueOf('beer-brewery_name'), 1],
            ['Lieu de la brasserie', [valueOf('beer-brewery_postal_code'), valueOf('beer-brewery_city')].filter(Boolean).join(' '), 1],
            ['Alcool', valueOf('beer-degree') && valueOf('beer-degree') + ' %', 2], ['Style', valueOf('beer-style'), 2],
            ['Amertume', valueOf('beer-bitterness') && valueOf('beer-bitterness') + ' IBU', 2],
            ['Description', valueOf('beer-description').slice(0, 140), 3], ['Photo de la bière', fileOf('beer-image'), 3],
            ...(menuMode ? [
                ['Format à la carte', choiceOf('menu-serving_format'), 4], ['Prix à la carte', valueOf('menu-price') && valueOf('menu-price') + ' €', 4],
            ] : [
                ['Commentaire', valueOf('drink-comment').slice(0, 140), 4], ['Note', valueOf('drink-note') && valueOf('drink-note') + ' / 10', 4],
                ['Date', valueOf('drink-date'), 4], ['Photo de l\'avis', fileOf('drink-photo'), 4],
                ['Lieu', choiceOf('drink-venue_type'), 5], ['Avec qui', choiceOf('drink-company'), 5],
                ['Format', choiceOf('drink-serving_format'), 5], ['Prix', valueOf('drink-price') && valueOf('drink-price') + ' €', 5],
            ]),
        ];
        recap.replaceChildren(...rows.map(([label, value, step]) => {
            const row = document.createElement('button');
            row.type = 'button';
            row.className = 'recap-row';
            row.dataset.goto = step;
            const dt = document.createElement('dt');
            dt.textContent = label;
            const dd = document.createElement('dd');
            dd.textContent = value || 'Non renseigné';
            if (!value) dd.className = 'is-empty';
            row.append(dt, dd);
            return row;
        }));
    }

    recap.addEventListener('click', event => {
        const row = event.target.closest('[data-goto]');
        if (row) show(Number(row.dataset.goto));
    });

    nextBtn.addEventListener('click', next);
    backBtn.addEventListener('click', back);

    // Entrée valide l'étape au lieu d'envoyer le formulaire ; seule la dernière étape l'envoie
    form.addEventListener('keydown', event => {
        if (event.key !== 'Enter' || event.target.tagName === 'TEXTAREA' || event.target.type === 'submit' || event.target.type === 'button') return;
        event.preventDefault();
        if (current < total) next();
    });

    // Dernier envoi : toutes les étapes sont revérifiées ; la première incomplète est rouverte
    form.addEventListener('submit', event => {
        const incomplete = panels.findIndex(panel => !Array.from(panel.querySelectorAll('input, select, textarea')).every(c => c.type === 'file' || c.checkValidity()));
        if (incomplete !== -1) {
            event.preventDefault();
            show(incomplete + 1);
            nativeValid(panels[incomplete]);
            return;
        }
        submitting = true;
        dirty = false;
    });

    // Une photo ajoutée pour la bière (étape 3) sert aussi à l'avis (étape 4), sans qu'on la reprenne : tant que le membre n'a pas choisi
    // lui-même la photo de l'avis, elle suit celle de la bière (changée ou retirée). Une photo de scan est déjà posée dans les deux champs.
    const beerPhoto = document.getElementById('id_beer-image');
    const tastingPhoto = document.getElementById('id_drink-photo');
    if (beerPhoto && tastingPhoto && window.ImageFields) {
        form.addEventListener('imagefield:set', event => {
            if (event.target !== beerPhoto || beerPhoto.dataset.fromScan === '1') return;
            window.ImageFields.preset(tastingPhoto, new File([event.detail.file], 'tasting.jpg', { type: 'image/jpeg' }));
        });
        form.addEventListener('imagefield:clear', event => {
            if (event.target !== beerPhoto || tastingPhoto.dataset.fromScan !== '1') return;
            const clear = tastingPhoto.closest('[data-image-field]').querySelector('[data-image-clear]');
            if (clear) clear.click();
        });
    }

    form.addEventListener('input', () => { dirty = true; });
    form.addEventListener('change', () => { dirty = true; });
    document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'hidden' && !submitting) saveSoft(current); });
    window.addEventListener('pagehide', () => { if (!submitting) saveSoft(current); });

    // Le bouton retour du téléphone remonte d'une étape au lieu de quitter la page
    window.addEventListener('popstate', event => {
        const step = event.state && event.state.step ? event.state.step : 1;
        show(step, { push: false });
    });

    const start = Math.min(Math.max(parseInt(form.dataset.startStep, 10) || 1, 1), total);
    history.replaceState({ step: start }, '', '#step-' + start);
    show(start, { push: false });
});
