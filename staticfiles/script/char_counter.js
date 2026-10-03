// Compteur de caractères pour tout <textarea data-char-counter maxlength="..."> (minlength optionnel)
document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("textarea[data-char-counter][maxlength]").forEach(function (field) {
        const min = parseInt(field.getAttribute("minlength") || "0", 10);
        const max = parseInt(field.getAttribute("maxlength"), 10);

        const counter = document.createElement("span");
        counter.className = "label-text-alt text-right mt-1";
        counter.setAttribute("aria-live", "polite");
        field.insertAdjacentElement("afterend", counter);

        function refresh() {
            const length = field.value.trim().length;
            counter.textContent = length < min
                ? `${length} / ${max} (minimum ${min} caractères)`
                : `${length} / ${max}`;
            counter.classList.toggle("text-error", length < min || length >= max);
            counter.classList.toggle("text-gray-400", length >= min && length < max);
        }

        field.addEventListener("input", refresh);
        refresh();
    });
});
