function switchTab(clickedBtn, panelId) {
    const btnContainer = clickedBtn.parentElement;
    const buttons = Array.from(btnContainer.querySelectorAll('.tab-btn'));
    
    // Détecter l'index actuel et le nouveau pour savoir si on va à gauche ou à droite
    const currentIndex = buttons.findIndex(btn => btn.classList.contains('bg-white'));
    const newIndex = buttons.indexOf(clickedBtn);
    
    // Si on clique sur l'onglet déjà actif, on ne fait rien
    if (currentIndex === newIndex) return;
    
    // Si le nouvel index est plus grand, on glisse depuis la droite, sinon depuis la gauche
    const directionClass = newIndex > currentIndex ? 'slide-in-right' : 'slide-in-left';

    // Mise à jour visuelle des boutons
    buttons.forEach(btn => {
        btn.classList.remove('bg-white', 'text-gray-900', 'shadow-sm');
        btn.classList.add('text-gray-500', 'hover:text-gray-700', 'hover:bg-base-300');
    });
    clickedBtn.classList.remove('text-gray-500', 'hover:text-gray-700', 'hover:bg-base-300');
    clickedBtn.classList.add('bg-white', 'text-gray-900', 'shadow-sm');

    // Mise à jour des panneaux
    const allPanels = document.querySelectorAll('.tab-panel');
    allPanels.forEach(panel => {
        panel.classList.remove('block', 'slide-in-right', 'slide-in-left');
        panel.classList.add('hidden');
    });

    // Afficher le nouveau panneau avec son animation
    const targetPanel = document.getElementById(panelId);
    if (targetPanel) {
        targetPanel.classList.remove('hidden');
        // Force un "reflow" du navigateur pour s'assurer que l'animation se joue à chaque clic
        void targetPanel.offsetWidth; 
        targetPanel.classList.add('block', directionClass);
    }
}

// Logique de détection du balayage (Swipe) globale
document.addEventListener('DOMContentLoaded', () => {
    const tabBtns = document.querySelectorAll('.tab-btn');
    
    // Le script s'active intelligemment uniquement sur les pages ayant exactement 2 onglets
    if (tabBtns.length !== 2) return;

    let startX = 0, startY = 0;
    let isDragging = false;

    function handleStart(e) {
        // Ignorer le swipe si on interagit avec des éléments spécifiques (sliders, map, etc.)
        if (e.target.closest('input[type="range"], .carousel, #map, .leaflet-container')) return;
        
        startX = e.type.includes('mouse') ? e.pageX : e.touches[0].clientX;
        startY = e.type.includes('mouse') ? e.pageY : e.touches[0].clientY;
        isDragging = true;
    }

    function handleEnd(e) {
        if (!isDragging) return;
        isDragging = false;

        let endX = e.type.includes('mouse') ? e.pageX : e.changedTouches[0].clientX;
        let endY = e.type.includes('mouse') ? e.pageY : e.changedTouches[0].clientY;

        let diffX = startX - endX;
        let diffY = startY - endY;

        // Seuil strict : le mouvement horizontal doit être d'au moins 60px et supérieur au vertical
        if (Math.abs(diffX) > 60 && Math.abs(diffX) > Math.abs(diffY) * 1.5) {
            
            // On vérifie quel onglet est actif
            const isFirstTabActive = tabBtns[0].classList.contains('bg-white');
            
            if (diffX > 0 && isFirstTabActive) {
                // Swipe vers la Gauche -> Ouvre le panel de Droite
                tabBtns[1].click();
            } else if (diffX < 0 && !isFirstTabActive) {
                // Swipe vers la Droite -> Ouvre le panel de Gauche
                tabBtns[0].click();
            }
        }
    }

    // Écouteurs globaux passifs
    document.addEventListener('touchstart', handleStart, {passive: true});
    document.addEventListener('touchend', handleEnd);
    document.addEventListener('mousedown', handleStart);
    document.addEventListener('mouseup', handleEnd);
});