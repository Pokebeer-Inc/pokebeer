document.addEventListener('DOMContentLoaded', function() {
    const allForms = document.querySelectorAll('form');
    
    allForms.forEach(form => {
        const toggles = form.querySelectorAll('input[type="checkbox"].toggle');
        
        if (toggles.length > 0) {
            const submitBtn = form.querySelector('button[type="submit"]');
            
            if (submitBtn) {
                // Dès qu'un switch change d'état, on simule un clic sur le bouton
                toggles.forEach(toggle => {
                    toggle.addEventListener('change', function() {
                        // On montre le loader global (qui vient de ton loader.js) pour que l'utilisateur patiente
                        const loader = document.getElementById('global-loader');
                        if (loader) {
                            loader.classList.remove('hidden');
                            loader.classList.add('flex');
                        }
                        
                        // On clique virtuellement sur le bouton caché
                        submitBtn.click();
                    });
                });
            }
        }
    });
});