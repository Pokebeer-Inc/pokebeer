document.addEventListener("DOMContentLoaded", () => {
    const mapElement = document.getElementById("bar-moderation-map");

    if (!mapElement) {
        return;
    }

    const bars = window.BARS || [];

    const map = L.map("bar-moderation-map");

    L.tileLayer(
        "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
        {
            attribution: "&copy; OpenStreetMap contributors",
            maxZoom: 19,
        }
    ).addTo(map);

    const bounds = [];
    const markers = new Map();

    bars.forEach((bar) => {
        const position = [
            bar.latitude,
            bar.longitude,
        ];

        bounds.push(position);

        const marker = L.circleMarker(
            position,
            {
                radius: 8,

                color: bar.is_verified
                    ? "#15803d"
                    : "#ea580c",

                fillColor: bar.is_verified
                    ? "#22c55e"
                    : "#f97316",

                fillOpacity: 0.9,
                weight: 2,
            }
        ).addTo(map);

        marker.bindPopup(
            createBarPopup(bar),
            {
                maxWidth: 400,
                minWidth: 320,
            }
        );

        markers.set(bar.id, marker);
    });

    if (bounds.length > 0) {
        map.fitBounds(
            bounds,
            {
                padding: [30, 30],
            }
        );
    } else {
        map.setView(
            [50.8503, 4.3517],
            11
        );
    }


    function createBarPopup(bar) {
        return `
            <div class="bar-popup">

                <div class="bar-popup-header">

                    <strong>
                        🍺 ${escapeHtml(bar.name)}
                    </strong>

                    ${
                        bar.is_verified
                            ? `
                                <span class="bar-status verified">
                                    ✓ Vérifié
                                </span>
                            `
                            : `
                                <span class="bar-status pending">
                                    À vérifier
                                </span>
                            `
                    }

                </div>


                <div class="bar-popup-field">
                    <label>
                        Nom
                    </label>

                    <input
                        type="text"
                        id="bar-name-${bar.id}"
                        value="${escapeHtml(bar.name)}"
                    >
                </div>


                <div class="bar-popup-field">
                    <label>
                        Adresse
                    </label>

                    <input
                        type="text"
                        id="bar-address-${bar.id}"
                        value="${escapeHtml(bar.address)}"
                    >
                </div>


                <div class="bar-popup-field">
                    <label>
                        Téléphone
                    </label>

                    <input
                        type="text"
                        id="bar-phone-${bar.id}"
                        value="${escapeHtml(bar.phone)}"
                    >
                </div>


                <div class="bar-popup-field">
                    <label>
                        Email
                    </label>

                    <input
                        type="email"
                        id="bar-email-${bar.id}"
                        value="${escapeHtml(bar.email)}"
                    >
                </div>


                <div class="bar-popup-field">
                    <label>
                        SIRET
                    </label>

                    <input
                        type="text"
                        id="bar-siret-${bar.id}"
                        value="${escapeHtml(bar.siret)}"
                    >
                </div>


                <div class="bar-popup-field">
                    <label>
                        Site web
                    </label>

                    <input
                        type="url"
                        id="bar-website-${bar.id}"
                        value="${escapeHtml(bar.website)}"
                    >
                </div>


                <div class="bar-popup-field">
                    <label>
                        Description
                    </label>

                    <textarea
                        id="bar-description-${bar.id}"
                        rows="3"
                    >${escapeHtml(bar.description)}</textarea>
                </div>


                <div class="bar-popup-actions">

                    <button
                        type="button"
                        class="bar-save-button"
                        onclick="saveBar(${bar.id})"
                    >
                        Enregistrer
                    </button>

                    ${
                        !bar.is_verified
                            ? `
                                <button
                                    type="button"
                                    class="bar-verify-button"
                                    onclick="verifyBar(${bar.id})"
                                >
                                    ✓ Valider
                                </button>
                            `
                            : ""
                    }

                </div>

            </div>
        `;
    }


    window.saveBar = async function (id) {
        const formData = new FormData();

        formData.append(
            "name",
            document.getElementById(
                `bar-name-${id}`
            ).value
        );

        formData.append(
            "address",
            document.getElementById(
                `bar-address-${id}`
            ).value
        );

        formData.append(
            "phone",
            document.getElementById(
                `bar-phone-${id}`
            ).value
        );

        formData.append(
            "email",
            document.getElementById(
                `bar-email-${id}`
            ).value
        );

        formData.append(
            "siret",
            document.getElementById(
                `bar-siret-${id}`
            ).value
        );

        formData.append(
            "website",
            document.getElementById(
                `bar-website-${id}`
            ).value
        );

        formData.append(
            "description",
            document.getElementById(
                `bar-description-${id}`
            ).value
        );


        try {
            const response = await fetch(
                `/admin/api/bars/${id}/`,
                {
                    method: "POST",

                    headers: {
                        "X-CSRFToken": getCookie(
                            "csrftoken"
                        ),
                    },

                    body: formData,
                }
            );

            const result = await response.json();

            if (!response.ok || !result.success) {
                throw new Error(
                    result.message ||
                    "Erreur lors de l'enregistrement."
                );
            }


            const bar = bars.find(
                (item) => item.id === id
            );

            if (bar && result.bar) {
                Object.assign(
                    bar,
                    result.bar
                );
            }


            const marker = markers.get(id);

            if (marker && bar) {
                marker.setPopupContent(
                    createBarPopup(bar)
                );

                marker.openPopup();
            }


            showMessage(
                "Bar enregistré.",
                "success"
            );

        } catch (error) {

            console.error(error);

            showMessage(
                "Impossible d'enregistrer le bar.",
                "error"
            );
        }
    };


    window.verifyBar = async function (id) {
        const bar = bars.find(
            (item) => item.id === id
        );

        if (!bar) {
            return;
        }

        if (
            !window.confirm(
                `Valider le bar "${bar.name}" ?`
            )
        ) {
            return;
        }


        try {
            const response = await fetch(
                `/admin/api/bars/${id}/verify/`,
                {
                    method: "POST",

                    headers: {
                        "X-CSRFToken": getCookie(
                            "csrftoken"
                        ),
                    },
                }
            );

            const result = await response.json();

            if (!response.ok || !result.success) {
                throw new Error(
                    result.message ||
                    "Erreur lors de la validation."
                );
            }


            bar.is_verified = true;


            const marker = markers.get(id);

            if (marker) {

                marker.setStyle({
                    radius: 8,
                    color: "#15803d",
                    fillColor: "#22c55e",
                    fillOpacity: 0.9,
                    weight: 2,
                });

                marker.setPopupContent(
                    createBarPopup(bar)
                );

                marker.openPopup();
            }


            showMessage(
                "Bar validé.",
                "success"
            );

        } catch (error) {

            console.error(error);

            showMessage(
                "Impossible de valider le bar.",
                "error"
            );
        }
    };


    function getCookie(name) {
        const cookies =
            document.cookie.split(";");

        for (const cookie of cookies) {
            const parts =
                cookie.trim().split("=");

            if (parts[0] === name) {
                return decodeURIComponent(
                    parts.slice(1).join("=")
                );
            }
        }

        return null;
    }


    function escapeHtml(value) {
        if (
            value === null ||
            value === undefined
        ) {
            return "";
        }

        return String(value)
            .replaceAll("&", "&amp;")
            .replaceAll("<", "&lt;")
            .replaceAll(">", "&gt;")
            .replaceAll('"', "&quot;")
            .replaceAll("'", "&#039;");
    }


    function showMessage(
        message,
        type
    ) {
        const existing =
            document.getElementById(
                "bar-moderation-message"
            );

        if (existing) {
            existing.remove();
        }

        const messageElement =
            document.createElement("div");

        messageElement.id =
            "bar-moderation-message";

        messageElement.textContent =
            message;

        messageElement.style.position =
            "fixed";

        messageElement.style.top =
            "20px";

        messageElement.style.right =
            "20px";

        messageElement.style.zIndex =
            "99999";

        messageElement.style.padding =
            "12px 18px";

        messageElement.style.borderRadius =
            "8px";

        messageElement.style.fontWeight =
            "600";

        messageElement.style.background =
            type === "error"
                ? "#fee2e2"
                : "#dcfce7";

        messageElement.style.color =
            type === "error"
                ? "#991b1b"
                : "#166534";

        document.body.appendChild(
            messageElement
        );

        setTimeout(() => {
            messageElement.remove();
        }, 3000);
    }
});