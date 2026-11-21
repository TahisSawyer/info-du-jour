"""Mode sans IA : titre, résumé par extraction et colonnes « Comment chaque bord en parle »."""
from __future__ import annotations

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer

from .texte import MOTS_VIDES, phrases, tronquer

_PREFERENCE_TITRE = {"non-partisan": 0, "centre": 1, "centre-gauche": 2, "centre-droit": 2, "autre": 3, "gauche": 4, "droite": 4}


def choisir_titre(sources: list[dict]) -> str:
    """Titre de l'article le plus neutre : source non partisane, en français, factuelle."""
    candidats = [s for s in sources if not s["opinion"]] or sources
    candidats.sort(key=lambda s: (s["langue"] != "fr", _PREFERENCE_TITRE.get(s["orientation"], 3), s["reprise"]))
    return candidats[0]["titre"] if candidats else ""


def resumer(sources: list[dict], max_phrases: int = 3, max_car: int = 650) -> str:
    """Résumé par extraction : on garde les phrases des chapôs les plus centrales et les plus
    « consensuelles », c'est-à-dire dont le contenu se retrouve chez plusieurs bords."""
    candidates: list[tuple[str, dict]] = []
    francais = [s for s in sources if s["langue"] == "fr" and not s["opinion"] and s["chapo"]]
    base = francais or [s for s in sources if not s["opinion"] and s["chapo"]]
    for s in base:
        for p in phrases(s["chapo"]) or [s["chapo"]]:
            candidates.append((p, s))
    if not candidates:
        return ""
    if len(candidates) == 1:
        p, s = candidates[0]
        return f"{tronquer(p, max_car)} ({s['media']})"
    textes = [p for p, _ in candidates]
    try:
        m = TfidfVectorizer(strip_accents="unicode", stop_words=list(MOTS_VIDES)).fit_transform(textes).toarray()
    except ValueError:
        p, s = candidates[0]
        return f"{tronquer(p, max_car)} ({s['media']})"
    n = np.linalg.norm(m, axis=1, keepdims=True)
    n[n == 0] = 1
    m = m / n
    centre = m.mean(axis=0)
    centralite = m @ centre
    sim = m @ m.T
    scores = []
    for i, (_, s) in enumerate(candidates):
        bords = {candidates[j][1]["bord"] for j in range(len(candidates)) if j != i and sim[i, j] > 0.2}
        consensus = len(bords - {s["bord"]})
        scores.append(centralite[i] + 0.15 * consensus - 0.1 * s["reprise"])
    ordre = np.argsort(scores)[::-1]
    retenues: list[int] = []
    total = 0
    for i in ordre:
        if any(sim[i, j] > 0.5 for j in retenues):
            continue
        longueur = len(candidates[i][0])
        if total + longueur > max_car and retenues:
            continue
        retenues.append(int(i))
        total += longueur
        if len(retenues) >= max_phrases:
            break
    retenues.sort(key=lambda i: candidates[i][1]["publie_le"])
    return " ".join(f"{tronquer(candidates[i][0], max_car)} ({candidates[i][1]['media']})" for i in retenues)


def par_bord(sources: list[dict], maxi: int = 3) -> dict:
    colonnes: dict[str, list[dict]] = {"gauche": [], "centre": [], "droite": []}
    for s in sources:
        if len(colonnes[s["bord"]]) < maxi:
            colonnes[s["bord"]].append({"cle": s["cle"], "media": s["media"], "titre": s["titre"],
                                        "chapo": tronquer(s["chapo"], 220), "url": s["url"], "opinion": s["opinion"]})
    return colonnes


def remplir_sans_ia(sujet: dict, motif: str) -> None:
    sujet["titre"] = choisir_titre(list(sujet["sources"]))
    sujet["resume"] = resumer(sujet["sources"])
    sujet["controverse"] = bool(sujet.get("debat"))
    sujet["points_de_vue"] = []
    sujet["par_bord"] = par_bord(sujet["sources"])
    sujet["evolution"] = ""
    sujet["limites"] = "Couverture limitée à une seule sensibilité." if len({s["bord"] for s in sujet["sources"]}) == 1 else ""
    sujet["statut_ia"] = "sans_ia"
    sujet["motif_ia"] = motif
