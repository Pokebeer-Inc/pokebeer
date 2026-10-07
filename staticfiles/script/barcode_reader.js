// Lecture de code-barres sur le flux de la caméra, par deux stratégies interchangeables : l'API native du navigateur quand elle
// existe (rapide, robuste), sinon notre décodeur EAN. Les deux exposent read(video) -> code EAN valide ou null.
(function (root) {
    'use strict';

    const FORMATS = ['ean_13', 'ean_8', 'upc_a'];
    const SCAN_WIDTH = 640;       // largeur de l'image analysée par le décodeur maison
    const CONFIRMATIONS = 2;      // le même code doit être lu sur deux images de suite avant d'être cru

    class NativeBarcodeReader {
        constructor(detector) {
            this.detector = detector;
        }

        async read(video) {
            const found = await this.detector.detect(video);
            const match = found.find(item => EanDecoder.isValid(item.rawValue));
            return match ? match.rawValue : null;
        }
    }

    class ScanlineBarcodeReader {
        constructor() {
            this.canvas = document.createElement('canvas');
            this.context = this.canvas.getContext('2d', { willReadFrequently: true });
        }

        async read(video) {
            const { videoWidth: width, videoHeight: height } = video;
            if (!width || !height) return null;
            this.canvas.width = Math.min(SCAN_WIDTH, width);
            this.canvas.height = Math.round(height * this.canvas.width / width);
            this.context.drawImage(video, 0, 0, this.canvas.width, this.canvas.height);
            const pixels = this.context.getImageData(0, 0, this.canvas.width, this.canvas.height).data;
            return EanDecoder.decodeImage(FrameMetrics.toGray(pixels, this.canvas.width, this.canvas.height), this.canvas.width, this.canvas.height);
        }
    }

    /** Lecteur le mieux adapté à cet appareil. */
    async function createReader() {
        if ('BarcodeDetector' in window) {
            try {
                const supported = await window.BarcodeDetector.getSupportedFormats();
                const formats = FORMATS.filter(format => supported.includes(format));
                if (formats.length) return new NativeBarcodeReader(new window.BarcodeDetector({ formats }));
            } catch (error) { /* API présente mais inutilisable : on se rabat sur le décodeur maison */ }
        }
        return new ScanlineBarcodeReader();
    }

    /** Ne laisse passer un code qu'après plusieurs lectures identiques consécutives : une lecture erronée isolée est ignorée. */
    class Confirmer {
        constructor(required = CONFIRMATIONS) {
            this.required = required;
            this.reset();
        }

        reset() {
            this.code = null;
            this.count = 0;
        }

        push(code) {
            if (!code) {
                this.reset();
                return null;
            }
            this.count = code === this.code ? this.count + 1 : 1;
            this.code = code;
            return this.count >= this.required ? code : null;
        }
    }

    root.BarcodeReader = { createReader, NativeBarcodeReader, ScanlineBarcodeReader, Confirmer };
})(window);
