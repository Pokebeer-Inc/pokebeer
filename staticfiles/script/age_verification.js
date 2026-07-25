document.addEventListener("DOMContentLoaded", async function() {
    const ageModal = document.getElementById('modal_age_verification');
    const ageForm = document.getElementById('age-form');
    const ageError = document.getElementById('age-error');
    const ageCheckboxText = document.getElementById('age-checkbox-text');
    
    // S'il n'y a pas de modale sur la page, on arrête l'exécution du script
    if (!ageModal || !ageForm) return;

    // 1. Dictionnaire des âges légaux par code pays (ISO 2)
    const legalAges = {
        'US': 21, // États-Unis
        'JP': 20, // Japon
        'IS': 20, // Islande
        'CA': 19, // Canada (majorité des provinces)
        'KR': 19, // Corée du Sud
        'FR': 18, // France
        'GB': 18, // Royaume-Uni
        'BE': 16, // Belgique (Bière/Vin)
        'DE': 16, // Allemagne (Bière/Vin)
        'CH': 16  // Suisse (Bière/Vin)
        // Tous les pays non listés tomberont sur l'âge par défaut (18)
    };
    
    let requiredAge = 18; // Âge par défaut strict et standard international

    // 2. Si non vérifié, on affiche la modale et on cherche le pays
    if (!localStorage.getItem('age_verified')) {
        ageModal.addEventListener('cancel', (e) => e.preventDefault());
        ageModal.showModal();
        
        try {
            // Appel à une API gratuite pour récupérer le code pays depuis l'IP
            const response = await fetch('https://ipapi.co/json/');
            const data = await response.json();
            
            if (data.country_code) {
                // On cherche l'âge dans notre dictionnaire, sinon on garde 18
                requiredAge = legalAges[data.country_code] || 18;
            }
        } catch (error) {
            console.warn("Impossible de détecter le pays. Utilisation de l'âge par défaut (18).");
        }
        
        // Mise à jour dynamique des textes de la modale
        ageCheckboxText.innerText = `Je certifie avoir plus de ${requiredAge} ans et j'accepte les conditions d'utilisation.`;
        ageError.innerText = `Vous devez avoir au moins ${requiredAge} ans pour accéder à l'application.`;
    }
    
    // 3. Traitement du formulaire
    ageForm.addEventListener('submit', function(e) {
        e.preventDefault();
        const birthdate = new Date(document.getElementById('birthdate').value);
        const today = new Date();
        
        // Calcul de l'âge précis
        let age = today.getFullYear() - birthdate.getFullYear();
        const monthDiff = today.getMonth() - birthdate.getMonth();
        if (monthDiff < 0 || (monthDiff === 0 && today.getDate() < birthdate.getDate())) {
            age--;
        }
        
        if (age >= requiredAge) {
            // Succès
            localStorage.setItem('age_verified', 'true');
            ageError.classList.add('hidden');
            ageModal.close();
        } else {
            // Échec
            ageError.classList.remove('hidden');
        }
    });
});