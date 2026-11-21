"""Construction, rédaction, publication et rattrapage d'une édition."""
from __future__ import annotations

import logging
import re
import time
from collections import Counter
from datetime import timedelta

from . import extraction, stockage, suivi
from .classement import (construire_sujets, fenetre_articles, infos_source, selectionner, sources_du_sujet)
from .config import BORD, ORIENTATIONS, LIBELLES_ORIENTATION, reglages, rubriques, sources
from .ia import MOTIFS, Redacteur
from .regroupement import marquer_reprises, regrouper
from .temps import _hhmm, heure_paris
from .vecteurs import vectoriser

log = logging.getLogger(__name__)
TRAVAIL = "travail/edition.json"
_REFS = re.compile(r"\s*\[\s*S\d+(?:\s*[,;]\s*S\d+)*\s*\]")


# =================================================================== 1. regroupement et classement
def regrouper_et_classer(mode: str = "edition", declenchement: str = "planifie") -> dict:
    debut = time.time()
    articles = sorted(fenetre_articles(stockage.charger_articles()), key=lambda a: a["publie_le"])
    log.info("%s articles dans la fenêtre", len(articles))
    vecteurs, moteur = vectoriser(articles) if articles else (None, "aucun")
    groupes = regrouper(vecteurs, moteur) if articles else []
    for g in groupes:
        marquer_reprises([articles[i] for i in g])
    sujets = construire_sujets(articles, groupes)
    selection = selectionner(sujets)
    par_article = {a["id"]: a for a in articles}
    par_sujet = {s["id"]: s for s in sujets}
    maxi = reglages()["classement"].get("sources_affichees", 6)
    retenus = {}
    for sid in selection["priorite"]:
        s = par_sujet[sid]
        s["sources"] = sources_du_sujet(s, par_article, maxi)
        s["source_unique"] = s["nb_medias"] == 1
        retenus[sid] = s
    date = heure_paris().date().isoformat()
    suivi.rattacher(list(retenus.values()), date)
    travail = {
        "mode": mode, "declenchement": declenchement, "date": date, "debut": stockage.iso(stockage.maintenant()),
        "moteur": moteur, "nb_articles": len(articles), "nb_sujets": len(sujets),
        "medias_actifs": len({a["source"] for a in articles}),
        "repartition_articles": dict(Counter(infos_source(a["source"])["orientation"] for a in articles)),
        "selection": selection, "sujets": retenus,
    }
    stockage.ecrire_json(TRAVAIL, travail, compact=True)
    log.info("Regroupement : %s sujets, %s retenus (%s s, moteur %s)", len(sujets), len(retenus),
             round(time.time() - debut), moteur)
    return travail


# =================================================================== 2. rédaction
def _jaccard(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def _reutiliser(sujet: dict, cache: list[dict]) -> bool:
    cfg = reglages()["ia"]
    ids = set(sujet["article_ids"])
    for c in cache:
        anciens = set(c["article_ids"])
        if _jaccard(ids, anciens) >= cfg.get("reutilisation_jaccard", 0.7) and \
                len(ids - anciens) <= cfg.get("reutilisation_nouveaux_max", 3):
            for cle in ("titre", "resume", "controverse", "points_de_vue", "limites", "evolution", "ia_modele", "sources"):
                sujet[cle] = c[cle]
            sujet["statut_ia"], sujet["motif_ia"] = "ia", ""
            sujet["reutilise"] = True
            return True
    return False


def _memoriser_cache(sujets: list[dict]) -> None:
    cache = stockage.lire_json("cache_resumes.json", [])
    limite = stockage.iso(stockage.maintenant() - timedelta(hours=30))
    cache = [c for c in cache if c["cree_le"] >= limite]
    connus = {frozenset(c["article_ids"]) for c in cache}
    for s in sujets:
        if s.get("statut_ia") == "ia" and not s.get("reutilise") and frozenset(s["article_ids"]) not in connus:
            cache.append({k: s.get(k) for k in ("article_ids", "titre", "resume", "controverse", "points_de_vue",
                                                "limites", "evolution", "ia_modele", "sources")}
                         | {"cree_le": stockage.iso(stockage.maintenant())})
    stockage.ecrire_json("cache_resumes.json", cache[-400:], compact=True)


def rediger() -> dict:
    travail = stockage.lire_json(TRAVAIL)
    if not travail:
        raise SystemExit("Aucun regroupement à rédiger")
    cfg = reglages()
    budget = cfg["planning"].get("budget_edition_min", 20) * 60
    debut = stockage.depuis_iso(travail["debut"]).timestamp()
    redacteur = Redacteur(echeance=debut + budget)
    sujets = travail["sujets"]
    sel = travail["selection"]
    ids_tops = sel["tops"]["france"] + sel["tops"]["international"]
    if travail["mode"] == "preparation":  # on prépare seulement les futurs Tops, sans publier
        ordre = [i for i in sel["priorite"] if i in ids_tops][:16]
    else:
        ordre = sel["priorite"]
    cache = stockage.lire_json("cache_resumes.json", [])
    a_rediger = {"tops": [], "rubriques": []}
    reutilises = 0
    for sid in ordre:
        s = sujets[sid]
        if _reutiliser(s, cache):
            reutilises += 1
        else:
            a_rediger["tops" if sid in ids_tops else "rubriques"].append(s)
    restants = redacteur.rediger(a_rediger["tops"], "tops")
    restants += redacteur.rediger(a_rediger["rubriques"], "rubriques")
    for s in restants:
        extraction.remplir_sans_ia(s, s.pop("_motif", redacteur.motif_absence()))
    _memoriser_cache([sujets[i] for i in ordre])
    if travail["mode"] != "preparation":
        travail["essentiel"] = {p: _essentiel(redacteur, [sujets[i] for i in sel["tops"][p][:5]])
                                for p in ("france", "international")}
    travail["ia_bilan"] = {**redacteur.bilan, "reutilises": reutilises,
                           "rediges": sum(1 for i in ordre if sujets[i].get("statut_ia") == "ia")}
    stockage.ecrire_json(TRAVAIL, travail, compact=True)
    stockage.journaliser({"etape": f"redaction-{travail['mode']}", **travail["ia_bilan"],
                          "sans_ia": len(restants)})
    return travail


def _essentiel(redacteur, tops: list[dict]) -> dict:
    """« L'essentiel » d'un périmètre : une phrase par sujet du Top 5 (IA), à défaut les titres."""
    points = None
    if redacteur is not None and tops and all(s.get("statut_ia") == "ia" for s in tops):
        points = redacteur.essentiel(tops)
    if points:
        return {"points": points, "statut_ia": "ia"}
    return {"points": [s.get("titre", "") for s in tops if s.get("titre")], "statut_ia": "sans_ia"}


# =================================================================== 3. publication
def _rattrapage_possible() -> bool:
    p = reglages()["planning"]
    if not p.get("rattrapage_auto", True):
        return False
    h, m = _hhmm(p.get("rattrapage_fin", "22:00"))
    maintenant = heure_paris()
    return maintenant < maintenant.replace(hour=h, minute=m, second=0, microsecond=0)


_MOTIFS_RATTRAPABLES = {MOTIFS["quota"], MOTIFS["indisponible"], MOTIFS["delai"]}


def _statut_edition(sujets: list[dict]) -> tuple[str, int, int]:
    total = len(sujets)
    ia = sum(1 for s in sujets if s.get("statut_ia") == "ia")
    statut = "complet" if ia == total else ("aucun" if ia == 0 else "partiel")
    return statut, ia, total


def _public(s: dict) -> dict:
    garde = {k: v for k, v in s.items() if not k.startswith("_") and k not in ("article_ids",)}
    if s.get("precedent"):
        garde["precedent"] = {"date": s["precedent"]["date"], "titre": s["precedent"]["titre"]}
    return garde


def _stats_pluralisme(edition: dict) -> dict:
    liens = Counter()
    for s in edition["sujets"].values():
        for src in s["sources"]:
            liens[src["orientation"]] += 1
    total = sum(liens.values()) or 1
    bords = Counter()
    for o, n in liens.items():
        bords[BORD.get(o, "centre")] += n
    sujets = list(edition["sujets"].values())
    cfg = reglages()["pluralisme"]
    alertes = [f"{LIBELLES_ORIENTATION[o]} : {round(100 * n / total)} % des liens affichés"
               for o, n in liens.items() if n / total > cfg.get("alerte_part_max", 0.35) and o not in ("non-partisan",)]
    for b in ("gauche", "droite"):
        if bords[b] / total < cfg.get("alerte_part_min", 0.10):
            alertes.append(f"Sensibilités de {b} : seulement {round(100 * bords[b] / total)} % des liens affichés")
    return {
        "date": edition["date"], "liens": dict(liens), "bords": dict(bords), "total_liens": total,
        "diversite_moyenne": round(sum(s["diversite"] for s in sujets) / max(len(sujets), 1), 3),
        "part_couverture_partielle": round(sum(1 for s in sujets if len(s["bords"]) == 1) / max(len(sujets), 1), 3),
        "part_points_de_vue": round(sum(1 for s in sujets if s.get("points_de_vue") or (s.get("controverse") and s.get("par_bord"))) / max(len(sujets), 1), 3),
        "alertes": alertes,
    }


def publier() -> dict:
    travail = stockage.lire_json(TRAVAIL)
    if not travail or travail["mode"] == "preparation":
        log.info("Rien à publier (préparation)")
        return {}
    if not travail["sujets"]:
        log.warning("Aucun sujet (flux injoignables ?) : l'édition précédente est conservée")
        stockage.journaliser({"etape": "publication", "annulee": "aucun sujet"})
        return {}
    rattrapable = _rattrapage_possible()
    for s in travail["sujets"].values():
        if s.get("statut_ia") != "ia" and rattrapable and s.get("motif_ia") in _MOTIFS_RATTRAPABLES:
            s["statut_ia"] = "en_attente"
    statut, ia, total = _statut_edition(list(travail["sujets"].values()))
    maintenant = stockage.maintenant()
    edition = {
        "version": 1,
        "id": heure_paris(maintenant).strftime("%Y-%m-%dT%H%M"),
        "date": travail["date"],
        "genere_le": stockage.iso(maintenant),
        "declenchement": travail["declenchement"],
        "statut_ia": statut,
        "couverture_ia": {"ia": ia, "total": total},
        "essentiel": travail.get("essentiel"),
        "tops": travail["selection"]["tops"],
        "rubriques": travail["selection"]["rubriques"],
        "angles_morts": travail["selection"]["angles_morts"],
        "sujets": {sid: _public(s) for sid, s in travail["sujets"].items()},
        "stats": {"articles": travail["nb_articles"], "sujets_detectes": travail["nb_sujets"],
                  "medias_actifs": travail["medias_actifs"], "moteur": travail["moteur"],
                  "repartition_articles": travail["repartition_articles"], "ia": travail.get("ia_bilan", {})},
    }
    edition["pluralisme"] = _stats_pluralisme(edition)
    _ecrire_edition(edition)
    suivi.memoriser(list(travail["sujets"].values()), travail["date"])
    _ecrire_sources()
    stockage.journaliser({"etape": "publication", "edition": edition["id"], "statut_ia": statut,
                          "ia": ia, "total": total})
    return edition


def _ecrire_edition(edition: dict) -> None:
    stockage.ecrire_json("public/edition.json", edition, compact=True)
    stockage.ecrire_json(f"public/editions/{edition['date']}.json", edition, compact=True)
    index = [e for e in stockage.lire_json("public/index.json", []) if e["date"] != edition["date"]]
    index.insert(0, {"date": edition["date"], "id": edition["id"], "genere_le": edition["genere_le"],
                     "statut_ia": edition["statut_ia"], "couverture_ia": edition["couverture_ia"],
                     "audio": edition.get("audio")})
    jours = reglages().get("archives_jours", 365)
    limite = (heure_paris() - timedelta(days=jours)).date().isoformat()
    for e in index:
        if e["date"] < limite:
            p = stockage.chemin(f"public/editions/{e['date']}.json")
            if p.exists():
                p.unlink()
    index = sorted([e for e in index if e["date"] >= limite], key=lambda e: e["date"], reverse=True)
    stockage.ecrire_json("public/index.json", index)
    plur = [p for p in stockage.lire_json("public/pluralisme.json", []) if p["date"] != edition["date"]]
    plur.append(edition["pluralisme"])
    plur = sorted(plur, key=lambda p: p["date"])[-30:]
    stockage.ecrire_json("public/pluralisme.json", plur)


def _ecrire_sources() -> None:
    flux = stockage.lire_json("flux.json", {})
    seuil = reglages()["collecte"].get("alerte_echecs_consecutifs", 3)
    catalogue = []
    for s in sources():
        e = flux.get(s.id, {})
        catalogue.append({"id": s.id, "nom": s.nom, "pays": s.pays, "region": s.region, "nature": s.nature,
                          "orientation": s.orientation, "orientation_libelle": LIBELLES_ORIENTATION[s.orientation],
                          "payant": s.payant, "actif": s.actif, "flux": s.flux,
                          "dernier_succes": e.get("dernier_succes"), "echecs": e.get("echecs", 0),
                          "erreur": e.get("erreur"), "alerte": e.get("echecs", 0) >= seuil})
    articles = fenetre_articles(stockage.charger_articles())
    repartition = Counter(infos_source(a["source"])["orientation"] for a in articles)
    stockage.ecrire_json("public/sources.json", {
        "genere_le": stockage.iso(stockage.maintenant()),
        "orientations": [{"id": o, "libelle": LIBELLES_ORIENTATION[o]} for o in ORIENTATIONS],
        "rubriques": [{"id": r.id, "nom": r.nom} for r in rubriques()],
        "catalogue": catalogue,
        "repartition_articles": {o: repartition.get(o, 0) for o in ORIENTATIONS},
        "journal": stockage.lire_json("journal.json", [])[:30],
    })


# =================================================================== 4. rattrapage
def rattraper(force: bool = False) -> bool:
    """Relance l'IA sur les sujets de l'édition du jour restés sans IA. Renvoie True si l'édition a changé."""
    edition = stockage.lire_json("public/edition.json")
    if not edition or edition["date"] != heure_paris().date().isoformat():
        log.info("Pas d'édition du jour à compléter")
        return False
    # après l'heure limite, c'est le dernier essai : les sujets non rattrapés passent « Sans IA »
    dernier_passage = not force and not _rattrapage_possible()
    cibles = [s for s in edition["sujets"].values() if s.get("statut_ia") in ("en_attente", "sans_ia")
              and (force or s.get("motif_ia") in _MOTIFS_RATTRAPABLES)]
    if not cibles:
        return False
    ordre = {sid: k for k, sid in enumerate(edition["tops"]["france"] + edition["tops"]["international"]
                                            + [i for r in edition["rubriques"] for i in r["sujets"]]
                                            + edition["angles_morts"])}
    cibles.sort(key=lambda s: ordre.get(s["id"], 999))
    ids_tops = set(edition["tops"]["france"] + edition["tops"]["international"])
    redacteur = Redacteur(echeance=time.time() + 12 * 60)
    restants = redacteur.rediger([s for s in cibles if s["id"] in ids_tops], "tops")
    restants += redacteur.rediger([s for s in cibles if s["id"] not in ids_tops], "rubriques")
    for s in restants:
        motif = s.pop("_motif", redacteur.motif_absence())
        s["motif_ia"] = motif
        s["statut_ia"] = "sans_ia" if (dernier_passage or motif not in _MOTIFS_RATTRAPABLES) else "en_attente"
    rattrapes = len(cibles) - len(restants)
    ess = edition.get("essentiel") or {}
    if "france" not in ess:  # ancien format (un seul paragraphe) : on le remplace
        ess = {}
    for p in ("france", "international"):
        tops = [edition["sujets"][i] for i in edition["tops"][p][:5]]
        if (ess.get(p) or {}).get("statut_ia") != "ia" and all(s.get("statut_ia") == "ia" for s in tops):
            ess[p] = _essentiel(redacteur, tops)
        elif p not in ess:
            ess[p] = _essentiel(None, tops)
    edition["essentiel"] = ess
    statut, ia, total = _statut_edition(list(edition["sujets"].values()))
    edition["statut_ia"], edition["couverture_ia"] = statut, {"ia": ia, "total": total}
    edition["rattrape_le"] = stockage.iso(stockage.maintenant())
    _ecrire_edition(edition)
    stockage.journaliser({"etape": "rattrapage", "rattrapes": rattrapes, "restants": len(restants), **redacteur.bilan})
    log.info("Rattrapage : %s sujets complétés, %s restants", rattrapes, len(restants))
    return True


def sans_references(texte: str) -> str:
    return _REFS.sub("", texte or "").strip()
