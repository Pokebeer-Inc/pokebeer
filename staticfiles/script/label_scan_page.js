// Page « Ajouter une bière » : relie le bouton de scan au scanner en direct (code-barres ou étiquette), avec la photo en secours
// (caméra refusée, indisponible, ou navigateur sans accès à la caméra).
document.addEventListener('DOMContentLoaded', function () {
    const button = document.getElementById('scan-label-btn');
    const overlay = document.getElementById('label-scanner');
    const fileInput = document.getElementById('camera-input');
    const pickLink = document.getElementById('scan-pick-photo');
    const status = document.getElementById('scan-status');
    const csrf = document.querySelector('[name=csrfmiddlewaretoken]');
    if (!button || !overlay || !fileInput || !status || !csrf) return;

    const client = new LabelScan.Client(button.dataset.url, csrf.value, button.dataset.eanUrl);

    const say = (text, isError) => {
        status.textContent = text;
        status.classList.toggle('hidden', !text);
        status.classList.toggle('text-error', Boolean(isError));
        status.classList.toggle('text-primary', !isError);
    };

    // Message avec un lien vers une bière du catalogue : le texte et l'adresse sont construits ici, jamais insérés comme HTML
    const sayWithLink = (text, slug, linkText) => {
        say(text + ' ', false);
        if (!/^[a-z0-9-]+$/.test(slug)) return;
        const link = document.createElement('a');
        link.href = '/beer/' + slug + '/';
        link.className = 'underline';
        link.textContent = linkText;
        status.appendChild(link);
    };

    const CLOSING_MESSAGES = {
        found: 'Bière reconnue : vérifiez les informations ci-dessous.',
        timeout: "La caméra s'est refermée. Touchez le bouton pour réessayer.",
        unavailable: "Caméra indisponible : choisissez une photo à la place.",
    };

    const scanner = new LabelScanner.LiveScanner({
        view: new LabelScanner.ScannerView(overlay),
        client,
        onFinish: ({ reason, data, blob, ean, existing, error }) => {
            button.disabled = false;
            if (reason === 'found') LabelScan.fillForm(data, blob, ean);
            if (reason === 'catalog') {
                sayWithLink('Cette bière est déjà au catalogue :', existing.slug, 'aller la noter');
                button.focus();
                return;
            }
            const denied = error && error.name === 'NotAllowedError';
            say(denied ? "Accès à la caméra refusé : autorisez-le dans les réglages, ou choisissez une photo." : (CLOSING_MESSAGES[reason] || ''), reason === 'unavailable');
            if (reason !== 'closed') button.focus();
        },
    });

    button.addEventListener('click', () => {
        say('');
        if (!LabelScanner.CameraSession.supported()) {
            fileInput.click();
            return;
        }
        button.disabled = true;
        scanner.open();
    });

    if (pickLink) pickLink.addEventListener('click', () => { say(''); fileInput.click(); });

    // Secours : une photo choisie (ou prise avec l'appareil photo du téléphone) suit le même chemin d'analyse
    fileInput.addEventListener('change', async function () {
        const file = fileInput.files[0];
        if (!file) return;
        say("Analyse de l'étiquette en cours...", false);
        button.disabled = true;
        try {
            const bitmap = await createImageBitmap(file);
            const blob = await LabelScan.Client.toJpeg(bitmap, bitmap.width, bitmap.height);
            bitmap.close();
            const result = await client.analyze(blob);
            if (result.found) {
                LabelScan.fillForm(result.data, blob);
                say(CLOSING_MESSAGES.found, false);
            } else {
                say('Aucune étiquette de bière reconnue : essayez une photo plus nette, ou saisissez la bière.', true);
            }
        } catch (error) {
            say(error.message || "L'analyse de l'étiquette a échoué.", true);
        } finally {
            button.disabled = false;
            fileInput.value = '';
        }
    });
});
