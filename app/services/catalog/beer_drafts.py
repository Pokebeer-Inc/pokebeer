"""Ajout d'une bière en plusieurs étapes : étapes, brouillon enregistré en base et validation étape par étape.

Les formulaires de la page (BeerForm, DrinkForm) restent la seule source de règles : une étape est valide quand les champs qui
lui appartiennent le sont dans ces formulaires, y compris la détection des doublons de la première étape. Rien n'est donc
dupliqué, et ce qui est obligatoire aujourd'hui l'est exactement de la même façon.
"""
from datetime import timedelta

from django.utils import timezone

from ...forms import BeerForm, DrinkForm, MenuEntryForm
from ...models import BeerDraft
from ...validators import MAX_TEXT_LENGTH

DRAFT_MAX_AGE = timedelta(days=30)

# (clé, titre, champs de la bière, champs de la dégustation) : l'ordre est celui de la page
STEPS = (
    ('biere', "La bière", ('name', 'brewery_name', 'brewery_postal_code', 'brewery_city'), ()),
    ('caracteristiques', "Ses caractéristiques", ('degree', 'style', 'bitterness'), ()),
    ('description', "Description et photo", ('description', 'image'), ()),
    ('avis', "Votre avis", (), ('note', 'date', 'comment', 'photo')),
    ('contexte', "Le contexte", (), ('venue_type', 'company', 'serving_format', 'price')),
    ('recap', "Vérification", (), ()),
)
LAST_STEP = len(STEPS)

# Ajout depuis la carte d'un bar (mode « menu ») : les mêmes trois premières étapes, puis le prix et le format à la carte à la place de l'avis
# et du contexte (le gérant n'a pas goûté la bière pour la servir : aucune note n'est demandée).
MENU = 'menu'
MENU_STEPS = (*STEPS[:3], ('carte', "À la carte", (), ('price', 'serving_format')), ('recap', "Vérification", (), ()))
MODES = {'': STEPS, MENU: MENU_STEPS}
# Second formulaire de chaque mode : (préfixe des champs, classe)
SECOND_FORMS = {'': ('drink', DrinkForm), MENU: ('menu', MenuEntryForm)}


def steps_for(mode=''):
    return MODES[mode]


def last_step(mode=''):
    return len(MODES[mode])

# Champs textuels conservés dans le brouillon, avec leur taille maximale (au-delà on tronque : la vraie validation a lieu à l'envoi).
# Les fichiers, les jetons de confirmation de doublon et tout autre champ sont ignorés.
DRAFT_FIELDS = {
    'beer-name': 150, 'beer-brewery_name': 150, 'beer-brewery_postal_code': 5, 'beer-brewery_city': 100,
    'beer-degree': 10, 'beer-style': 200, 'beer-bitterness': 6, 'beer-description': MAX_TEXT_LENGTH, 'beer-ean': 20,
    'drink-note': 3, 'drink-date': 10, 'drink-comment': MAX_TEXT_LENGTH,
    'drink-venue_type': 12, 'drink-company': 10, 'drink-serving_format': 10, 'drink-price': 10,
    'menu-price': 10, 'menu-serving_format': 10,
}
MAX_NOTEBOOKS = 50


def sanitize(posted):
    """Champs autorisés d'un envoi, en texte tronqué ; `posted` est un QueryDict (ou un dict)."""
    clean = {}
    for key, limit in DRAFT_FIELDS.items():
        value = posted.get(key)
        if isinstance(value, str):
            clean[key] = value.strip()[:limit]
    return clean


def sanitize_notebooks(posted):
    getter = posted.getlist if hasattr(posted, 'getlist') else lambda key: posted.get(key, [])
    return [slug[:60] for slug in getter('notebooks') if isinstance(slug, str)][:MAX_NOTEBOOKS]


def step_of_field(prefix, name, mode=''):
    """Numéro (à partir de 1) de l'étape qui porte ce champ ; None s'il n'appartient à aucune."""
    for number, (_, _, beer_fields, other_fields) in enumerate(MODES[mode], start=1):
        if name in (beer_fields if prefix == 'beer' else other_fields):
            return number
    return None


def purge_stale():
    """Efface les brouillons abandonnés depuis plus de 30 jours (appelé à l'enregistrement d'un brouillon : pas de tâche planifiée)."""
    BeerDraft.objects.filter(updated_at__lt=timezone.now() - DRAFT_MAX_AGE).delete()


def get_draft(user):
    return BeerDraft.objects.filter(user=user).first()


def save_lenient(user, posted, step, mode=''):
    """Enregistre ce que contient l'envoi sans rien valider (quitter la page, retour en arrière) : on garde au moins ces données."""
    purge_stale()
    draft, _ = BeerDraft.objects.get_or_create(user=user)
    draft.data = {**draft.data, **sanitize(posted)}
    if 'notebooks_present' in posted:
        draft.data['notebooks'] = sanitize_notebooks(posted)
    draft.current_step = min(max(step, 1), last_step(mode))
    draft.save()
    return draft


def _second_form(mode, data, user):
    prefix, form_class = SECOND_FORMS[mode]
    return form_class(data, prefix=prefix, **({'user': user} if form_class is DrinkForm else {}))


def validate_step(user, step, posted, draft=None, mode=''):
    """Valide une étape avec les données du brouillon et de l'envoi. Retourne {'errors': [messages], 'fields': [id de champ]} (vides si valide)."""
    merged = {**(draft.data if draft else {}), **sanitize(posted)}
    data = dict(merged)
    for token in ('beer-confirm_brewery', 'beer-confirm_beer'):  # confirmations de doublon : seulement celles de l'envoi
        if posted.get(token):
            data[token] = posted.get(token)
    beer_form = BeerForm(data, prefix='beer', user=user)
    other_form = _second_form(mode, data, user)
    beer_form.is_valid()
    other_form.is_valid()

    _, _, beer_fields, other_fields = MODES[mode][step - 1]
    messages, fields = [], []
    for form, names in ((beer_form, beer_fields), (other_form, other_fields)):
        for name in names:
            for message in form.errors.get(name, []):
                label = str(form.fields[name].label or name).replace(' (Optionnel)', '')
                messages.append(f"{label} : {message}")
                fields.append(form[name].id_for_label)
    if step == 1:  # doublons : erreurs du formulaire qui ne portent sur aucun champ précis
        messages.extend(str(message) for message in beer_form.non_field_errors())
    return {'errors': messages, 'fields': fields}


def first_step_with_errors(beer_form, other_form, mode=''):
    """Étape à rouvrir après un envoi final refusé : la première qui porte une erreur (la dernière si l'erreur ne se rattache à aucune)."""
    steps = set()
    for prefix, form in (('beer', beer_form), (SECOND_FORMS[mode][0], other_form)):
        for name in form.errors:
            if name == '__all__':
                if prefix == 'beer':
                    steps.add(1)
                continue
            number = step_of_field(prefix, name, mode)
            if number:
                steps.add(number)
    if steps:
        return min(steps)
    return last_step(mode) if (beer_form.errors or other_form.errors) else 1
