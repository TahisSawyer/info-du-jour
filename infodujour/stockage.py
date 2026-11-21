"""Lecture et écriture de l'état persistant (branche Git « etat » du dépôt).

Arborescence :
    etat/articles.json.gz      articles des dernières 72 h
    etat/vecteurs.npz          vecteurs sémantiques déjà calculés (par identifiant d'article)
    etat/flux.json             santé de chaque flux (dernier succès, échecs consécutifs, ETag)
    etat/cache_resumes.json    résumés IA réutilisables (préparation de l'après-midi, rattrapage)
    etat/suivi.json            sujets des jours précédents (suivi « Nouveau » / « Suite »)
    etat/journal.json          historique des exécutions
    etat/travail/              fichiers intermédiaires entre deux étapes d'une même exécution
    etat/public/               données publiées avec la PWA (éditions, sources, pluralisme, audio)
"""
from __future__ import annotations

import gzip
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .config import DOSSIER_ETAT


def chemin(*parties: str) -> Path:
    p = DOSSIER_ETAT.joinpath(*parties)
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def lire_json(nom: str, defaut: Any = None) -> Any:
    p = chemin(nom)
    if not p.exists():
        return defaut
    if nom.endswith(".gz"):
        with gzip.open(p, "rt", encoding="utf-8") as f:
            return json.load(f)
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def ecrire_json(nom: str, donnees: Any, compact: bool = False) -> None:
    p = chemin(nom)
    tmp = p.with_suffix(p.suffix + ".tmp")
    if nom.endswith(".gz"):
        with gzip.open(tmp, "wt", encoding="utf-8") as f:
            json.dump(donnees, f, ensure_ascii=False, separators=(",", ":"))
    else:
        with open(tmp, "w", encoding="utf-8") as f:
            if compact:
                json.dump(donnees, f, ensure_ascii=False, separators=(",", ":"))
            else:
                json.dump(donnees, f, ensure_ascii=False, indent=1)
    os.replace(tmp, p)


def maintenant() -> datetime:
    return datetime.now(timezone.utc)


def iso(d: datetime) -> str:
    return d.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def depuis_iso(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


# ------------------------------------------------------------------ articles
def charger_articles() -> dict[str, dict]:
    return {a["id"]: a for a in lire_json("articles.json.gz", [])}


def enregistrer_articles(articles: dict[str, dict], conservation_h: int) -> None:
    limite = maintenant() - timedelta(hours=conservation_h)
    gardes = [a for a in articles.values() if depuis_iso(a["publie_le"]) >= limite]
    gardes.sort(key=lambda a: a["publie_le"], reverse=True)
    ecrire_json("articles.json.gz", gardes)


# ------------------------------------------------------------------ vecteurs
def charger_vecteurs() -> dict:
    import numpy as np

    p = chemin("vecteurs.npz")
    if not p.exists():
        return {}
    d = np.load(p, allow_pickle=False)
    return {i: v for i, v in zip(d["ids"].tolist(), d["vecs"])}


def enregistrer_vecteurs(vecteurs: dict, ids_gardes: set[str]) -> None:
    import numpy as np

    ids = [i for i in vecteurs if i in ids_gardes]
    if not ids:
        return
    vecs = np.stack([vecteurs[i] for i in ids]).astype(np.float16)
    np.savez_compressed(chemin("vecteurs.npz"), ids=np.array(ids), vecs=vecs)


# ------------------------------------------------------------------ journal
def journaliser(evenement: dict) -> None:
    journal = lire_json("journal.json", [])
    evenement = {"le": iso(maintenant()), **evenement}
    journal.insert(0, evenement)
    ecrire_json("journal.json", journal[:200])
