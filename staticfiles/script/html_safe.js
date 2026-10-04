// Contenu venu d'autres membres ou de services tiers : toujours échappé (ou affiché via textContent) avant d'entrer dans du HTML.
function escapeHtml(value) {
    const element = document.createElement('div');
    element.textContent = value;
    return element.innerHTML.replace(/"/g, '&quot;');
}

// Markdown (réponses de l'IA) converti en HTML puis nettoyé : aucun script ni gestionnaire d'événement ne survit.
function renderMarkdown(text) {
    return DOMPurify.sanitize(marked.parse(text));
}
