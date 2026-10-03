document.addEventListener('DOMContentLoaded', function () {
    const input = document.getElementById('avatar-input');
    if (!input) return;

    input.addEventListener('change', function () {
        const file = input.files[0];
        if (!file) return;

        // Confort uniquement : le serveur revérifie la taille, le format et le contenu
        if (file.size > Number(input.dataset.maxBytes)) {
            alert(input.dataset.tooLarge);
            input.value = '';
            return;
        }
        input.form.submit();
    });
});
