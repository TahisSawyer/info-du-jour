"""Rédaction par IA (Mistral, Gemini en secours) avec charte de neutralité et contrôles automatiques.

- Les sujets sont envoyés par lots (5 par appel par défaut) pour économiser les requêtes.
- Chaque réponse est validée sujet par sujet ; un sujet refusé est redemandé seul, avec la liste
  des défauts constatés. Au second refus, il passe en mode sans IA (« Résumé IA non conforme »).
- Quota, panne ou délai dépassé : bascule sur le fournisseur suivant, puis mode sans IA.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass, field

import httpx
from pydantic import BaseModel, Field, ValidationError

from .config import reglages, termes_connotes
from .texte import contient_terme, hors_guillemets, normaliser_mots, phrases

log = logging.getLogger(__name__)

MOTIFS = {
    "quota": "Quota d'IA atteint",
    "indisponible": "Service d'IA indisponible",
    "non_conforme": "Résumé IA non conforme",
    "delai": "Délai de traitement dépassé",
    "desactivee": "IA désactivée",
    "sans_cle": "Aucune clé d'IA configurée",
}

CONSIGNE = """Tu es rédacteur dans une agence de presse. Tu rédiges en français des synthèses strictement
factuelles et neutres, à partir des seuls extraits d'articles fournis (titre et chapô).

Règles :
1. N'utilise que les faits présents dans les extraits. Aucune connaissance extérieure, aucune supposition,
   aucun pronostic. Traduis en français les extraits en langue étrangère.
2. Attribue toute affirmation contestée ou toute opinion à son auteur (« selon le gouvernement »,
   « d'après l'opposition », « estime X »). Un fait rapporté par une seule source est attribué à cette source
   (« selon Le Figaro ») et n'est jamais présenté comme établi.
3. Pas d'adjectifs évaluatifs ni de vocabulaire connoté. Les termes propres à un camp sont cités
   entre guillemets.
4. Chaque phrase du résumé se termine par les sources qui l'étayent entre crochets : [S1, S4].
5. Les extraits marqués « tribune » sont des opinions : ne les utilise jamais pour les faits du résumé,
   seulement pour les points de vue. Une « reprise de dépêche » n'est pas une confirmation indépendante.
6. Si les sources divergent sur les faits, l'interprétation ou les conséquences, ou si le sujet fait débat,
   mets "controverse": true et remplis "points_de_vue" : une entrée par position, résumée équitablement,
   de longueur comparable, avec ses sources. Chaque position s'appuie sur au moins une source de
   l'orientation qui la porte. N'arbitre jamais entre les positions.
7. Si toutes les sources viennent d'une seule sensibilité, indique-le dans "limites".
8. Si un "resume_precedent" est fourni, écris dans "evolution" en une ou deux phrases ce qui a changé
   depuis, sinon laisse "evolution" vide.
9. Titre : factuel, 12 mots au plus, sans point d'exclamation ni question.
10. Résumé : 3 à 5 phrases.

Réponds uniquement avec un objet JSON de la forme :
{"sujets": [{"id": "T1", "titre": "...", "resume": "... [S1, S2]", "controverse": false,
  "points_de_vue": [{"position": "...", "synthese": "...", "sources": ["S1"]}],
  "limites": "", "evolution": ""}]}"""

CONSIGNE_ESSENTIEL = """Tu es rédacteur dans une agence de presse. À partir des titres et résumés fournis,
rédige en français « L'essentiel du jour » : 4 à 6 phrases factuelles et neutres, une par sujet important,
dans l'ordre donné, sans adjectif évaluatif ni opinion, sans rien ajouter aux textes fournis.
Réponds uniquement avec un objet JSON : {"texte": "..."}"""


class PointDeVue(BaseModel):
    position: str = Field(min_length=2)
    synthese: str = Field(min_length=10)
    sources: list[str] = Field(default_factory=list)


class SortieSujet(BaseModel):
    id: str
    titre: str = Field(min_length=5)
    resume: str = Field(min_length=60)
    controverse: bool = False
    points_de_vue: list[PointDeVue] = Field(default_factory=list)
    limites: str = ""
    evolution: str = ""


_REFS = re.compile(r"\[(\s*S\d+(?:\s*[,;]\s*S\d+)*\s*)\]")


def valider(sortie: SortieSujet, sujet: dict) -> list[str]:
    """Contrôles automatiques de conformité. Renvoie la liste des défauts (vide si conforme)."""
    defauts = []
    cles = {s["cle"]: s for s in sujet["sources"]}
    if len(sortie.titre.split()) > 16:
        defauts.append("titre trop long (12 mots maximum)")
    morceaux = phrases(sortie.resume) or [sortie.resume]
    avec_ref = 0
    for p in morceaux:
        refs = _REFS.findall(p)
        if refs:
            avec_ref += 1
        for groupe in refs:
            for c in re.split(r"[,;]", groupe):
                if c.strip() not in cles:
                    defauts.append(f"source inexistante citée : {c.strip()}")
    if avec_ref < max(1, round(0.6 * len(morceaux))):
        defauts.append("chaque phrase du résumé doit citer ses sources entre crochets")
    if len(sortie.resume) > 1100:
        defauts.append("résumé trop long (5 phrases maximum)")
    bords_presents = {s["bord"] for s in sujet["sources"]}
    if sortie.controverse:
        if len(sortie.points_de_vue) < 2:
            defauts.append("controverse sans au moins deux points de vue")
        else:
            longueurs = [max(len(p.synthese.split()), 1) for p in sortie.points_de_vue]
            if max(longueurs) / min(longueurs) > 1.6:
                defauts.append("points de vue de longueurs trop inégales")
            bords_cites = set()
            for p in sortie.points_de_vue:
                if not p.sources:
                    defauts.append(f"point de vue « {p.position} » sans source")
                for c in p.sources:
                    if c.strip() not in cles:
                        defauts.append(f"source inexistante citée : {c}")
                    else:
                        bords_cites.add(cles[c.strip()]["bord"])
            if len(bords_presents) >= 2 and len(bords_cites) < 2:
                defauts.append("les points de vue doivent s'appuyer sur des sources d'orientations différentes")
    elif sujet.get("debat") and {"gauche", "droite"} <= bords_presents:
        defauts.append("sujet en débat : restituer les points de vue en présence (controverse: true)")
    texte = normaliser_mots(hors_guillemets(" ".join([sortie.titre, sortie.resume] + [p.synthese for p in sortie.points_de_vue])))
    for terme in termes_connotes():
        if contient_terme(texte, terme):
            defauts.append(f"terme connoté hors guillemets : « {terme} »")
    return defauts


def appliquer(sujet: dict, sortie: SortieSujet, fournisseur: str, modele: str) -> None:
    sujet["titre"] = sortie.titre.strip().rstrip(".")
    sujet["resume"] = sortie.resume.strip()
    sujet["controverse"] = sortie.controverse
    sujet["points_de_vue"] = [p.model_dump() for p in sortie.points_de_vue] if sortie.controverse else []
    sujet["limites"] = sortie.limites.strip()
    sujet["evolution"] = sortie.evolution.strip() if sujet.get("precedent") else ""
    sujet["statut_ia"] = "ia"
    sujet["motif_ia"] = ""
    sujet["ia_modele"] = f"{fournisseur} · {modele}"
    sujet.pop("par_bord", None)


def entree_ia(sujet: dict, cle_locale: str) -> dict:
    """Prépare l'entrée d'un sujet : au plus 2 articles par média et 4 par orientation."""
    par_media: dict[str, int] = {}
    par_orientation: dict[str, int] = {}
    extraits = []
    for s in sujet["sources"]:
        if par_media.get(s["media"], 0) >= 2 or par_orientation.get(s["orientation"], 0) >= 4:
            continue
        par_media[s["media"]] = par_media.get(s["media"], 0) + 1
        par_orientation[s["orientation"]] = par_orientation.get(s["orientation"], 0) + 1
        nature = "tribune" if s["opinion"] else ("reprise de dépêche" if s["reprise"] else "article")
        extraits.append({"cle": s["cle"], "media": s["media"], "orientation": s["orientation_libelle"],
                         "type": nature, "langue": s["langue"], "titre": s["titre"], "chapo": s["chapo"][:400]})
    entree = {"id": cle_locale, "sources": extraits}
    if sujet.get("precedent"):
        entree["resume_precedent"] = sujet["precedent"]["resume"][:500]
    return entree


@dataclass
class Fournisseur:
    nom: str
    url: str
    cle: str
    intervalle: float
    modeles: dict
    epuise: bool = False
    hors_service: bool = False
    dernier_appel: float = 0.0
    modeles_refuses: set = field(default_factory=set)
    appels: int = 0
    disponibles: list | None = None
    extra: dict = field(default_factory=dict)


class ErreurIA(Exception):
    def __init__(self, nature: str, detail: str = ""):
        super().__init__(detail)
        self.nature = nature


class Redacteur:
    def __init__(self, echeance: float | None = None):
        cfg = reglages()["ia"]
        self.actif = cfg.get("actif", True)
        self.taille_lot = cfg.get("taille_lot", 5)
        self.temperature = cfg.get("temperature", 0.2)
        self.echeance = echeance
        self.fournisseurs = []
        for f in cfg.get("fournisseurs", []):
            cle = os.environ.get(f["cle_env"], "").strip()
            if cle:
                self.fournisseurs.append(Fournisseur(f["nom"], f["url"], cle, f.get("intervalle_s", 2), f["modeles"],
                                                     extra=dict(f.get("parametres", {}) or {})))
        self.client = httpx.Client(timeout=120)
        self.bilan = {"appels": 0, "rejets": 0, "fournisseurs": {}}
        self.dernier_motif = "indisponible"

    # ---------------------------------------------------------------- appels
    def disponible(self) -> bool:
        return any(not f.epuise and not f.hors_service for f in self.fournisseurs)

    def motif_absence(self) -> str:
        if not self.actif:
            return MOTIFS["desactivee"]
        if not self.fournisseurs:
            return MOTIFS["sans_cle"]
        if self.echeance and time.time() > self.echeance:
            return MOTIFS["delai"]
        return MOTIFS.get(self.dernier_motif, MOTIFS["indisponible"])

    def _appeler(self, f: Fournisseur, modele: str, systeme: str, contenu: str) -> dict:
        attente = f.intervalle - (time.time() - f.dernier_appel)
        if attente > 0:
            time.sleep(attente)
        corps = {"model": modele, "temperature": self.temperature, "max_tokens": 6000,
                 "response_format": {"type": "json_object"}, **f.extra,
                 "messages": [{"role": "system", "content": systeme}, {"role": "user", "content": contenu}]}
        for essai in range(3):
            if self.echeance and time.time() > self.echeance:
                raise ErreurIA("delai")
            f.dernier_appel = time.time()
            try:
                r = self.client.post(f.url, json=corps, headers={"Authorization": f"Bearer {f.cle}"})
            except httpx.HTTPError as exc:
                log.warning("%s · %s : erreur réseau %s", f.nom, modele, exc)
                if essai >= 1:
                    raise ErreurIA("surcharge", str(exc))
                time.sleep(5)
                continue
            f.appels += 1
            self.bilan["appels"] += 1
            self.bilan["fournisseurs"][f.nom] = f.appels
            self._lire_quota(f, r.headers)
            if r.status_code == 429:
                attente = float(r.headers.get("retry-after", 0) or 0) or 20 * (essai + 1)
                if attente > 90 or essai == 2:
                    f.epuise = True
                    raise ErreurIA("quota", "429")
                time.sleep(attente)
                continue
            if r.status_code >= 400:
                log.warning("%s · %s : HTTP %s %s", f.nom, modele, r.status_code, r.text[:300].replace("\n", " "))
            if r.status_code in (401, 403):
                f.hors_service = True
                raise ErreurIA("indisponible", f"clé refusée ({r.status_code})")
            if r.status_code == 400 and f.extra and any(k in r.text for k in f.extra):
                # paramètre facultatif refusé par ce fournisseur : on le retire et on recommence
                for k in list(f.extra):
                    corps.pop(k, None)
                f.extra = {}
                continue
            if r.status_code in (400, 404, 422):
                texte = r.text[:300].lower()
                if "model" in texte or r.status_code == 404:
                    f.modeles_refuses.add(modele)
                    raise ErreurIA("modele", texte)
                raise ErreurIA("requete", texte)
            if r.status_code >= 500:
                if essai >= 1:  # modèle saturé : on passe au modèle suivant plutôt que d'attendre
                    raise ErreurIA("surcharge", f"HTTP {r.status_code}")
                time.sleep(5)
                continue
            try:
                contenu = r.json()["choices"][0]["message"]["content"]
                contenu = re.sub(r"^```(?:json)?|```$", "", contenu.strip()).strip()
                return json.loads(contenu)
            except (KeyError, IndexError, ValueError, TypeError) as exc:
                raise ErreurIA("format", str(exc))
        raise ErreurIA("indisponible", "trop d'erreurs")

    @staticmethod
    def _lire_quota(f: Fournisseur, entetes: httpx.Headers) -> None:
        for k, v in entetes.items():
            k = k.lower()
            if "ratelimit" in k and "remaining" in k and any(p in k for p in ("day", "month", "daily")):
                try:
                    if float(v) <= 0:
                        f.epuise = True
                except ValueError:
                    pass

    def _modeles_disponibles(self, f: Fournisseur) -> list[str]:
        """Liste les modèles accessibles avec la clé (point d'accès /models compatible OpenAI).
        Les noms de modèles changent souvent : on garde ceux de la configuration qui existent encore,
        et à défaut on prend automatiquement les modèles « flash » ou « small » les plus récents."""
        if f.disponibles is None:
            f.disponibles = []
            try:
                url = f.url.rsplit("/chat/completions", 1)[0] + "/models"
                r = self.client.get(url, headers={"Authorization": f"Bearer {f.cle}"}, timeout=30)
                if r.status_code == 200:
                    f.disponibles = [str(m.get("id", "")).split("/")[-1] for m in r.json().get("data", [])]
                    log.info("%s : %s modèles disponibles", f.nom, len(f.disponibles))
                else:
                    log.warning("%s : liste des modèles indisponible (HTTP %s) %s", f.nom, r.status_code, r.text[:200])
            except (httpx.HTTPError, ValueError) as exc:
                log.warning("%s : liste des modèles indisponible (%s)", f.nom, exc)
        return f.disponibles

    def _candidats(self, f: Fournisseur, niveau: str) -> list[str]:
        voulus = [m for m in f.modeles.get(niveau, []) if m not in f.modeles_refuses]
        dispo = self._modeles_disponibles(f)
        if not dispo:
            return voulus
        gardes = [m for m in voulus if m in dispo]
        if gardes:
            return gardes
        exclus = ("image", "tts", "live", "audio", "embed", "vision", "imagen", "veo", "omni", "robotics",
                  "computer", "preview", "exp", "thinking", "translate", "ocr", "moderation", "codestral")
        auto = [m for m in dispo if any(k in m for k in ("flash", "small", "medium"))
                and not any(k in m for k in exclus) and m not in f.modeles_refuses]

        def cle_tri(m: str):
            nombres = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", m)] or [0.0]
            leger = "lite" in m or "small" in m
            return (leger if niveau == "tops" else not leger, -nombres[0])

        auto.sort(key=cle_tri)
        if auto:
            log.info("%s : modèles configurés absents, choix automatique : %s", f.nom, auto[:3])
        return auto[:3]

    def demander(self, niveau: str, systeme: str, contenu: str) -> tuple[dict, str, str]:
        """Essaie chaque fournisseur et chaque modèle autorisé ; lève ErreurIA si tous échouent."""
        derniere = ErreurIA("indisponible")
        for f in self.fournisseurs:
            if f.epuise or f.hors_service:
                continue
            for modele in self._candidats(f, niveau):
                if modele in f.modeles_refuses:
                    continue
                try:
                    return self._appeler(f, modele, systeme, contenu), f.nom, modele
                except ErreurIA as e:
                    derniere = e
                    if e.nature == "modele":
                        continue
                    if e.nature in ("format", "requete", "surcharge"):
                        continue
                    if e.nature == "delai":
                        self.dernier_motif = "delai"
                        raise
                    break  # quota ou panne : fournisseur suivant
        self.dernier_motif = {"quota": "quota", "delai": "delai"}.get(derniere.nature, "indisponible")
        raise derniere

    # ---------------------------------------------------------------- rédaction
    def rediger(self, sujets: list[dict], niveau: str) -> list[dict]:
        """Rédige une liste de sujets (déjà dans l'ordre de priorité). Renvoie les sujets non traités."""
        restants = list(sujets)
        refus: dict[str, list[str]] = {}
        non_traites: list[dict] = []
        while restants:
            if not self.actif or not self.disponible() or (self.echeance and time.time() > self.echeance):
                non_traites.extend(restants)
                break
            lot = restants[: self.taille_lot]
            # un sujet déjà refusé une fois est redemandé seul avec ses défauts
            if lot[0]["id"] in refus:
                lot = lot[:1]
            restants = restants[len(lot):]
            locales = {f"T{k}": s for k, s in enumerate(lot, 1)}
            entree = {"sujets": [entree_ia(s, c) for c, s in locales.items()]}
            message = json.dumps(entree, ensure_ascii=False)
            if len(lot) == 1 and lot[0]["id"] in refus:
                message += "\n\nTa réponse précédente pour ce sujet a été refusée. Corrige : " + "; ".join(refus[lot[0]["id"]])
            try:
                reponse, fournisseur, modele = self.demander(niveau, CONSIGNE, message)
            except ErreurIA as e:
                if e.nature == "delai":
                    non_traites.extend(lot + restants)
                    break
                non_traites.extend(lot)
                continue
            except Exception as exc:  # garde-fou : une anomalie imprévue ne doit jamais bloquer l'édition
                log.warning("Erreur inattendue pendant la rédaction : %s", exc)
                non_traites.extend(lot)
                continue
            if isinstance(reponse, list):  # certains modèles renvoient directement la liste des sujets
                reponse = {"sujets": reponse}
            elif not isinstance(reponse, dict):
                reponse = {}
            recus = {}
            for brut in (reponse.get("sujets") or []):
                if not isinstance(brut, dict):
                    continue
                try:
                    sortie = SortieSujet.model_validate(brut)
                    recus[sortie.id] = sortie
                except ValidationError:
                    continue
            for cle_locale, sujet in locales.items():
                sortie = recus.get(cle_locale)
                defauts = valider(sortie, sujet) if sortie else ["sujet absent ou JSON invalide"]
                if not defauts:
                    appliquer(sujet, sortie, fournisseur, modele)
                    continue
                self.bilan["rejets"] += 1
                log.info("Résumé refusé (%s) : %s", sujet["titre"][:60] if sujet.get("titre") else sujet["id"], "; ".join(defauts[:4]))
                if sujet["id"] in refus:  # second refus
                    sujet["_motif"] = MOTIFS["non_conforme"]
                    non_traites.append(sujet)
                else:
                    refus[sujet["id"]] = defauts[:6]
                    restants.insert(0, sujet)
        for s in non_traites:
            s.setdefault("_motif", self.motif_absence())
        return non_traites

    def essentiel(self, sujets: list[dict]) -> str | None:
        if not sujets or not self.actif or not self.disponible():
            return None
        entree = [{"titre": s["titre"], "resume": re.sub(_REFS, "", s["resume"]).strip()} for s in sujets]
        try:
            reponse, _, _ = self.demander("tops", CONSIGNE_ESSENTIEL, json.dumps(entree, ensure_ascii=False))
        except ErreurIA:
            return None
        if isinstance(reponse, list):
            reponse = reponse[0] if reponse and isinstance(reponse[0], dict) else {"texte": " ".join(map(str, reponse))}
        texte = str(reponse.get("texte", "") if isinstance(reponse, dict) else reponse).strip()
        normal = normaliser_mots(hors_guillemets(texte))
        if len(texte) < 80 or any(contient_terme(normal, t) for t in termes_connotes()):
            return None
        return texte
