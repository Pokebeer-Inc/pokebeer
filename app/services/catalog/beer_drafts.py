"""Ajout d'une bière en plusieurs étapes : étapes, brouillon enregistré en base et validation étape par étape.

Les formulaires de la page (BeerForm, MenuEntryForm) restent la seule source de règles : une étape est valide quand les champs qui
lui appartiennent le sont dans ces formulaires, y compris la détection des doublons de la première étape. Rien n'est donc dupliqué.

Ajouter une bière n'est pas la déguster : le membre n'a besoin que du nom (la brasserie et le reste sont facultatifs, l'équipe complète),
et sa dégustation se fait ensuite sur la page de félicitations (voir tasting_views).
"""
from datetime import timedelta

from django.utils import timezone

from ...forms import BeerForm, MenuEntryForm
from ...models import BeerDraft
from ...validators import MAX_TEXT_LENGTH

DRAFT_MAX_AGE = timedelta(days=30)

# Un membre n'a pas d'étape de vérification : tout ce qu'il n'a pas rempli est facultatif, le lui lister serait du bruit. Le gérant de bar, qui
# engage sa carte, relit son ajout avant l'envoi.
RECAP = ('recap', "Vérification", (), ())

# (clé, titre, champs de la bière, champs du second formulaire) : l'ordre est celui de la page
STEPS = (
    ('biere', "La bière", ('name', 'degree', 'brewery_name'), ()),
    ('details', "Détails", ('style', 'bitterness', 'image'), ()),
)
LAST_STEP = len(STEPS)

# Ajout depuis la carte d'un bar (mode « menu ») : le gérant connaît le lieu de la brasserie et sa description officielle, puis donne le prix et le
# format à la carte (il n'a pas goûté la bière pour la servir : aucune note n'est demandée).
MENU = 'menu'
MENU_STEPS = (
    ('biere', "La bière", ('name', 'degree', 'brewery_name', 'brewery_postal_code', 'brewery_city'), ()),
    ('details', "Détails", ('style', 'bitterness', 'description', 'image'), ()),
    ('carte', "À la carte", (), ('price', 'serving_format')),
    RECAP,
)
MODES = {'': STEPS, MENU: MENU_STEPS}
# Second formulaire de chaque mode qui en a un : (préfixe des champs, classe)
SECOND_FORMS = {MENU: ('menu', MenuEntryForm)}


def steps_for(mode=''):
    return MODES[mode]


def last_step(mode=''):
    return len(MODES[mode])

# Champs textuels conservés dans le brouillon, avec leur taille maximale (au-delà on tronque : la vraie validation a lieu à l'envoi).
# Les fichiers, les jetons de confirmation de doublon et tout autre champ sont ignorés.
DRAFT_FIELDS = {
    'beer-name': 150, 'beer-brewery_name': 150, 'beer-brewery_slug': 80, 'beer-brewery_postal_code': 5, 'beer-brewery_city': 100,
    'beer-degree': 10, 'beer-style': 200, 'beer-bitterness': 6, 'beer-description': MAX_TEXT_LENGTH, 'beer-ean': 20,
    'menu-price': 10, 'menu-serving_format': 10,
}


def sanitize(posted):
    """Champs autorisés d'un envoi, en texte tronqué ; `posted` est un QueryDict (ou un dict)."""
    clean = {}
    for key, limit in DRAFT_FIELDS.items():
        value = posted.get(key)
        if isinstance(value, str):
            clean[key] = value.strip()[:limit]
    return clean


def step_of_field(prefix, name, mode=''):
    """Numéro (à partir de 1) de l'étape qui porte ce champ ; None s'il n'appartient à aucune."""
    for number, (_, _, beer_fields, other_fields) in enumerate(MODES[mode], start=1):
        if name in (beer_fields if prefix == 'beer' else other_fields):
            return number
    return None


def beer_form_for(mode, data=None, user=None, **kwargs):
    """Formulaire de la bière du mode : allégé (sans lieu de la brasserie ni description) pour un membre, complet pour la carte d'un bar."""
    return BeerForm(data, prefix='beer', user=user, light=mode != MENU, **kwargs)


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
    draft.current_step = min(max(step, 1), last_step(mode))
    draft.save()
    return draft


def _second_form(mode, data):
    if mode not in SECOND_FORMS:
        return None
    prefix, form_class = SECOND_FORMS[mode]
    return form_class(data, prefix=prefix)


def validate_step(user, step, posted, draft=None, mode=''):
    """Valide une étape avec les données du brouillon et de l'envoi. Retourne {'errors': [messages], 'fields': [id de champ]} (vides si valide)."""
    merged = {**(draft.data if draft else {}), **sanitize(posted)}
    data = dict(merged)
    for token in ('beer-confirm_brewery', 'beer-confirm_beer'):  # confirmations de doublon : seulement celles de l'envoi
        if posted.get(token):
            data[token] = posted.get(token)
    beer_form = beer_form_for(mode, data, user)
    other_form = _second_form(mode, data)
    forms = [(beer_form, MODES[mode][step - 1][2])]
    if other_form:
        forms.append((other_form, MODES[mode][step - 1][3]))
    messages, fields = [], []
    for form, names in forms:
        form.is_valid()
        for name in names:
            for message in form.errors.get(name, []):
                label = str(form.fields[name].label or name).replace(' (Optionnel)', '')
                messages.append(f"{label} : {message}")
                fields.append(form[name].id_for_label)
    if step == 1:  # doublons : erreurs du formulaire qui ne portent sur aucun champ précis
        messages.extend(str(message) for message in beer_form.non_field_errors())
    return {'errors': messages, 'fields': fields}


def first_step_with_errors(beer_form, other_form=None, mode=''):
    """Étape à rouvrir après un envoi final refusé : la première qui porte une erreur (la dernière si l'erreur ne se rattache à aucune)."""
    forms = [('beer', beer_form)] + ([(SECOND_FORMS[mode][0], other_form)] if other_form else [])
    steps = set()
    for prefix, form in forms:
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
    return last_step(mode) if any(form.errors for _, form in forms) else 1
