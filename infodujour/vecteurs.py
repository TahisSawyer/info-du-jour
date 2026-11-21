"""Vectorisation sémantique des articles.

Deux moteurs :
- « fastembed » : petit modèle multilingue au format ONNX (léger, sans PyTorch), qui rapproche
  des articles de langues différentes. Les vecteurs sont mis en cache d'une exécution à l'autre.
- « tfidf » : repli sans modèle, fondé sur les mots partagés (moins précis, monolingue).
"""
from __future__ import annotations

import logging

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer

from . import stockage
from .config import reglages
from .texte import MOTS_VIDES

log = logging.getLogger(__name__)


def texte_article(a: dict) -> str:
    return f"{a['titre']}. {a['chapo'] if not a.get('accroche') else ''}".strip()


def moteur_disponible() -> str:
    choix = reglages()["regroupement"].get("moteur", "auto")
    if choix == "tfidf":
        return "tfidf"
    try:
        import fastembed  # noqa: F401
        return "fastembed"
    except ImportError:
        if choix == "fastembed":
            log.warning("fastembed n'est pas installé : repli sur TF-IDF")
        return "tfidf"


def _normaliser(m: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(m, axis=1, keepdims=True)
    n[n == 0] = 1
    return m / n


def tfidf(textes: list[str]) -> np.ndarray:
    vec = TfidfVectorizer(strip_accents="unicode", lowercase=True, sublinear_tf=True, ngram_range=(1, 2),
                          min_df=1, max_df=0.5, stop_words=list(MOTS_VIDES), token_pattern=r"(?u)\b\w[\w'-]+\b")
    try:
        m = vec.fit_transform(textes).toarray().astype(np.float32)
    except ValueError:  # vocabulaire vide
        m = np.zeros((len(textes), 1), dtype=np.float32)
    return _normaliser(m)


def vectoriser(articles: list[dict]) -> tuple[np.ndarray, str]:
    moteur = moteur_disponible()
    textes = [texte_article(a) for a in articles]
    if moteur == "tfidf":
        return tfidf(textes), moteur
    try:
        from fastembed import TextEmbedding

        cache = stockage.charger_vecteurs()
        manquants = [i for i, a in enumerate(articles) if a["id"] not in cache]
        if manquants:
            modele = TextEmbedding(model_name=reglages()["regroupement"]["modele"])
            nouveaux = list(modele.embed([textes[i] for i in manquants], batch_size=64))
            for i, v in zip(manquants, nouveaux):
                cache[articles[i]["id"]] = np.asarray(v, dtype=np.float32)
        m = np.stack([np.asarray(cache[a["id"]], dtype=np.float32) for a in articles])
        stockage.enregistrer_vecteurs(cache, {a["id"] for a in stockage.charger_articles().values()} | {a["id"] for a in articles})
        log.info("Vecteurs : %s calculés, %s repris du cache", len(manquants), len(articles) - len(manquants))
        return _normaliser(m), moteur
    except Exception as exc:  # modèle indisponible (réseau, mémoire…) : on ne bloque pas l'édition
        log.warning("fastembed indisponible (%s) : repli sur TF-IDF", exc)
        return tfidf(textes), "tfidf"


def precalculer(articles: list[dict]) -> int:
    """Appelé après chaque collecte : calcule à l'avance les vecteurs des nouveaux articles."""
    if moteur_disponible() != "fastembed" or not articles:
        return 0
    avant = len(stockage.charger_vecteurs())
    vectoriser(articles)
    return len(stockage.charger_vecteurs()) - avant
