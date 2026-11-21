"""Suivi d'un sujet d'un jour à l'autre (badges « Nouveau » / « Suite », « Ce qui a changé »)."""
from __future__ import annotations

from datetime import timedelta

from . import stockage

JOURS_SUIVIS = 4
SEUIL = 0.25


def _jaccard(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def rattacher(sujets: list[dict], date_edition: str) -> None:
    """Ajoute à chaque sujet « piste » (identifiant stable dans le temps), « suivi » (nouveau/suite)
    et, pour une suite, le résumé de la veille afin que l'IA décrive ce qui a changé."""
    historique = stockage.lire_json("suivi.json", [])
    anciens = [h for h in historique if h["date"] < date_edition]
    for s in sujets:
        mots = set(s.get("mots_cles", []))
        ids = set(s["article_ids"])
        meilleur, score_max = None, 0.0
        for h in anciens:
            score = max(_jaccard(mots, set(h["mots_cles"])), _jaccard(ids, set(h.get("article_ids", []))) * 1.5)
            if score > score_max:
                meilleur, score_max = h, score
        if meilleur and score_max >= SEUIL:
            s["piste"] = meilleur["piste"]
            s["suivi"] = "suite"
            s["precedent"] = {"date": meilleur["date"], "titre": meilleur["titre"], "resume": meilleur["resume"]}
        else:
            s["piste"] = s["id"]
            s["suivi"] = "nouveau"


def memoriser(sujets: list[dict], date_edition: str) -> None:
    historique = [h for h in stockage.lire_json("suivi.json", []) if h["date"] != date_edition]
    for s in sujets:
        historique.append({"date": date_edition, "piste": s.get("piste", s["id"]), "titre": s.get("titre", ""),
                           "resume": s.get("resume", "")[:600], "mots_cles": s.get("mots_cles", []),
                           "article_ids": s["article_ids"][:40]})
    limite = (stockage.maintenant() - timedelta(days=JOURS_SUIVIS)).date().isoformat()
    stockage.ecrire_json("suivi.json", [h for h in historique if h["date"] >= limite], compact=True)
