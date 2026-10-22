"""Raretés des bières du tirage du jour : règle pure, sans accès à la base.

La rareté d'une bière est relative au catalogue : on classe les bières de la moins goûtée à la plus goûtée, puis chaque palier prend une
part de ce classement (`share`). Le tirage choisit d'abord un palier selon sa probabilité (`weight`), puis une bière au hasard dans ce
palier : les deux séries de pourcentages sont volontairement différentes (un palier « Légendaire » regroupe 10 % des bières mais ne sort
que 2 % du temps), c'est ce qui rend une bière légendaire réellement plus rare qu'une bière commune.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Rarity:
    key: str
    label: str
    share: float   # part du catalogue classée dans ce palier (la somme vaut 1)
    weight: float  # probabilité de sortie d'une carte de ce palier


# Du plus commun au plus rare : l'ordre sert au classement (des plus goûtées aux moins goûtées) et à l'ordre de révélation
COMMON = Rarity('common', 'Commune', share=0.40, weight=60)
RARE = Rarity('rare', 'Rare', share=0.30, weight=28)
EPIC = Rarity('epic', 'Épique', share=0.20, weight=10)
LEGENDARY = Rarity('legendary', 'Légendaire', share=0.10, weight=2)

RARITIES = (COMMON, RARE, EPIC, LEGENDARY)
BY_KEY = {rarity.key: rarity for rarity in RARITIES}
CHOICES = [(rarity.key, rarity.label) for rarity in RARITIES]


def get(key):
    return BY_KEY[key]


def split_ranking(ranked_ids):
    """Répartit des identifiants classés de la bière la plus goûtée à la moins goûtée en {palier: [identifiants]}.

    Les bornes sont arrondies pour que chaque bière ait un palier ; avec très peu de bières, un palier peut rester vide (le tirage l'ignore).
    """
    total = len(ranked_ids)
    tiers = {}
    start = 0
    cumulated = 0.0
    for rarity in RARITIES:
        cumulated += rarity.share
        end = total if rarity is RARITIES[-1] else round(total * cumulated)
        tiers[rarity.key] = list(ranked_ids[start:end])
        start = end
    return tiers


def pick_rarity(rng, available):
    """Palier tiré au hasard parmi ceux qui ont encore des bières, selon leurs probabilités. `available` : clés de palier non vides."""
    open_tiers = [rarity for rarity in RARITIES if rarity.key in available]
    return rng.choices(open_tiers, weights=[rarity.weight for rarity in open_tiers])[0]
