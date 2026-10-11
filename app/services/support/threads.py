"""Éléments d'affichage communs aux pages de type « échange » : messages d'un fil avec l'équipe, signalement et sa décision."""
import html
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from django.utils.html import strip_tags

MEMBER = 'member'
TEAM = 'team'


BLOCK_END = re.compile(r'<\s*br\s*/?>|</\s*(?:p|div|li|h[1-6]|tr)\s*>', re.IGNORECASE)


def plain_text(value):
    """Texte brut : balises retirées, entités décodées, espaces normalisés. Les messages de l'équipe sont du texte, pas du HTML ;
    cela corrige aussi d'anciennes valeurs saisies avec un éditeur riche. Le rendu échappe de toute façon le résultat."""
    # Sauts de ligne à la place des retours à la ligne et fins de blocs, pour que les paragraphes ne se collent pas
    text = BLOCK_END.sub('\n', value or '')
    lines = [' '.join(line.split()) for line in html.unescape(strip_tags(text)).splitlines()]
    return re.sub(r'\n{3,}', '\n\n', '\n'.join(lines)).strip()

RESOLVED_DEFAULT_MESSAGE = "Votre signalement a été pris en compte et des actions ont été menées."


@dataclass(frozen=True)
class Entry:
    """Une bulle de conversation. `created_at` est facultatif : la date de la décision d'un signalement n'est pas conservée."""
    author_kind: str
    body: str
    created_at: Optional[datetime] = None

    @property
    def is_team(self):
        return self.author_kind == TEAM


def report_entries(report):
    """Signalement du membre puis, s'il y en a une, la réponse de l'équipe (lecture seule : aucun échange n'est possible)."""
    entries = [Entry(MEMBER, report.description, report.created_at)]
    decision = plain_text(report.admin_response)
    if decision:
        entries.append(Entry(TEAM, decision))
    elif report.status == 'resolved':
        entries.append(Entry(TEAM, RESOLVED_DEFAULT_MESSAGE))
    return entries
