// Réglage de la mesure d'audience Android : le choix est conservé par l'application native (pont AndroidBridge).
// Dans un navigateur, le pont n'existe pas : la section reste masquée.
document.addEventListener('DOMContentLoaded', function () {
    const bridge = window.AndroidBridge;
    const section = document.getElementById('privacy-settings');
    const toggle = document.getElementById('analytics-consent');
    if (!bridge || !bridge.getAnalyticsConsent || !section || !toggle) return;

    section.classList.remove('hidden');
    toggle.checked = bridge.getAnalyticsConsent() === 'granted';
    toggle.addEventListener('change', function () {
        bridge.setAnalyticsConsent(toggle.checked);
        // Le pont refuse la modification hors du site de Pokebeer : on réaffiche l'état réellement enregistré
        toggle.checked = bridge.getAnalyticsConsent() === 'granted';
    });
});
