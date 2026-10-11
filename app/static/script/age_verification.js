// Âge minimal fixe : 18 ans, quel que soit le pays (aucun service tiers n'est interrogé, l'adresse IP du visiteur n'est transmise à personne).
document.addEventListener("DOMContentLoaded", function() {
    const ageModal = document.getElementById('modal_age_verification');
    const ageForm = document.getElementById('age-form');

    // S'il n'y a pas de modale sur la page, on arrête l'exécution du script
    if (!ageModal || !ageForm) return;

    let verified = false;
    try { verified = Boolean(localStorage.getItem('age_verified')); } catch (error) { /* stockage indisponible : la modale s'affiche */ }
    if (!verified) {
        ageModal.addEventListener('cancel', (e) => e.preventDefault());
        ageModal.showModal();
    }

    ageForm.addEventListener('submit', function(e) {
        e.preventDefault();
        try { localStorage.setItem('age_verified', 'true'); } catch (error) { /* ignoré */ }
        ageModal.close();
    });
});
