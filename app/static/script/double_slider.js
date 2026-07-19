document.addEventListener('DOMContentLoaded', function() {
    const minSlider = document.getElementById('rating_min');
    const maxSlider = document.getElementById('rating_max');
    
    if (minSlider && maxSlider) {
        const track = document.getElementById('rating-track');
        const display = document.getElementById('rating-display');
        
        // On récupère le conteneur parent (la div qui englobe les sliders)
        const sliderContainer = minSlider.parentElement;

        function updateSliders() {
            let minVal = parseInt(minSlider.value);
            let maxVal = parseInt(maxSlider.value);

            // Mise à jour de la barre colorée entre les deux curseurs
            const percentMin = (minVal / 10) * 100;
            const percentMax = (maxVal / 10) * 100;
            
            track.style.left = percentMin + '%';
            track.style.width = (percentMax - percentMin) + '%';

            // Mise à jour du badge texte
            if (minVal === maxVal) {
                display.textContent = minVal + ' / 10'; // Valeur exacte
            } else {
                display.textContent = 'De ' + minVal + ' à ' + maxVal; // Fourchette
            }
        }

        minSlider.addEventListener('input', function() {
            // Empêche le curseur min de dépasser le max
            if (parseInt(minSlider.value) > parseInt(maxSlider.value)) {
                minSlider.value = maxSlider.value;
            }
            updateSliders();
        });

        maxSlider.addEventListener('input', function() {
            // Empêche le curseur max de descendre sous le min
            if (parseInt(maxSlider.value) < parseInt(minSlider.value)) {
                maxSlider.value = minSlider.value;
            }
            updateSliders();
        });

        // --- NOUVEAU : Gérer le clic direct sur la barre ---
        sliderContainer.addEventListener('click', function(e) {
            // Si on clique directement sur un bouton de curseur (input), on laisse le navigateur gérer
            if (e.target.tagName.toLowerCase() === 'input') return;

            // Calcul de la valeur cliquée en fonction de la position de la souris
            const rect = sliderContainer.getBoundingClientRect();
            const clickX = e.clientX - rect.left;
            const percent = clickX / rect.width;
            let clickedValue = Math.round(percent * 10);
            
            // Sécurité pour rester strictement entre 0 et 10
            clickedValue = Math.max(0, Math.min(10, clickedValue));

            let minVal = parseInt(minSlider.value);
            let maxVal = parseInt(maxSlider.value);

            // Déterminer quel curseur est le plus proche de la zone cliquée
            const distToMin = Math.abs(clickedValue - minVal);
            const distToMax = Math.abs(clickedValue - maxVal);

            if (distToMin < distToMax) {
                minSlider.value = clickedValue;
            } else if (distToMax < distToMin) {
                maxSlider.value = clickedValue;
            } else {
                // Si on clique exactement au milieu des deux, on déplace celui qui a le plus de sens
                if (clickedValue < minVal) {
                    minSlider.value = clickedValue;
                } else {
                    maxSlider.value = clickedValue;
                }
            }
            
            updateSliders();
        });

        // Initialisation au chargement de la page
        updateSliders();
    }
});