document.addEventListener("DOMContentLoaded", async function() {
    const ageModal = document.getElementById('modal_age_verification');
    const ageForm = document.getElementById('age-form');
    const ageCheckboxText = document.getElementById('age-checkbox-text');
    
    // S'il n'y a pas de modale sur la page, on arrête l'exécution du script
    if (!ageModal || !ageForm) return;

    // Dictionnaire des âges légaux par code pays (ISO 2)
    const legalAges = {
        'US': 21, 'JP': 20, 'IS': 20, 'CA': 19, 'KR': 19,
        'FR': 18, 'GB': 18, 'BE': 16, 'DE': 16, 'CH': 16
    };
    
    let requiredAge = 18; // Âge par défaut strict et standard international

    // Si non vérifié, on affiche la modale et on cherche le pays
    if (!localStorage.getItem('age_verified')) {
        ageModal.addEventListener('cancel', (e) => e.preventDefault());
        ageModal.showModal();
        
        try {
            // Appel à une API pour récupérer le code pays depuis l'IP
            const response = await fetch('https://ipapi.co/json/');
            const data = await response.json();
            
            if (data.country_code) {
                requiredAge = legalAges[data.country_code] || 18;
            }
        } catch (error) {
            console.warn("Impossible de détecter le pays. Utilisation de l'âge par défaut (18).");
        }
        
        // Mise à jour dynamique du texte
        if (ageCheckboxText) {
            ageCheckboxText.innerText = `Je certifie avoir au moins ${requiredAge} ans, l'âge légal pour consommer de l'alcool dans mon pays.`;
        }
    }
    
    // Traitement de la confirmation
    ageForm.addEventListener('submit', function(e) {
        e.preventDefault();
        localStorage.setItem('age_verified', 'true');
        ageModal.close();
    });
});