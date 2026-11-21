"""Regroupement des articles en sujets et repérage des reprises de dépêches d'agence."""
from __future__ import annotations

import numpy as np
from sklearn.cluster import AgglomerativeClustering
from sklearn.feature_extraction.text import TfidfVectorizer

from .config import reglages


def regrouper(vecteurs: np.ndarray, moteur: str) -> list[list[int]]:
    """Renvoie des groupes d'indices d'articles (un groupe = un sujet)."""
    n = len(vecteurs)
    if n == 0:
        return []
    if n == 1:
        return [[0]]
    cfg = reglages()["regroupement"]
    seuil = cfg["distance_fastembed"] if moteur == "fastembed" else cfg["distance_tfidf"]
    modele = AgglomerativeClustering(n_clusters=None, metric="cosine", linkage="average", distance_threshold=seuil)
    etiquettes = modele.fit_predict(vecteurs)
    groupes: dict[int, list[int]] = {}
    for i, e in enumerate(etiquettes):
        groupes.setdefault(int(e), []).append(i)
    return sorted(groupes.values(), key=len, reverse=True)


class _Union:
    def __init__(self, n: int):
        self.p = list(range(n))

    def trouver(self, i: int) -> int:
        while self.p[i] != i:
            self.p[i] = self.p[self.p[i]]
            i = self.p[i]
        return i

    def unir(self, a: int, b: int) -> None:
        self.p[self.trouver(a)] = self.trouver(b)


def marquer_reprises(articles: list[dict]) -> None:
    """Dans un sujet, repère les textes quasi identiques publiés par des médias différents
    (dépêche AFP, Reuters, AP reprise telle quelle). Chaque article reçoit « souche » = identifiant
    de l'article le plus ancien de son groupe, et « reprise » = True s'il n'est pas l'original."""
    for a in articles:
        a["souche"], a["reprise"] = a["id"], False
    textes = [(a["titre"] + " " + a["chapo"]).strip() for a in articles]
    if len(articles) < 2:
        return
    try:
        m = TfidfVectorizer(analyzer="char_wb", ngram_range=(4, 5), lowercase=True,
                            strip_accents="unicode").fit_transform(textes)
    except ValueError:
        return
    sim = (m @ m.T).toarray()
    seuil = reglages()["regroupement"].get("seuil_depeche", 0.80)
    u = _Union(len(articles))
    for i in range(len(articles)):
        for j in range(i + 1, len(articles)):
            if articles[i]["source"] != articles[j]["source"] and sim[i, j] >= seuil and len(articles[i]["chapo"]) > 80:
                u.unir(i, j)
    groupes: dict[int, list[int]] = {}
    for i in range(len(articles)):
        groupes.setdefault(u.trouver(i), []).append(i)
    for membres in groupes.values():
        if len(membres) < 2:
            continue
        original = min(membres, key=lambda k: articles[k]["publie_le"])
        for k in membres:
            articles[k]["souche"] = articles[original]["id"]
            articles[k]["reprise"] = k != original
