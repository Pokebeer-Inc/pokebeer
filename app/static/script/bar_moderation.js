document.addEventListener("DOMContentLoaded", function () {

    const mapElement = document.getElementById(
        "bar-moderation-map"
    );

    if (!mapElement) {
        return;
    }


    /*
     * ============================================================
     * RÉCUPÉRATION DES BARS
     * ============================================================
     */

    const barsContainer = document.getElementById(
        "bars-data-container"
    );

    const bars = [];

    if (barsContainer) {

        barsContainer
            .querySelectorAll(".bar-data-item")
            .forEach(function (item) {

                bars.push({

                    id: item.dataset.id,

                    name: item.dataset.name,

                    description:
                        item.dataset.description,

                    address:
                        item.dataset.address,

                    phone:
                        item.dataset.phone,

                    email:
                        item.dataset.email,

                    website:
                        item.dataset.website,

                    instagram:
                        item.dataset.instagram,

                    facebook:
                        item.dataset.facebook,

                    siret:
                        item.dataset.siret,

                    latitude:
                        parseFloat(item.dataset.lat),

                    longitude:
                        parseFloat(item.dataset.lng),

                    isVerified:
                        item.dataset.verified === "true",

                    /*
                     * NOUVEAU :
                     * URL Django Admin générée par BarAdmin
                     */
                    verifyUrl:
                        item.dataset.verifyUrl

                });

            });

    }


    /*
     * ============================================================
     * INITIALISATION DE LA CARTE
     * ============================================================
     */

    const map = L.map(
        "bar-moderation-map",
        {
            zoomControl: false
        }
    ).setView(
        [50.8503, 4.3517],
        11
    );


    L.control.zoom({
        position: "topright"
    }).addTo(map);


    /*
     * Même configuration que ton map.js principal
     */

    L.tileLayer(
        "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
        {
            maxZoom: 19
        }
    ).addTo(map);


    /*
     * Permet à Leaflet de recalculer correctement
     * la taille lorsqu'Unfold affiche le composant.
     */

    new ResizeObserver(function () {
        map.invalidateSize();
    }).observe(mapElement);


    /*
     * ============================================================
     * MARKERS
     * ============================================================
     */

    const markers = {};

    const coordinates = [];


    bars.forEach(function (bar) {

        if (
            Number.isNaN(bar.latitude) ||
            Number.isNaN(bar.longitude)
        ) {
            return;
        }


        const position = [
            bar.latitude,
            bar.longitude
        ];

        coordinates.push(position);


        const marker = L.circleMarker(
            position,
            getMarkerStyle(bar)
        ).addTo(map);


        marker.bindPopup(
            createPopup(bar),
            {
                maxWidth: 380,
                minWidth: 320,
                className: "bar-moderation-popup"
            }
        );


        markers[bar.id] = marker;

    });


    /*
     * ============================================================
     * CENTRAGE DE LA CARTE
     * ============================================================
     */

    if (coordinates.length > 0) {

        map.fitBounds(
            coordinates,
            {
                padding: [50, 50]
            }
        );

    }


    /*
     * ============================================================
     * STYLE DES MARKERS
     * ============================================================
     */

    function getMarkerStyle(bar) {

        return {

            radius: 9,

            color: bar.isVerified
                ? "#15803d"
                : "#c2410c",

            fillColor: bar.isVerified
                ? "#22c55e"
                : "#f97316",

            fillOpacity: 0.95,

            weight: 2

        };

    }


    /*
     * ============================================================
     * POPUP
     * ============================================================
     */

    function createPopup(bar) {

        return `

            <div class="bar-moderation-popup-content">

                <div class="bar-popup-title">

                    <div class="bar-popup-icon">
                        🍺
                    </div>

                    <div class="bar-popup-title-text">

                        <h3>
                            ${escapeHtml(bar.name)}
                        </h3>

                        <span class="
                            bar-popup-status
                            ${bar.isVerified
                                ? "verified"
                                : "pending"}
                        ">

                            ${
                                bar.isVerified
                                    ? "✓ Bar vérifié"
                                    : "⚠ À vérifier"
                            }

                        </span>

                    </div>

                </div>


                ${
                    bar.description
                        ? `

                            <div class="bar-popup-description">

                                ${escapeHtml(
                                    bar.description
                                )}

                            </div>

                        `
                        : ""
                }


                <div class="bar-popup-info">

                    ${
                        bar.address
                            ? `

                                <div class="bar-popup-info-row">

                                    <span class="info-icon">
                                        📍
                                    </span>

                                    <span>
                                        ${escapeHtml(
                                            bar.address
                                        )}
                                    </span>

                                </div>

                            `
                            : ""
                    }


                    ${
                        bar.phone
                            ? `

                                <div class="bar-popup-info-row">

                                    <span class="info-icon">
                                        📞
                                    </span>

                                    <span>
                                        ${escapeHtml(
                                            bar.phone
                                        )}
                                    </span>

                                </div>

                            `
                            : ""
                    }


                    ${
                        bar.email
                            ? `

                                <div class="bar-popup-info-row">

                                    <span class="info-icon">
                                        ✉️
                                    </span>

                                    <span>
                                        ${escapeHtml(
                                            bar.email
                                        )}
                                    </span>

                                </div>

                            `
                            : ""
                    }


                    ${
                        bar.website
                            ? `

                                <div class="bar-popup-info-row">

                                    <span class="info-icon">
                                        🌐
                                    </span>

                                    <a
                                        href="${escapeHtml(
                                            bar.website
                                        )}"
                                        target="_blank"
                                        rel="noopener noreferrer"
                                    >
                                        Site web
                                    </a>

                                </div>

                            `
                            : ""
                    }


                    ${
                        bar.siret
                            ? `

                                <div class="bar-popup-info-row">

                                    <span class="info-icon">
                                        🏢
                                    </span>

                                    <span>

                                        SIRET :

                                        ${escapeHtml(
                                            bar.siret
                                        )}

                                    </span>

                                </div>

                            `
                            : ""
                    }

                </div>


                <div class="bar-popup-footer">

                    ${
                        !bar.isVerified
                            ? `

                                <button
                                    type="button"
                                    class="bar-verify-button"
                                    onclick="verifyBar('${bar.id}')"
                                >

                                    <span>✓</span>

                                    Valider ce bar

                                </button>

                            `
                            : `

                                <div class="bar-already-verified">

                                    ✓ Ce bar est déjà vérifié

                                </div>

                            `
                    }

                </div>

            </div>

        `;

    }


    /*
     * ============================================================
     * CSRF
     * ============================================================
     *
     * Le token est fourni par {% csrf_token %} dans le template.
     */

    function getCsrfToken() {

        const csrfInput = document.querySelector(
            "[name=csrfmiddlewaretoken]"
        );

        if (csrfInput) {
            return csrfInput.value;
        }

        return null;
    }


    /*
     * ============================================================
     * VALIDATION
     * ============================================================
     */

    window.verifyBar = function (id) {

        const bar = bars.find(
            function (bar) {
                return bar.id === id;
            }
        );


        if (!bar) {
            console.error(
                "Bar introuvable :",
                id
            );

            return;
        }


        /*
         * Vérification de l'URL fournie par Django
         */

        if (!bar.verifyUrl) {

            console.error(
                "URL de validation absente pour le bar :",
                bar
            );

            return;
        }


        /*
         * Récupération du token CSRF
         */

        const csrfToken = getCsrfToken();


        if (!csrfToken) {

            console.error(
                "Token CSRF introuvable."
            );

            alert(
                "Erreur de sécurité : token CSRF introuvable."
            );

            return;
        }


        /*
         * Désactivation du bouton pendant la requête
         */

        const button = document.querySelector(
            `.bar-verify-button[onclick="verifyBar('${id}')"]`
        );


        if (button) {

            button.disabled = true;

            button.innerHTML = `
                <span>⏳</span>
                Validation...
            `;

        }


        /*
         * POST vers l'endpoint Django Admin
         */

        fetch(
            bar.verifyUrl,
            {
                method: "POST",

                headers: {
                    "X-CSRFToken": csrfToken,
                    "X-Requested-With": "XMLHttpRequest",
                },

                credentials: "same-origin",
            }
        )

        .then(function (response) {

            if (!response.ok) {

                throw new Error(
                    `HTTP ${response.status}`
                );

            }

            return response.json();

        })

        .then(function (data) {

            if (!data.success) {

                throw new Error(
                    data.error ||
                    "Erreur lors de la validation."
                );

            }


            /*
             * ====================================================
             * MISE À JOUR LOCALE
             * ====================================================
             */

            bar.isVerified = true;


            /*
             * ====================================================
             * MISE À JOUR DU MARKER
             * ====================================================
             */

            const marker = markers[bar.id];


            if (marker) {

                marker.setStyle(
                    getMarkerStyle(bar)
                );


                /*
                 * Mise à jour de la popup
                 */

                marker.setPopupContent(
                    createPopup(bar)
                );


                /*
                 * On garde la popup ouverte
                 */

                marker.openPopup();

            }

        })

        .catch(function (error) {

            console.error(
                "Erreur lors de la validation :",
                error
            );


            /*
             * Réactivation du bouton
             */

            if (button) {

                button.disabled = false;

                button.innerHTML = `
                    <span>✓</span>
                    Valider ce bar
                `;

            }


            alert(
                "Impossible de valider le bar."
            );

        });

    };


    /*
     * ============================================================
     * SÉCURITÉ HTML
     * ============================================================
     */

    function escapeHtml(value) {

        if (
            value === null ||
            value === undefined
        ) {

            return "";

        }


        return String(value)

            .replaceAll(
                "&",
                "&amp;"
            )

            .replaceAll(
                "<",
                "&lt;"
            )

            .replaceAll(
                ">",
                "&gt;"
            )

            .replaceAll(
                '"',
                "&quot;"
            )

            .replaceAll(
                "'",
                "&#039;"
            );

    }

});