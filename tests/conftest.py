import json
import os
import shutil
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))


@pytest.fixture()
def etat(tmp_path, monkeypatch):
    """Dossier d'état isolé + moteur TF-IDF (pas de téléchargement de modèle pendant les tests)."""
    from infodujour import config, stockage

    monkeypatch.setattr(config, "DOSSIER_ETAT", tmp_path)
    monkeypatch.setattr(stockage, "DOSSIER_ETAT", tmp_path)
    config.reglages.cache_clear()
    reg = config.reglages()
    reg["regroupement"]["moteur"] = "tfidf"
    yield tmp_path
    config.reglages.cache_clear()


def fausse_ia(requete_json: dict, bords_par_cle=None) -> dict:
    """Simule une IA conforme : résumé sourcé, points de vue équilibrés si plusieurs bords."""
    contenu = requete_json["messages"][1]["content"].split("\n\nTa réponse précédente")[0]
    donnees = json.loads(contenu)
    if isinstance(donnees, list):  # essentiel
        return {"texte": " ".join(f"{d['titre']}." for d in donnees) + " Les détails figurent dans chaque sujet de l'édition."}
    sortie = []
    for s in donnees["sujets"]:
        src = s["sources"]
        cles = [x["cle"] for x in src]
        titre = src[0]["titre"].replace("Exemple : ", "").replace("Example: ", "")[:80]
        resume = (f"Selon les médias, {titre.lower()} [{cles[0]}]. "
                  f"Plusieurs sources rapportent les mêmes faits [{', '.join(cles[:2])}]. "
                  f"Le détail figure dans les articles cités [{cles[-1]}].")
        orient = {x["cle"]: x["orientation"] for x in src}
        gauche = [c for c in cles if orient[c] in ("Gauche", "Centre-gauche")]
        droite = [c for c in cles if orient[c] in ("Droite", "Centre-droit")]
        pdv = []
        if gauche and droite:
            pdv = [{"position": "Première position", "synthese": "Les partisans de cette position avancent un premier argument factuel rapporté.", "sources": gauche[:1]},
                   {"position": "Seconde position", "synthese": "Les tenants de l'autre position avancent un second argument factuel rapporté.", "sources": droite[:1]}]
        sortie.append({"id": s["id"], "titre": titre, "resume": resume, "controverse": bool(pdv),
                       "points_de_vue": pdv, "limites": "", "evolution": ""})
    return {"sujets": sortie}
