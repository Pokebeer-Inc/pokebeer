"""Rapport d'un établissement : des sections (onglets) qui partagent un même contexte de calcul.

Un rapport sert deux lecteurs sans qu'on écrive deux fois le même code :
- l'équipe, qui voit toutes les sections à la suite (pages Établissements et Bars de l'administration) ;
- le gérant de l'établissement, qui voit une section à la fois dans l'application (voir views/pro_analytics_views.py).

Ouvert/fermé : ajouter une section = ajouter une entrée à `SECTIONS` d'un rapport. Un rapport ne décide pas de qui le lit (voir access.py) ;
il ne calcule que des agrégats de l'établissement et des repères de comparaison anonymes de la communauté (seuil d'anonymat de privacy.py).
"""
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class Section:
    key: str
    title: str
    description: str
    build: Callable  # (contexte) -> liste de blocs
    empty_text: str = ''  # message quand la section n'a rien à afficher (sinon : pas encore assez de membres pour publier)


class PlaceReport:
    """Base des rapports. Une sous-classe fournit `kind`, `SECTIONS` et `context_class` (un objet construit une seule fois par rapport,
    qui calcule à la demande et garde ce que plusieurs sections utilisent : les dégustations, les lieux, la communauté...)."""
    kind = ''
    SECTIONS: tuple = ()
    context_class: type = None

    def __init__(self, place, period):
        self.place, self.period = place, period
        self._context = None

    @property
    def context(self):
        if self._context is None:
            self._context = self.context_class(self.place, self.period)
        return self._context

    @classmethod
    def section(cls, key):
        """La section de cette clé, ou None."""
        return next((section for section in cls.SECTIONS if section.key == key), None)

    def blocks(self, key=None, insights=False):
        """Blocs d'une section, ou de toutes à la suite (ordre des sections) quand `key` est omis. Les constats (Insight), destinés aux gérants,
        ne sont renvoyés que sur demande."""
        sections = (self.section(key),) if key else self.SECTIONS
        blocks, seen_notes = [], set()
        for section in sections:
            for block in section.build(self.context):
                if block.block_type == 'insight' and not insights:
                    continue
                if block.block_type == 'note':  # plusieurs sections peuvent expliquer la même absence de données : une seule note suffit
                    if block.text in seen_notes:
                        continue
                    seen_notes.add(block.text)
                blocks.append(block)
        return blocks
