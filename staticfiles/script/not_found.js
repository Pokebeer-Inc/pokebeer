document.addEventListener('DOMContentLoaded', () => {
    const backButton = document.getElementById('not-found-back');
    if (!backButton) return;

    backButton.addEventListener('click', () => {
        if (window.history.length > 1) {
            window.history.back();
        } else {
            window.location.href = backButton.dataset.homeUrl;
        }
    });
});
