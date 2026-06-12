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