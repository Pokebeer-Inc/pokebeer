// Carte d'un bar : recherche d'une bière du catalogue puis ajout en un geste. Les résultats sont construits avec textContent (jamais en HTML) ;
// l'ajout est un vrai formulaire POST protégé par le jeton CSRF de la page.
document.addEventListener("DOMContentLoaded", function () {
    const root = document.querySelector("[data-menu-picker]");
    if (!root) return;
    const input = root.querySelector("[data-menu-search]");
    const list = root.querySelector("[data-menu-results]");
    const hint = root.querySelector("[data-menu-hint]");
    const csrf = root.querySelector("[name=csrfmiddlewaretoken]").value;
    let timer = null;
    let controller = null;

    function row(item) {
        const li = document.createElement("li");
        li.className = "mn-result";
        const label = document.createElement("div");
        label.className = "min-w-0";
        const name = document.createElement("span");
        name.className = "mn-beer";
        name.textContent = item.name;
        const detail = document.createElement("span");
        detail.className = "mn-brewery";
        detail.textContent = item.brewery + (item.style ? " · " + item.style : "");
        label.append(name, detail);
        li.appendChild(label);

        if (item.on_menu) {
            const served = document.createElement("span");
            served.className = "mn-served";
            served.textContent = "Déjà à la carte";
            li.appendChild(served);
            return li;
        }
        const form = document.createElement("form");
        form.method = "post";
        form.action = root.dataset.addUrl;
        [["csrfmiddlewaretoken", csrf], ["beer", item.slug]].forEach(function (pair) {
            const hidden = document.createElement("input");
            hidden.type = "hidden";
            hidden.name = pair[0];
            hidden.value = pair[1];
            form.appendChild(hidden);
        });
        const button = document.createElement("button");
        button.type = "submit";
        button.className = "pb-chip is-primary";
        button.textContent = "Ajouter";
        form.appendChild(button);
        li.appendChild(form);
        return li;
    }

    async function search() {
        const term = input.value.trim();
        if (controller) controller.abort();
        if (term.length < 2) {
            list.replaceChildren();
            hint.textContent = "Tapez au moins 2 lettres.";
            return;
        }
        controller = new AbortController();
        try {
            const response = await fetch(root.dataset.searchUrl + "?" + new URLSearchParams({ term: term }), { signal: controller.signal, credentials: "same-origin" });
            if (!response.ok) throw new Error(String(response.status));
            const items = await response.json();
            list.replaceChildren(...items.map(row));
            hint.textContent = items.length ? "" : "Aucune bière trouvée dans le catalogue.";
        } catch (error) {
            if (error.name !== "AbortError") hint.textContent = "Recherche impossible pour le moment. Réessayez.";
        }
    }

    input.addEventListener("input", function () {
        clearTimeout(timer);
        timer = setTimeout(search, 250);
    });
});
