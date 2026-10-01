from django.db import models

from .services.slugs import generate_slug


class PublicSlugField(models.SlugField):
    """
    Identifiant public d'un objet, exposé à la place de la clé primaire dans les URLs, les formulaires et le JSON.

    - Généré une seule fois à la création (jamais modifié : les liens existants restent valides).
    - `source` : champ du modèle servant de libellé lisible ; sans lui, le slug est un jeton opaque
      (à réserver aux contenus privés, qui n'ont pas à révéler leur titre dans l'URL).
    - Généré dans pre_save : couvre save(), create() et bulk_create().
    - L'unicité est garantie par la base ; la clé primaire reste l'identifiant interne (jointures, ordre).
    """

    def __init__(self, *args, source=None, **kwargs):
        self.source = source
        kwargs.setdefault('max_length', 150)
        kwargs.setdefault('unique', True)
        kwargs.setdefault('editable', False)
        super().__init__(*args, **kwargs)

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        if self.source:
            kwargs['source'] = self.source
        return name, path, args, kwargs

    def pre_save(self, model_instance, add):
        value = getattr(model_instance, self.attname)
        if not value:
            label = getattr(model_instance, self.source, '') if self.source else ''
            value = generate_slug(label, self.max_length)
            setattr(model_instance, self.attname, value)
        return value
