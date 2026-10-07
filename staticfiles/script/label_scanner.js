// Scanner en direct : la caméra s'ouvre, un cadre guide l'étiquette. Deux détections tournent en même temps sur le même flux :
// le code-barres EAN (le plus rapide et le plus fiable), lu dès qu'il apparaît ; sinon l'étiquette, analysée toute seule dès que
// l'image est nette, contrastée et immobile. Rien n'est enregistré : l'aperçu reste dans l'appareil ; seuls partent vers notre serveur
// un code-barres validé (5 recherches au plus) ou une image à analyser (3 au plus en automatique).
(function (root) {
    'use strict';

    const FRAME_MS = 200;            // une mesure toutes les 200 ms
    const SAMPLE_WIDTH = 160;        // largeur de l'image réduite sur laquelle on mesure
    const CROP = { w: 0.76, h: 0.52 }; // part de l'image (centrée) qui correspond au cadre affiché
    const MAX_AUTO_ATTEMPTS = 3;     // analyses automatiques par ouverture : l'IA est comptée au quota quotidien
    const MAX_BARCODE_LOOKUPS = 5;   // recherches par code-barres par ouverture (un code déjà refusé n'est jamais renvoyé)
    const COOLDOWN_MS = 2500;        // pause après une analyse sans résultat
    const SESSION_MS = 60000;        // la caméra se referme seule après une minute
    const CLOSE_DELAY_MS = 700;      // le temps de voir « reconnue » avant de refermer

    const MESSAGES = {
        searching: "Présentez le code-barres, ou placez l'étiquette dans le cadre",
        reading: 'Code-barres lu : recherche de la bière...',
        unknownBarcode: "Code-barres inconnu : placez l'étiquette dans le cadre",
        holding: 'Ne bougez plus...',
        analyzing: "Analyse de l'étiquette...",
        found: 'Bière reconnue',
        notfound: 'Rien reconnu : rapprochez-vous, évitez les reflets, ou touchez le bouton',
        error: 'Analyse impossible',
        exhausted: 'Rien reconnu : touchez le bouton pour réessayer, ou saisissez la bière',
    };

    /** Accès à la caméra arrière ; l'aperçu n'est jamais enregistré et le flux est coupé dès la fermeture. */
    class CameraSession {
        static supported() {
            return Boolean(window.isSecureContext && navigator.mediaDevices && navigator.mediaDevices.getUserMedia);
        }

        async start(video) {
            this.stream = await navigator.mediaDevices.getUserMedia({
                video: { facingMode: { ideal: 'environment' }, width: { ideal: 1280 }, height: { ideal: 720 } },
                audio: false,
            });
            video.srcObject = this.stream;
            await video.play();
        }

        stop(video) {
            if (this.stream) this.stream.getTracks().forEach(track => track.stop());
            this.stream = null;
            video.srcObject = null;
        }
    }

    /** Image réduite de la zone du cadre, en niveaux de gris, pour les mesures. */
    class FrameSampler {
        constructor(video) {
            this.video = video;
            this.canvas = document.createElement('canvas');
            this.context = this.canvas.getContext('2d', { willReadFrequently: true });
        }

        sample() {
            const { videoWidth: width, videoHeight: height } = this.video;
            if (!width || !height) return null;
            const sw = width * CROP.w, sh = height * CROP.h;
            this.canvas.width = SAMPLE_WIDTH;
            this.canvas.height = Math.max(3, Math.round(SAMPLE_WIDTH * sh / sw));
            this.context.drawImage(this.video, (width - sw) / 2, (height - sh) / 2, sw, sh, 0, 0, this.canvas.width, this.canvas.height);
            const pixels = this.context.getImageData(0, 0, this.canvas.width, this.canvas.height).data;
            return FrameMetrics.toGray(pixels, this.canvas.width, this.canvas.height);
        }
    }

    /** Affichage : état du cadre, message, progression. Ne décide de rien. */
    class ScannerView {
        constructor(rootElement) {
            this.root = rootElement;
            this.video = rootElement.querySelector('[data-scanner-video]');
            this.message = rootElement.querySelector('[data-scanner-message]');
            this.progress = rootElement.querySelector('[data-scanner-progress]');
            this.capture = rootElement.querySelector('[data-scanner-capture]');
            this.close = rootElement.querySelector('[data-scanner-close]');
        }

        show() {
            this.root.classList.add('is-open');
            this.root.setAttribute('aria-hidden', 'false');
            document.body.classList.add('overflow-hidden');
            this.close.focus();
        }

        hide() {
            this.root.classList.remove('is-open');
            this.root.setAttribute('aria-hidden', 'true');
            document.body.classList.remove('overflow-hidden');
        }

        setState(state, text) {
            this.root.dataset.state = state;
            this.message.textContent = text || MESSAGES[state] || '';
        }

        setProgress(ratio) {
            this.progress.style.width = Math.round(ratio * 100) + '%';
        }

        setBusy(busy) {
            this.capture.disabled = busy;
        }
    }

    /** Orchestre : ouvre la caméra, mesure les images, lance l'analyse au bon moment, referme. */
    class LiveScanner {
        /** `onFinish({ reason, data, blob, ean, existing })` : reason vaut found, catalog, closed, timeout, hidden ou unavailable. */
        constructor({ view, client, onFinish, readerFactory = BarcodeReader.createReader }) {
            this.view = view;
            this.client = client;
            this.readerFactory = readerFactory;
            this.confirmer = new BarcodeReader.Confirmer();
            this.onFinish = onFinish;
            this.camera = new CameraSession();
            this.sampler = new FrameSampler(view.video);
            this.tracker = new FrameMetrics.StabilityTracker();
            this.isOpen = false;
            view.close.addEventListener('click', () => this.close('closed'));
            view.capture.addEventListener('click', () => this.capture('manual'));
            document.addEventListener('keydown', event => { if (event.key === 'Escape' && this.isOpen) this.close('closed'); });
            document.addEventListener('visibilitychange', () => { if (document.hidden && this.isOpen) this.close('hidden'); });
            window.addEventListener('pagehide', () => { if (this.isOpen) this.close('hidden'); });
        }

        async open() {
            if (this.isOpen) return;
            this.isOpen = true;
            this.autoAttempts = 0;
            this.busy = false;
            this.done = false;
            this.previous = null;
            this.pauseUntil = 0;
            this.barcodeLookups = 0;
            this.rejectedCodes = new Set();
            this.reading = false;
            this.confirmer.reset();
            this.tracker.reset();
            this.view.setProgress(0);
            this.view.setBusy(false);
            this.view.setState('searching');
            this.view.show();
            try {
                await this.camera.start(this.view.video);
            } catch (error) {
                this.finish('unavailable', { error });
                return;
            }
            this.reader = await this.readerFactory();
            if (!this.isOpen) return; // refermé pendant la préparation du lecteur
            this.timer = setInterval(() => this.tick(), FRAME_MS);
            this.deadline = setTimeout(() => this.close('timeout'), SESSION_MS);
        }

        async tick() {
            if (!this.isOpen || this.done || this.busy || performance.now() < this.pauseUntil) return;
            await this.scanBarcode();
            if (!this.isOpen || this.done || this.busy || this.autoAttempts >= MAX_AUTO_ATTEMPTS) return;
            const gray = this.sampler.sample();
            if (!gray) return;
            const { width, height } = this.sampler.canvas;
            const measures = {
                sharpness: FrameMetrics.sharpness(gray, width, height),
                contrast: FrameMetrics.contrast(gray),
                motion: FrameMetrics.motion(this.previous, gray),
            };
            this.previous = gray;
            const { ready, progress } = this.tracker.update(measures, performance.now());
            this.view.setProgress(progress);
            this.view.setState(progress > 0 ? 'holding' : 'searching');
            if (ready) this.capture('auto');
        }

        /** Cherche un code-barres dans l'image courante ; un code confirmé lance sa recherche (le code-barres prime sur l'étiquette). */
        async scanBarcode() {
            if (this.reading || this.barcodeLookups >= MAX_BARCODE_LOOKUPS) return;
            this.reading = true;
            let code = null;
            try {
                code = this.confirmer.push(await this.reader.read(this.view.video));
            } catch (error) {
                this.confirmer.reset(); // lecture impossible sur cette image : la suivante réessaie
            } finally {
                this.reading = false;
            }
            if (code && this.isOpen && !this.done && !this.busy && !this.rejectedCodes.has(code)) await this.lookup(code);
        }

        async lookup(code) {
            this.busy = true;
            this.barcodeLookups++;
            this.view.setBusy(true);
            this.view.setState('reading');
            this.view.setProgress(1);
            try {
                const result = await this.client.lookupEan(code);
                if (!this.isOpen) return;
                if (result.source === 'catalog' || result.found) {
                    this.done = true;
                    this.view.setState('found', result.source === 'catalog' ? 'Bière déjà au catalogue' : undefined);
                    this.camera.stop(this.view.video);
                    setTimeout(() => this.finish(result.source === 'catalog' ? 'catalog' : 'found', { data: result.data, ean: result.ean, existing: result.existing }), CLOSE_DELAY_MS);
                    return;
                }
                this.rejectedCodes.add(code);
                this.afterMiss('unknownBarcode');
            } catch (error) {
                if (this.isOpen) this.afterMiss('error', error.message);
            } finally {
                this.busy = false;
                if (this.isOpen) this.view.setBusy(false);
            }
        }

        async capture(mode) {
            const { video } = this.view;
            if (!this.isOpen || this.done || this.busy || !video.videoWidth) return;
            this.busy = true;
            if (mode === 'auto') this.autoAttempts++;
            this.view.setBusy(true);
            this.view.setState('analyzing');
            this.view.setProgress(1);
            try {
                const blob = await root.LabelScan.Client.toJpeg(video, video.videoWidth, video.videoHeight);
                const result = await this.client.analyze(blob);
                if (!this.isOpen) return; // refermé pendant l'analyse : rien à remplir
                if (result.found) {
                    this.done = true; // plus aucune analyse ni mesure pendant la brève confirmation
                    this.view.setState('found');
                    this.camera.stop(video);
                    setTimeout(() => this.finish('found', { data: result.data, blob }), CLOSE_DELAY_MS);
                    return;
                }
                this.afterMiss(this.autoAttempts >= MAX_AUTO_ATTEMPTS ? 'exhausted' : 'notfound');
            } catch (error) {
                if (this.isOpen) this.afterMiss('error', error.message);
            } finally {
                this.busy = false;
                if (this.isOpen) this.view.setBusy(false);
            }
        }

        afterMiss(state, text) {
            this.view.setState(state, text);
            this.view.setProgress(0);
            this.tracker.reset();
            this.confirmer.reset();
            this.previous = null;
            this.pauseUntil = performance.now() + COOLDOWN_MS;
        }

        close(reason) {
            if (!this.isOpen) return;
            this.finish(reason);
        }

        finish(reason, details = {}) {
            this.isOpen = false;
            clearInterval(this.timer);
            clearTimeout(this.deadline);
            this.camera.stop(this.view.video);
            this.view.hide();
            this.onFinish({ reason, ...details });
        }
    }

    root.LabelScanner = { CameraSession, FrameSampler, ScannerView, LiveScanner, MESSAGES };
})(window);
