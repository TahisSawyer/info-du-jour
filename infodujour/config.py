"""Chargement de la configuration (fichiers YAML du dossier config/)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

RACINE = Path(os.environ.get("INFODUJOUR_RACINE", Path(__file__).resolve().parent.parent))
DOSSIER_CONFIG = RACINE / "config"
DOSSIER_ETAT = Path(os.environ.get("INFODUJOUR_ETAT", RACINE / "etat"))

ORIENTATIONS = ["gauche", "centre-gauche", "centre", "centre-droit", "droite", "non-partisan", "autre"]
# Regroupement en trois « bords » pour l'affichage en colonnes et les angles morts
BORD = {
    "gauche": "gauche", "centre-gauche": "gauche",
    "centre": "centre", "non-partisan": "centre", "autre": "centre",
    "centre-droit": "droite", "droite": "droite",
}
LIBELLES_ORIENTATION = {
    "gauche": "Gauche", "centre-gauche": "Centre-gauche", "centre": "Centre",
    "centre-droit": "Centre-droit", "droite": "Droite", "non-partisan": "Non partisan",
    "autre": "Autre regard",
}


@dataclass
class Source:
    id: str
    nom: str
    pays: str
    langue: str
    region: str
    nature: str
    orientation: str
    flux: str = ""
    payant: bool = False
    actif: bool = True
    domaine: str = ""

    @property
    def bord(self) -> str:
        return BORD.get(self.orientation, "centre")


@dataclass
class Rubrique:
    id: str
    nom: str
    categories: list[str] = field(default_factory=list)
    mots_cles: list[str] = field(default_factory=list)


def _lire_yaml(nom: str) -> dict:
    with open(DOSSIER_CONFIG / nom, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _lire_liste(nom: str) -> list[str]:
    chemin = DOSSIER_CONFIG / nom
    if not chemin.exists():
        return []
    lignes = []
    for ligne in chemin.read_text(encoding="utf-8").splitlines():
        ligne = ligne.strip()
        if ligne and not ligne.startswith("#"):
            lignes.append(ligne.lower())
    return lignes


def _domaine(url: str) -> str:
    from urllib.parse import urlparse

    hote = urlparse(url).hostname or ""
    morceaux = hote.split(".")
    # garde le domaine « principal » (lemonde.fr, bbc.co.uk…)
    if len(morceaux) >= 3 and morceaux[-2] in {"co", "com", "org", "net"} and len(morceaux[-1]) == 2:
        return ".".join(morceaux[-3:])
    return ".".join(morceaux[-2:])


@lru_cache(maxsize=1)
def reglages() -> dict:
    return _lire_yaml("reglages.yaml")


@lru_cache(maxsize=1)
def sources() -> list[Source]:
    donnees = _lire_yaml("sources.yaml")
    resultat = []
    for s in donnees.get("sources", []):
        src = Source(**s)
        if src.orientation not in ORIENTATIONS:
            raise ValueError(f"Orientation inconnue pour {src.id} : {src.orientation}")
        if not src.domaine:
            src.domaine = _domaine(src.flux) if src.flux else ""
        resultat.append(src)
    return resultat


def sources_par_id() -> dict[str, Source]:
    return {s.id: s for s in sources()}


def source_par_domaine(url: str) -> Source | None:
    dom = _domaine(url)
    for s in sources():
        if s.domaine == dom:
            return s
    return None


@lru_cache(maxsize=1)
def config_api() -> dict:
    return _lire_yaml("sources.yaml").get("api", {}) or {}


@lru_cache(maxsize=1)
def rubriques() -> list[Rubrique]:
    resultat = []
    for r in _lire_yaml("rubriques.yaml").get("rubriques", []):
        r["categories"] = [str(c) for c in r.get("categories", [])]
        r["mots_cles"] = [str(m) for m in r.get("mots_cles", [])]
        resultat.append(Rubrique(**r))
    return resultat


@lru_cache(maxsize=1)
def termes_connotes() -> list[str]:
    return _lire_liste("termes_connotes.txt")


@lru_cache(maxsize=1)
def lexique_debat() -> list[str]:
    return _lire_liste("lexique_debat.txt")


def fuseau() -> ZoneInfo:
    return ZoneInfo(reglages().get("fuseau", "Europe/Paris"))
