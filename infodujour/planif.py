"""Décide, à chaque déclenchement du workflow (toutes les 30 minutes ou à la demande), quelles étapes exécuter.

GitHub Actions planifie en heure UTC et peut retarder un déclenchement de quelques minutes :
on raisonne donc en heure de Paris, sur des créneaux d'une demi-heure, avec rattrapage si un créneau
d'édition a été manqué.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta

from . import stockage
from .config import reglages
from .temps import _hhmm, heure_paris


def _dans_creneau(maintenant: datetime, hhmm: str, duree_min: int = 30) -> bool:
    h, m = _hhmm(hhmm)
    debut = maintenant.replace(hour=h, minute=m, second=0, microsecond=0)
    return debut <= maintenant < debut + timedelta(minutes=duree_min)


def _entre(maintenant: datetime, debut: str, fin: str) -> bool:
    h1, m1 = _hhmm(debut)
    h2, m2 = _hhmm(fin)
    return (h1, m1) <= (maintenant.hour, maintenant.minute) <= (h2, m2)


def decider(evenement: str, mode_demande: str = "", forcer: bool = False,
            maintenant: datetime | None = None) -> dict:
    p = reglages()["planning"]
    now = heure_paris(maintenant)
    aujourd_hui = now.date().isoformat()
    edition = stockage.lire_json("public/edition.json") or {}
    edition_du_jour = edition.get("date") == aujourd_hui
    d = {"collecte": False, "regroupement": False, "mode": "", "declenchement": "planifie",
         "publication": False, "rattrapage": False, "message": ""}

    if evenement == "workflow_dispatch":
        mode = mode_demande or "edition"
        if mode == "edition":
            if edition and not forcer:
                ecart = stockage.maintenant() - stockage.depuis_iso(edition["genere_le"])
                mini = p.get("delai_min_rafraichissement_min", 30)
                if ecart < timedelta(minutes=mini):
                    d["message"] = (f"Dernière édition il y a {int(ecart.total_seconds() // 60)} min : "
                                    f"attendre {mini} min entre deux rafraîchissements (ou cocher « forcer »).")
                    return d
            d.update(collecte=True, regroupement=True, mode="edition", declenchement="manuel", publication=True)
        elif mode == "rattrapage":
            d.update(rattrapage=True, message="Rattrapage demandé")
        elif mode == "collecte":
            d.update(collecte=True)
        elif mode == "preparation":
            d.update(collecte=True, regroupement=True, mode="preparation")
        return d

    # ------------------------------------------------------------ déclenchement planifié
    # GitHub déclenche en pratique environ une fois par heure, à une minute variable :
    # on collecte donc à chaque passage en journée (et non plus seulement sur les demi-heures paires).
    if _entre(now, p.get("collecte_debut", "06:00"), p.get("collecte_fin", "22:00")):
        d["collecte"] = True
    if _dans_creneau(now, p.get("edition", "17:30")):
        d.update(collecte=True, regroupement=True, mode="edition", publication=True)
        return d
    h_ed, m_ed = _hhmm(p.get("edition", "17:30"))
    apres_edition = (now.hour, now.minute) >= (h_ed, m_ed)
    if apres_edition and not edition_du_jour and now.hour < 21:
        d.update(collecte=True, regroupement=True, mode="edition", publication=True,
                 message="Créneau d'édition manqué : édition de rattrapage")
        return d
    # créneaux de préparation d'une heure, pour qu'un déclenchement tardif (ex. 15 h 36) ne les manque pas
    duree_prep = p.get("duree_preparation_min", 60)
    if not apres_edition and any(_dans_creneau(now, c, duree_prep) for c in p.get("preparation", [])):
        d.update(collecte=True, regroupement=True, mode="preparation")
        return d
    fin = p.get("rattrapage_fin", "22:00")
    h_f, m_f = _hhmm(fin)
    limite = now.replace(hour=h_f, minute=m_f, second=0, microsecond=0) + timedelta(minutes=30)
    if (p.get("rattrapage_auto", True) and edition_du_jour and apres_edition and now < limite
            and edition.get("statut_ia") != "complet"
            and any(s.get("statut_ia") == "en_attente" for s in edition.get("sujets", {}).values())):
        d["rattrapage"] = True
    return d


def ecrire_sorties(d: dict) -> None:
    sortie = os.environ.get("GITHUB_OUTPUT")
    lignes = [f"{k}={str(v).lower() if isinstance(v, bool) else v}" for k, v in d.items()]
    if sortie:
        with open(sortie, "a", encoding="utf-8") as f:
            f.write("\n".join(lignes) + "\n")
    resume = os.environ.get("GITHUB_STEP_SUMMARY")
    if resume:
        with open(resume, "a", encoding="utf-8") as f:
            f.write("### Planification\n\n" + "\n".join(f"- {l}" for l in lignes) + "\n")
    print("\n".join(lignes))
