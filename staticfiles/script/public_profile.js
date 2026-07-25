document.addEventListener("DOMContentLoaded", function() {
    if (new URLSearchParams(window.location.search).has('reported')) {
        const modal = document.getElementById('modal_block_user');
        if (modal) {
            modal.showModal();
        }
    }
});