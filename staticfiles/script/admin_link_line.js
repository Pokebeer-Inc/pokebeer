document.addEventListener("DOMContentLoaded", () => {
    const rows = document.querySelectorAll(
        "#result_list tbody tr"
    );

    rows.forEach((row) => {
        const link = row.querySelector(
            'a[href*="/change/"]'
        );

        if (!link) {
            return;
        }

        row.style.cursor = "pointer";

        row.addEventListener("click", (event) => {
            // Ne pas interférer avec les liens ou éléments interactifs
            if (
                event.target.closest("a") ||
                event.target.closest("button") ||
                event.target.closest("select") ||
                event.target.closest("input") ||
                event.target.closest("textarea")
            ) {
                return;
            }

            window.location.href = link.href;
        });
    });
});