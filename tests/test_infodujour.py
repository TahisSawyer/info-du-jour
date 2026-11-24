import json
import subprocess
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
import pytest

from conftest import RACINE, fausse_ia

PARIS = ZoneInfo("Europe/Paris")


# ------------------------------------------------------------------ texte
def test_url_canonique_retire_le_pistage():
    from infodujour.texte import url_canonique

    assert url_canonique("http://www.lemonde.fr/a/b/?utm_source=x&id=3#top") == "https://lemonde.fr/a/b?id=3"


@pytest.mark.parametrize("url,titre,attendu", [
    ("https://www.lefigaro.fr/vox/politique/tribune-xyz", "Tribune : il faut agir", True),
    ("https://www.liberation.fr/idees-et-debats/opinions/xyz", "Un texte", True),
    ("https://www.theguardian.com/commentisfree/2026/nov/14/x", "A view", True),
    ("https://www.lemonde.fr/politique/article/2026/11/14/comment-le-budget-a-ete-vote", "Comment le budget a été voté", False),
    ("https://www.francetvinfo.fr/economie/greve.html", "Grève jeudi", False),
])
def test_detection_opinion(url, titre, attendu):
    from infodujour.texte import est_opinion

    assert est_opinion(url, [], titre) is attendu


def test_accroche():
    from infodujour.texte import est_accroche

    assert est_accroche("Découvrez notre sélection des meilleurs films de la semaine à voir absolument.")
    assert not est_accroche("Les députés ont adopté mardi le projet de loi de finances par 300 voix contre 250.")


# ------------------------------------------------------------------ configuration
def test_catalogue_equilibre():
    from infodujour.config import sources

    fr = [s for s in sources() if s.region == "france"]
    for o in ("gauche", "centre-gauche", "centre", "centre-droit", "droite"):
        assert sum(1 for s in fr if s.orientation == o) >= 2, o
    inter = [s for s in sources() if s.region != "france"]
    assert sum(1 for s in inter if s.bord == "gauche") >= 2
    assert sum(1 for s in inter if s.bord == "droite") >= 2
    regions = {s.region for s in inter}
    assert {"afrique", "asie", "amerique-latine", "moyen-orient"} <= regions


# ------------------------------------------------------------------ chaîne complète sans IA
def _pipeline(etat):
    sys.argv = ["demo"]
    subprocess.run([sys.executable, str(RACINE / "outils" / "demo.py")], check=True,
                   env={**__import__("os").environ, "INFODUJOUR_ETAT": str(etat)})
    from infodujour import edition

    edition.regrouper_et_classer("edition", "planifie")
    edition.rediger()
    return edition.publier()


def test_edition_sans_ia(etat, monkeypatch):
    for v in ("MISTRAL_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.delenv(v, raising=False)
    e = _pipeline(etat)
    assert e["statut_ia"] == "aucun"
    assert e["tops"]["france"] and e["tops"]["international"]
    s = e["sujets"][e["tops"]["france"][0]]
    assert s["statut_ia"] == "sans_ia" and s["motif_ia"] == "Aucune clé d'IA configurée"
    assert s["resume"] and s["titre"] and "par_bord" in s
    assert (etat / "public" / "index.json").exists()
    assert (etat / "public" / "sources.json").exists()


def _brancher_fausse_ia(monkeypatch, comportement=None):
    from infodujour import ia

    appels = []

    def gestion(requete: httpx.Request):
        corps = json.loads(requete.content)
        appels.append((str(requete.url), corps["model"]))
        if comportement:
            r = comportement(requete, corps, len(appels))
            if r is not None:
                return r
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(fausse_ia(corps))}}]})

    original = ia.Redacteur.__init__

    def init(self, *a, **k):
        original(self, *a, **k)
        self.client = httpx.Client(transport=httpx.MockTransport(gestion))
        for f in self.fournisseurs:
            f.intervalle = 0

    monkeypatch.setattr(ia.Redacteur, "__init__", init)
    return appels


def test_edition_avec_ia_par_lots(etat, monkeypatch):
    monkeypatch.setenv("MISTRAL_API_KEY", "test")
    monkeypatch.setenv("GEMINI_API_KEY", "test")
    appels = _brancher_fausse_ia(monkeypatch)
    e = _pipeline(etat)
    total = e["couverture_ia"]["total"]
    assert e["statut_ia"] == "complet", [(s["titre"], s.get("motif_ia")) for s in e["sujets"].values()]
    # 5 sujets par appel : beaucoup moins d'appels que de sujets (+1 pour l'essentiel)
    assert len(appels) <= -(-total // 5) + 3  # + 2 appels pour l'essentiel (France, International)
    for p in ("france", "international"):
        assert e["essentiel"][p]["statut_ia"] == "ia"
        assert len(e["essentiel"][p]["points"]) == len(e["tops"][p][:5])
    assert any(s["points_de_vue"] for s in e["sujets"].values())


def test_quota_bascule_sur_gemini_puis_sans_ia(etat, monkeypatch):
    monkeypatch.setenv("MISTRAL_API_KEY", "test")
    monkeypatch.setenv("GEMINI_API_KEY", "test")
    monkeypatch.setattr("time.sleep", lambda s: None)

    def comportement(requete, corps, n):
        if "mistral" in str(requete.url):
            return httpx.Response(429, headers={"retry-after": "120"})
        if n > 3:  # Gemini répond deux fois puis atteint son quota
            return httpx.Response(429, headers={"retry-after": "120"})
        return None

    _brancher_fausse_ia(monkeypatch, comportement)
    e = _pipeline(etat)
    assert e["statut_ia"] == "partiel"
    motifs = {s["motif_ia"] for s in e["sujets"].values() if s["statut_ia"] != "ia"}
    assert motifs == {"Quota d'IA atteint"}
    # les Tops France passent en premier : le n°1 France doit être rédigé par l'IA
    assert e["sujets"][e["tops"]["france"][0]]["statut_ia"] == "ia"


def test_reponse_non_conforme_redemandee_puis_refusee(etat, monkeypatch):
    monkeypatch.setenv("MISTRAL_API_KEY", "test")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    def comportement(requete, corps, n):
        donnees = fausse_ia(corps)
        if "sujets" in donnees:
            for s in donnees["sujets"]:
                s["resume"] = "Une décision scandaleuse a été prise hier sans aucune source citée ici."
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(donnees)}}]})

    _brancher_fausse_ia(monkeypatch, comportement)
    e = _pipeline(etat)
    assert all(s["motif_ia"] == "Résumé IA non conforme" for s in e["sujets"].values())


def test_rattrapage(etat, monkeypatch):
    monkeypatch.setenv("MISTRAL_API_KEY", "test")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr("time.sleep", lambda s: None)
    panne = {"active": True}

    def comportement(requete, corps, n):
        return httpx.Response(503) if panne["active"] else None

    _brancher_fausse_ia(monkeypatch, comportement)
    e = _pipeline(etat)
    assert e["statut_ia"] == "aucun"
    from infodujour import edition

    panne["active"] = False
    assert edition.rattraper(force=True)
    e2 = json.loads((etat / "public" / "edition.json").read_text())
    assert e2["statut_ia"] == "complet"
    assert "rattrape_le" in e2


# ------------------------------------------------------------------ validation
def test_validation_points_de_vue_desequilibres():
    from infodujour.ia import SortieSujet, valider

    sujet = {"sources": [{"cle": "S1", "bord": "gauche"}, {"cle": "S2", "bord": "droite"}], "debat": True}
    sortie = SortieSujet(id="T1", titre="Un titre factuel", resume="Phrase un sourcée ici [S1]. Phrase deux sourcée là [S2]. Fin du résumé de test [S1].",
                         controverse=True, points_de_vue=[
                             {"position": "Partisans", "synthese": "Court argument rapporté ici.", "sources": ["S1"]},
                             {"position": "Opposants", "synthese": " ".join(["Argument très long"] * 20), "sources": ["S2"]}])
    defauts = valider(sortie, sujet)
    assert any("inégales" in d for d in defauts)


def test_validation_source_inventee():
    from infodujour.ia import SortieSujet, valider

    sujet = {"sources": [{"cle": "S1", "bord": "centre"}]}
    sortie = SortieSujet(id="T1", titre="Un titre factuel", resume="Phrase sourcée inventée [S9]. Seconde phrase sourcée correcte [S1].")
    assert any("inexistante" in d for d in valider(sortie, sujet))


# ------------------------------------------------------------------ planification
@pytest.mark.parametrize("heure,attendu", [
    ((9, 7), {"collecte": True, "regroupement": False}),
    ((15, 7), {"collecte": True, "mode": "preparation"}),
    ((17, 37), {"collecte": True, "mode": "edition", "publication": True}),
    ((23, 7), {"collecte": False, "regroupement": False}),
])
def test_planification(etat, heure, attendu):
    from infodujour.planif import decider

    now = datetime(2026, 11, 16, *heure, tzinfo=PARIS)
    d = decider("schedule", maintenant=now)
    for k, v in attendu.items():
        assert d[k] == v, (heure, d)


def test_planification_heure_ete(etat):
    from infodujour.planif import decider

    d = decider("schedule", maintenant=datetime(2026, 7, 6, 17, 40, tzinfo=PARIS))
    assert d["mode"] == "edition"


def test_rafraichissement_trop_rapproche(etat):
    from infodujour import stockage
    from infodujour.planif import decider

    stockage.ecrire_json("public/edition.json", {"date": "2026-11-16", "genere_le": stockage.iso(stockage.maintenant())})
    assert not decider("workflow_dispatch", "edition")["regroupement"]
    assert decider("workflow_dispatch", "edition", forcer=True)["regroupement"]


def test_preparation_puis_reutilisation(etat, monkeypatch):
    """Les résumés préparés l'après-midi sont réutilisés à 18 h, même si l'IA est alors indisponible."""
    monkeypatch.setenv("MISTRAL_API_KEY", "test")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr("time.sleep", lambda s: None)
    panne = {"active": False}
    _brancher_fausse_ia(monkeypatch, lambda req, corps, n: httpx.Response(503) if panne["active"] else None)
    subprocess.run([sys.executable, str(RACINE / "outils" / "demo.py")], check=True,
                   env={**__import__("os").environ, "INFODUJOUR_ETAT": str(etat)})
    from infodujour import edition

    edition.regrouper_et_classer("preparation", "planifie")
    t = edition.rediger()
    assert t["ia_bilan"]["rediges"] > 0
    assert edition.publier() == {}  # une préparation ne publie rien
    panne["active"] = True
    edition.regrouper_et_classer("edition", "planifie")
    t = edition.rediger()
    assert t["ia_bilan"]["reutilises"] > 0
    e = edition.publier()
    tops = e["tops"]["france"] + e["tops"]["international"]
    assert all(e["sujets"][i]["statut_ia"] == "ia" for i in tops)


def test_choix_automatique_des_modeles(monkeypatch):
    """Si les modèles configurés n'existent plus, les plus récents « flash » sont choisis automatiquement."""
    from infodujour import ia

    monkeypatch.setenv("GEMINI_API_KEY", "test")
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    r = ia.Redacteur()
    liste = {"data": [{"id": "models/gemini-3.6-flash"}, {"id": "models/gemini-3.5-flash-lite"},
                      {"id": "models/gemini-3.1-flash-image"}, {"id": "models/gemini-embedding-2"}]}
    r.client = httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(200, json=liste)))
    f = r.fournisseurs[0]
    f.modeles = {"tops": ["gemini-2.5-flash"], "rubriques": ["gemini-2.5-flash-lite"]}
    assert r._candidats(f, "tops")[0] == "gemini-3.6-flash"
    assert r._candidats(f, "rubriques")[0] == "gemini-3.5-flash-lite"
    assert all("image" not in m and "embedding" not in m for m in r._candidats(f, "tops"))


def test_reponse_sous_forme_de_liste(etat, monkeypatch):
    """Un modèle qui renvoie la liste des sujets sans l'objet englobant ne doit pas faire échouer l'édition."""
    monkeypatch.setenv("MISTRAL_API_KEY", "test")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    def comportement(requete, corps, n):
        donnees = fausse_ia(corps)
        contenu = donnees["sujets"] if "sujets" in donnees else [donnees]
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(contenu)}}]})

    _brancher_fausse_ia(monkeypatch, comportement)
    e = _pipeline(etat)
    assert e["statut_ia"] == "complet"


def test_sources_dans_une_seule_chaine():
    from infodujour.ia import SortieSujet, valider

    sujet = {"sources": [{"cle": "S1", "bord": "gauche"}, {"cle": "S2", "bord": "droite"}, {"cle": "S3", "bord": "centre"}]}
    sortie = SortieSujet(id="T1", titre="Un titre factuel", resume="Phrase un sourcée ici [S1, S2]. Phrase deux sourcée là [S3].",
                         controverse=True, points_de_vue=[
                             {"position": "Partisans", "synthese": "Argument rapporté par les uns ici.", "sources": ["S1, S3"]},
                             {"position": "Opposants", "synthese": "Argument rapporté par les autres là.", "sources": "S2"}])
    assert valider(sortie, sujet) == []


def test_debat_non_signale_accepte_avec_colonnes(etat):
    from infodujour.ia import SortieSujet, appliquer, valider

    sources = [{"cle": "S1", "bord": "gauche", "media": "A", "titre": "t", "chapo": "c", "url": "u", "opinion": False},
               {"cle": "S2", "bord": "droite", "media": "B", "titre": "t", "chapo": "c", "url": "u", "opinion": False}]
    sujet = {"id": "x", "sources": sources, "debat": True}
    sortie = SortieSujet(id="T1", titre="Un titre factuel", resume="Première phrase factuelle et sourcée ici [S1]. Seconde phrase factuelle et sourcée là [S2].")
    assert valider(sortie, sujet) == []
    appliquer(sujet, sortie, "Test", "m")
    assert sujet["statut_ia"] == "ia" and sujet["par_bord"]["gauche"] and sujet["par_bord"]["droite"]


def test_openrouter_uniquement_modeles_gratuits(monkeypatch):
    from infodujour import ia

    monkeypatch.setenv("OPENROUTER_API_KEY", "test")
    for v in ("GEMINI_API_KEY", "MISTRAL_API_KEY", "GROQ_API_KEY"):
        monkeypatch.delenv(v, raising=False)
    r = ia.Redacteur()
    liste = {"data": [{"id": "openai/gpt-5"}, {"id": "meta-llama/llama-3.3-70b-instruct:free"},
                      {"id": "qwen/qwen3-8b:free"}, {"id": "google/gemma-3-27b-it:free"}]}
    r.client = httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(200, json=liste)))
    f = r.fournisseurs[0]
    assert f.nom == "OpenRouter"
    f.modeles = {"tops": ["openai/gpt-5", "un-modele-disparu:free"], "rubriques": []}
    candidats = r._candidats(f, "tops")
    assert candidats and all(m.endswith(":free") for m in candidats)
    assert candidats[0] == "meta-llama/llama-3.3-70b-instruct:free"


def test_groq_identifiants_complets(monkeypatch):
    from infodujour import ia

    monkeypatch.setenv("GROQ_API_KEY", "test")
    for v in ("GEMINI_API_KEY", "MISTRAL_API_KEY", "OPENROUTER_API_KEY"):
        monkeypatch.delenv(v, raising=False)
    r = ia.Redacteur()
    liste = {"data": [{"id": "openai/gpt-oss-120b"}, {"id": "llama-3.3-70b-versatile"}]}
    r.client = httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(200, json=liste)))
    assert r._candidats(r.fournisseurs[0], "tops")[:2] == ["openai/gpt-oss-120b", "llama-3.3-70b-versatile"]


def test_rattrapage_avec_sujet_suivi_publie(etat, monkeypatch):
    """Régression du 23/11 : dans l'édition publiée, « precedent » n'a plus de résumé ; le rattrapage ne doit pas planter."""
    monkeypatch.setenv("MISTRAL_API_KEY", "test")
    for v in ("GEMINI_API_KEY", "GROQ_API_KEY", "OPENROUTER_API_KEY"):
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setattr("time.sleep", lambda s: None)
    panne = {"active": True}
    _brancher_fausse_ia(monkeypatch, lambda req, corps, n: httpx.Response(503) if panne["active"] else None)
    _pipeline(etat)
    e = json.loads((etat / "public" / "edition.json").read_text())
    for s in e["sujets"].values():
        s["suivi"], s["precedent"] = "suite", {"date": "2026-11-22", "titre": "Hier"}
    (etat / "public" / "edition.json").write_text(json.dumps(e))
    from infodujour import edition

    panne["active"] = False
    assert edition.rattraper(force=True)
    e2 = json.loads((etat / "public" / "edition.json").read_text())
    assert e2["statut_ia"] == "complet"
