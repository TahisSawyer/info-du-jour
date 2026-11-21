"""Qualification des sujets (périmètre, rubrique, débat), score d'importance et sélection des Tops."""
from __future__ import annotations

import math
from collections import Counter
from datetime import timedelta

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer

from . import stockage
from .config import BORD, LIBELLES_ORIENTATION, lexique_debat, reglages, rubriques, sources_par_id
from .texte import MOTS_VIDES, contient_terme, empreinte, normaliser_mots

_MOTS_FRANCE = ["france", "francais", "francaise", "paris", "assemblee nationale", "senat", "elysee", "matignon",
                "conseil constitutionnel", "conseil d'etat", "prefecture", "prefet", "sncf", "ratp", "bercy",
                "marseille", "lyon", "toulouse", "lille", "bordeaux", "nantes", "strasbourg", "outre-mer",
                "nouvelle-caledonie", "guadeloupe", "martinique", "corse", "bretagne", "hexagone", "smic", "urssaf"]
_CATS_FRANCE = ["france", "politique", "societe", "regions", "paris", "ile-de-france", "faits-divers", "justice"]
_CATS_MONDE = ["international", "monde", "world", "europe", "afrique", "africa", "asie", "asia", "ameriques",
               "americas", "moyen-orient", "middle east", "proche-orient", "us", "uk", "geopolitique"]


def infos_source(sid: str) -> dict:
    s = sources_par_id().get(sid)
    if s:
        return {"id": s.id, "nom": s.nom, "orientation": s.orientation, "payant": s.payant, "pays": s.pays,
                "region": s.region, "nature": s.nature, "langue": s.langue}
    nom = stockage.lire_json("medias_api.json", {}).get(sid, {}).get("nom", "Autre média")
    return {"id": sid, "nom": nom, "orientation": "autre", "payant": False, "pays": "??", "region": "monde",
            "nature": "generaliste", "langue": "en"}


def _entropie_normalisee(compte: Counter) -> float:
    total = sum(compte.values())
    k = len([v for v in compte.values() if v])
    if total <= 1 or k <= 1:
        return 0.0
    h = -sum((v / total) * math.log(v / total) for v in compte.values() if v)
    return h / math.log(min(total, 7))


def _perimetre(articles: list[dict], medias: list[dict]) -> str:
    part_inter = sum(1 for m in medias if m["region"] != "france") / max(len(medias), 1)
    score_fr, score_int = 0.0, part_inter * 3
    for a in articles:
        texte = normaliser_mots(a["titre"] + " " + a["chapo"])
        score_fr += 0.6 * sum(1 for m in _MOTS_FRANCE if contient_terme(texte, m))
        cats = normaliser_mots(" ".join(a.get("categories", [])) + " " + a["url"])
        if any(c in cats for c in _CATS_MONDE):
            score_int += 1
        elif any(c in cats for c in _CATS_FRANCE):
            score_fr += 1
    score_fr /= max(len(articles), 1) ** 0.5
    score_int /= max(len(articles), 1) ** 0.5
    return "france" if score_fr > score_int else "international"


def _rubrique(articles: list[dict]) -> str:
    scores: Counter = Counter()
    for a in articles:
        texte = normaliser_mots(a["titre"] + " " + a["chapo"])
        cats = normaliser_mots(" ".join(a.get("categories", [])) + " " + a["url"])
        for r in rubriques():
            if any(normaliser_mots(c) in cats for c in r.categories):
                scores[r.id] += 2
            scores[r.id] += sum(1 for m in r.mots_cles if contient_terme(texte, m))
    if not scores or scores.most_common(1)[0][1] == 0:
        return "societe"
    return scores.most_common(1)[0][0]


def _debat(articles: list[dict], bords: Counter) -> bool:
    lexique = lexique_debat()
    hits = 0
    for a in articles:
        texte = normaliser_mots(a["titre"] + " " + a["chapo"])
        if any(contient_terme(texte, m) for m in lexique):
            hits += 1
    a_opinions = any(a.get("opinion") for a in articles)
    deux_bords = bords.get("gauche", 0) >= 1 and bords.get("droite", 0) >= 1
    return hits >= 2 or (hits >= 1 and deux_bords) or (a_opinions and deux_bords)


def construire_sujets(articles: list[dict], groupes: list[list[int]]) -> list[dict]:
    cfg = reglages()
    poids_reprise = cfg["regroupement"].get("poids_reprise", 0.25)
    demi_vie = cfg["classement"].get("demi_vie_heures", 12)
    now = stockage.maintenant()
    sujets = []
    for g in groupes:
        arts = sorted((articles[i] for i in g), key=lambda a: a["publie_le"])
        par_media: dict[str, list[dict]] = {}
        for a in arts:
            par_media.setdefault(a["source"], []).append(a)
        medias = [infos_source(sid) for sid in par_media]
        orient = Counter(m["orientation"] for m in medias)
        bords = Counter(BORD.get(m["orientation"], "centre") for m in medias)
        independants = sum(1 for sid, la in par_media.items() if any(not a.get("reprise") for a in la))
        couverture = independants + poids_reprise * (len(par_media) - independants)
        dernier = max(stockage.depuis_iso(a["publie_le"]) for a in arts)
        age_h = max((now - dernier).total_seconds() / 3600, 0)
        perimetre = _perimetre(arts, medias)
        part_autre = sum(1 for m in medias if (m["region"] != "france") == (perimetre == "france")) / max(len(medias), 1)
        sujets.append({
            "id": "s" + empreinte(arts[0]["id"], 10),
            "article_ids": [a["id"] for a in arts],
            "nb_medias": len(par_media),
            "couverture_effective": round(couverture, 2),
            "orientations": dict(orient),
            "bords": dict(bords),
            "diversite": round(_entropie_normalisee(orient), 3),
            "fraicheur": round(0.5 ** (age_h / demi_vie), 3),
            "reprise_ext": round(part_autre, 3),
            "perimetre": perimetre,
            "rubrique": _rubrique(arts),
            "debat": _debat(arts, bords),
            "opinion_seule": all(a.get("opinion") for a in arts),
            "depeches": sum(1 for a in arts if a.get("reprise")),
            "premier": arts[0]["publie_le"],
            "dernier": stockage.iso(dernier),
        })
    _scorer(sujets)
    _mots_cles(sujets, articles)
    return sujets


def _scorer(sujets: list[dict]) -> None:
    p = reglages()["classement"]["poids"]
    cmax = max((s["couverture_effective"] for s in sujets), default=1) or 1
    for s in sujets:
        s["score"] = round(p["couverture"] * s["couverture_effective"] / cmax + p["diversite"] * s["diversite"]
                           + p["fraicheur"] * s["fraicheur"] + p["reprise"] * s["reprise_ext"], 4)


def _mots_cles(sujets: list[dict], articles: list[dict]) -> None:
    par_id = {a["id"]: a for a in articles}
    textes = [" ".join(par_id[i]["titre"] for i in s["article_ids"]) for s in sujets]
    if not textes:
        return
    try:
        vec = TfidfVectorizer(strip_accents="unicode", stop_words=list(MOTS_VIDES), max_df=0.3,
                              token_pattern=r"(?u)\b[^\W\d_][\w'-]{2,}\b")
        m = vec.fit_transform(textes)
    except ValueError:
        for s in sujets:
            s["mots_cles"] = []
        return
    termes = np.array(vec.get_feature_names_out())
    for k, s in enumerate(sujets):
        ligne = m[k].toarray().ravel()
        idx = ligne.argsort()[::-1][:8]
        s["mots_cles"] = [str(termes[i]) for i in idx if ligne[i] > 0]


def est_angle_mort(s: dict) -> str | None:
    cfg = reglages()["classement"]
    g, d = s["bords"].get("gauche", 0), s["bords"].get("droite", 0)
    partisans = g + d
    if s["nb_medias"] < cfg.get("angles_morts_medias_min", 4) or partisans < 3:
        return None
    if g / partisans >= 0.8 and d <= 1:
        return "gauche"
    if d / partisans >= 0.8 and g <= 1:
        return "droite"
    return None


def selectionner(sujets: list[dict]) -> dict:
    """Choisit les Tops 10, les sujets de chaque rubrique et les angles morts.
    Renvoie aussi l'ordre de priorité pour l'IA."""
    cfg = reglages()["classement"]
    n_top, n_rub = cfg.get("taille_top", 10), cfg.get("sujets_par_rubrique", 5)
    min_top = cfg.get("medias_min_top", 2)
    tries = sorted(sujets, key=lambda s: s["score"], reverse=True)
    eligibles = [s for s in tries if not s["opinion_seule"]]
    top_fr = [s for s in eligibles if s["perimetre"] == "france" and s["nb_medias"] >= min_top][:n_top]
    top_int = [s for s in eligibles if s["perimetre"] == "international" and s["nb_medias"] >= min_top][:n_top]
    deja = {s["id"] for s in top_fr + top_int}
    rubs = []
    for r in rubriques():
        candidats = [s for s in eligibles if s["rubrique"] == r.id
                     and not (cfg.get("rubriques_hors_tops", True) and s["id"] in deja)]
        choisis = [s for s in candidats if s["nb_medias"] >= 2][:n_rub]
        if len(choisis) < n_rub:  # complète avec des sujets à source unique si la rubrique est maigre
            choisis += [s for s in candidats if s["nb_medias"] < 2][: n_rub - len(choisis)]
        rubs.append({"id": r.id, "nom": r.nom, "sujets": [s["id"] for s in choisis]})
        deja |= {s["id"] for s in choisis}
    angles = []
    for s in eligibles:
        cote = est_angle_mort(s)
        if cote:
            s["angle_mort"] = cote
            angles.append(s)
        if len(angles) >= cfg.get("angles_morts_max", 5):
            break
    par_id = {s["id"]: s for s in sujets}
    for rang, s in enumerate(top_fr, 1):
        s["rang"] = rang
    for rang, s in enumerate(top_int, 1):
        s["rang"] = rang
    priorite: list[str] = []
    for s in top_fr + top_int + [par_id[i] for r in rubs for i in r["sujets"]] + angles:
        if s["id"] not in priorite:
            priorite.append(s["id"])
    return {
        "tops": {"france": [s["id"] for s in top_fr], "international": [s["id"] for s in top_int]},
        "rubriques": rubs,
        "angles_morts": [s["id"] for s in angles],
        "priorite": priorite,
    }


def sources_du_sujet(s: dict, par_id: dict[str, dict], maxi: int) -> list[dict]:
    """Choisit les articles à afficher : un par média, en alternant les bords pour l'équilibre,
    les articles originaux et factuels d'abord. Les tribunes sont ajoutées à la fin si débat."""
    par_media: dict[str, dict] = {}
    for aid in s["article_ids"]:
        a = par_id[aid]
        actuel = par_media.get(a["source"])
        cle = (a.get("opinion", False), a.get("reprise", False), a.get("accroche", False))
        if actuel is None or cle < (actuel.get("opinion", False), actuel.get("reprise", False), actuel.get("accroche", False)):
            par_media[a["source"]] = a
    files: dict[str, list[dict]] = {"gauche": [], "centre": [], "droite": []}
    for a in sorted(par_media.values(), key=lambda a: (a.get("opinion", False), a.get("reprise", False), a["publie_le"])):
        files[BORD.get(infos_source(a["source"])["orientation"], "centre")].append(a)
    choisis: list[dict] = []
    while len(choisis) < maxi and any(files.values()):
        for bord in ("centre", "gauche", "droite"):
            if files[bord] and len(choisis) < maxi:
                choisis.append(files[bord].pop(0))
    # tribunes et éditoriaux : utiles pour les points de vue, ajoutés s'il y a de la place
    if s.get("debat"):
        for aid in s["article_ids"]:
            a = par_id[aid]
            if a.get("opinion") and a not in choisis and len(choisis) < maxi + 2:
                choisis.append(a)
    resultat = []
    for k, a in enumerate(choisis, 1):
        info = infos_source(a["source"])
        resultat.append({
            "cle": f"S{k}", "media": info["nom"], "source_id": info["id"], "orientation": info["orientation"],
            "orientation_libelle": LIBELLES_ORIENTATION.get(info["orientation"], info["orientation"]),
            "bord": BORD.get(info["orientation"], "centre"), "payant": info["payant"], "langue": a["langue"],
            "titre": a["titre"], "chapo": a["chapo"] if not a.get("accroche") else "", "url": a["url"],
            "publie_le": a["publie_le"], "opinion": a.get("opinion", False), "reprise": a.get("reprise", False),
        })
    return resultat


def fenetre_articles(articles: dict[str, dict]) -> list[dict]:
    h = reglages()["collecte"].get("fenetre_heures", 30)
    limite = stockage.maintenant() - timedelta(hours=h)
    return [a for a in articles.values() if stockage.depuis_iso(a["publie_le"]) >= limite]
