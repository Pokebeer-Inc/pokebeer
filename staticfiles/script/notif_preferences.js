document.addEventListener('DOMContentLoaded', function() {
    const globalToggle = document.querySelector('input[name="notif_global"]');
    const categoriesDiv = document.getElementById('notif-categories');
    
    if(globalToggle && categoriesDiv) {
        globalToggle.addEventListener('change', function() {
            if(this.checked) {
                categoriesDiv.classList.remove('opacity-50', 'pointer-events-none');
            } else {
                categoriesDiv.classList.add('opacity-50', 'pointer-events-none');
            }
        });
    }
});