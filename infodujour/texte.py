"""Outils de traitement du texte : nettoyage, URL canonique, détection des opinions et accroches."""
from __future__ import annotations

import hashlib
import html
import re
import unicodedata
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

_BALISES = re.compile(r"<[^>]+>")
_ESPACES = re.compile(r"\s+")
_PARAMS_PISTAGE = re.compile(r"^(utm_|fbclid|gclid|xtor|at_|ito|cmp|mc_|ns_|ref|origin|from|cid|sref|smid|traffic_source)", re.I)

# Rubriques d'opinion repérées dans l'adresse ou dans les catégories du flux
_MOTIFS_OPINION_URL = re.compile(
    r"/(opinions?|tribunes?|editorials?|editos?|chroniques?|idees|debats|points-de-vue|point-de-vue|"
    r"commentisfree|op-?eds?|columns?|columnists?|blogs?|analyses?-et-opinions)(/|-|$)",
    re.I,
)
_MOTIFS_OPINION_CAT = re.compile(
    r"\b(opinion|opinions|tribune|tribunes|editorial|éditorial|edito|édito|chronique|chroniques|idées|"
    r"débats|point de vue|commentary|comment is free|op-ed|column)\b",
    re.I,
)
_MOTIFS_OPINION_TITRE = re.compile(
    r"^\s*(tribune|édito|edito|éditorial|editorial|chronique|opinion|point de vue|l'édito|"
    r"la chronique)\s*[:|\-–—]",
    re.I,
)
_MOTIFS_ACCROCHE = re.compile(
    r"\b(découvrez|decouvrez|cliquez|abonnez-vous|inscrivez-vous|lire aussi|à lire|a lire|en images|"
    r"notre sélection|vidéo\s*:|podcast|newsletter|quiz|bons plans|code promo|sign up|subscribe|"
    r"click here|watch:|listen:)\b",
    re.I,
)
_PHRASES = re.compile(r"(?<=[.!?…])\s+(?=[A-ZÀ-ÖØ-Þ«\"“0-9])")


def nettoyer(texte: str | None) -> str:
    if not texte:
        return ""
    texte = html.unescape(_BALISES.sub(" ", texte))
    texte = texte.replace("\xa0", " ").replace("​", "")
    return _ESPACES.sub(" ", texte).strip()


def sans_accents(texte: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texte) if unicodedata.category(c) != "Mn")


def normaliser_mots(texte: str) -> str:
    return sans_accents(texte.lower())


def url_canonique(url: str) -> str:
    try:
        p = urlparse(url.strip())
    except ValueError:
        return url.strip()
    params = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=False) if not _PARAMS_PISTAGE.match(k)]
    hote = (p.hostname or "").lower()
    if hote.startswith("www."):
        hote = hote[4:]
    chemin = p.path.rstrip("/") or "/"
    return urlunparse(("https", hote, chemin, "", urlencode(params), ""))


def empreinte(texte: str, longueur: int = 16) -> str:
    return hashlib.sha1(texte.encode("utf-8")).hexdigest()[:longueur]


def est_opinion(url: str, categories: list[str], titre: str) -> bool:
    if _MOTIFS_OPINION_URL.search(urlparse(url).path or ""):
        return True
    if any(_MOTIFS_OPINION_CAT.search(c or "") for c in categories):
        return True
    return bool(_MOTIFS_OPINION_TITRE.match(titre or ""))


def est_accroche(chapo: str) -> bool:
    """Chapô sans information factuelle (accroche, promotion, trop court)."""
    if len(chapo) < 50:
        return True
    return bool(_MOTIFS_ACCROCHE.search(chapo[:160]))


def phrases(texte: str) -> list[str]:
    return [p.strip() for p in _PHRASES.split(texte) if len(p.strip()) > 25]


def tronquer(texte: str, n: int) -> str:
    if len(texte) <= n:
        return texte
    coupe = texte[:n].rsplit(" ", 1)[0]
    return coupe.rstrip(",;:") + "…"


def contient_terme(texte_normalise: str, terme: str) -> bool:
    terme = normaliser_mots(terme)
    return re.search(r"(?<![\w-])" + re.escape(terme) + r"(?![\w-])", texte_normalise) is not None


def hors_guillemets(texte: str) -> str:
    """Retire les passages entre guillemets (citations) avant de chercher des termes connotés."""
    return re.sub(r"«[^»]*»|“[^”]*”|\"[^\"]*\"", " ", texte)


MOTS_VIDES = set(
    """
    a au aux avec ce ces dans de des du elle en et eux il ils je la le les leur lui ma mais me meme mes moi mon ne nos
    notre nous on ou par pas pour qu que qui sa se ses son sur ta te tes toi ton tu un une vos votre vous c d j l m n s t y
    ete etre avoir fait plus apres avant selon contre entre sans sous chez depuis lors alors aussi tres tout tous toute
    toutes cette cet comme dont si ont est sont sera seront a-t-il va vont deux trois an ans jour jours hier aujourd hui
    demain mardi lundi mercredi jeudi vendredi samedi dimanche the of and to in for on with at by from as is are was were
    be been has have had it its this that these those an or but not will would could should after before over new says
    said his her their they he she we you than into about up out more most video live direct
    """.split()
)
