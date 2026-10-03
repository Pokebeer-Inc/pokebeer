"""Blocs d'affichage indépendants du rendu : chaque page d'analytics renvoie une liste de blocs."""
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

from django.utils.text import slugify


@dataclass
class Kpi:
    label: str
    value: Any
    delta: Optional[float] = None  # variation en % par rapport à la période précédente
    hint: str = ""
    block_type: str = field(default="kpi", init=False)
    id: str = field(init=False)

    def __post_init__(self):
        self.id = 'kpi-' + (slugify(self.label) or 'valeur')  # identifiant stable : sert à mémoriser la disposition

    @property
    def title(self):
        return self.label


@dataclass
class Chart:
    id: str
    title: str
    kind: str  # line | bar | hbar | donut | heatmap
    categories: list
    series: list  # [{'name': str, 'data': [...]}]
    subtitle: str = ""
    stacked: bool = False
    dashed: list = field(default_factory=list)  # indices des séries en pointillés (prévisions)
    block_type: str = field(default="chart", init=False)

    def spec(self):
        return asdict(self)


@dataclass
class Table:
    id: str
    title: str
    columns: list
    rows: list
    subtitle: str = ""
    block_type: str = field(default="table", init=False)


@dataclass
class MapBlock:
    id: str
    title: str
    points: list  # [{'lat','lng','radius','color','lines': [str, ...]}]
    subtitle: str = ""
    block_type: str = field(default="map", init=False)

    def spec(self):
        return asdict(self)


@dataclass
class Note:
    """Avertissement ou précision méthodologique affichée au lecteur."""
    text: str
    block_type: str = field(default="note", init=False)
