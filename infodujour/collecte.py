"""Collecte des articles : flux RSS du catalogue (socle) et API d'actualités (compléments facultatifs)."""
from __future__ import annotations

import asyncio
import calendar
import logging
import os
from datetime import datetime, timedelta, timezone

import feedparser
import httpx

from . import stockage
from .config import Source, config_api, reglages, source_par_domaine, sources
from .texte import empreinte, est_accroche, est_opinion, nettoyer, tronquer, url_canonique

log = logging.getLogger(__name__)
AGENT = "InfoDuJour/1.0 (lecteur de flux personnel; +https://github.com)"


def _date_entree(e) -> datetime | None:
    for cle in ("published_parsed", "updated_parsed", "created_parsed"):
        t = e.get(cle)
        if t:
            try:
                return datetime.fromtimestamp(calendar.timegm(t), tz=timezone.utc)
            except (OverflowError, ValueError):
                continue
    return None


def fabriquer_article(src: Source, url: str, titre: str, chapo: str, publie: datetime | None,
                      categories: list[str], via: str = "rss") -> dict | None:
    titre = nettoyer(titre)
    chapo = nettoyer(chapo)
    if not url or not titre:
        return None
    if chapo.lower().startswith(titre.lower()[:40]):
        chapo = chapo[len(titre):].strip(" -–:.")
    url_c = url_canonique(url)
    now = stockage.maintenant()
    if publie is None or publie > now + timedelta(hours=1):
        publie = now
    return {
        "id": empreinte(url_c),
        "url": url.strip(),
        "source": src.id,
        "titre": tronquer(titre, 220),
        "chapo": tronquer(chapo, 450),
        "publie_le": stockage.iso(publie),
        "collecte_le": stockage.iso(now),
        "categories": [c for c in categories if c][:6],
        "opinion": est_opinion(url_c, categories, titre),
        "accroche": est_accroche(chapo),
        "langue": src.langue,
        "via": via,
    }


def analyser_flux(src: Source, contenu: bytes, fenetre_h: int) -> list[dict]:
    flux = feedparser.parse(contenu)
    limite = stockage.maintenant() - timedelta(hours=fenetre_h)
    articles = []
    for e in flux.entries[:120]:
        publie = _date_entree(e)
        if publie and publie < limite:
            continue
        cats = [t.get("term", "") for t in e.get("tags", [])] if e.get("tags") else []
        chapo = e.get("summary") or e.get("description") or ""
        a = fabriquer_article(src, e.get("link", ""), e.get("title", ""), chapo, publie, cats)
        if a:
            articles.append(a)
    return articles


async def _lire_flux(client: httpx.AsyncClient, src: Source, etat: dict, sem: asyncio.Semaphore,
                     fenetre_h: int) -> tuple[str, list[dict], str | None]:
    entetes = {}
    if etat.get("etag"):
        entetes["If-None-Match"] = etat["etag"]
    if etat.get("modifie"):
        entetes["If-Modified-Since"] = etat["modifie"]
    async with sem:
        try:
            r = await client.get(src.flux, headers=entetes)
        except httpx.HTTPError as exc:
            return src.id, [], f"{type(exc).__name__}"
    if r.status_code == 304:
        return src.id, [], None
    if r.status_code >= 400:
        return src.id, [], f"HTTP {r.status_code}"
    etat["etag"] = r.headers.get("etag")
    etat["modifie"] = r.headers.get("last-modified")
    articles = analyser_flux(src, r.content, fenetre_h)
    if not articles and b"<item" not in r.content and b"<entry" not in r.content:
        return src.id, [], "Flux vide ou illisible"
    return src.id, articles, None


async def _collecter_rss(fenetre_h: int) -> tuple[list[dict], dict]:
    cfg = reglages()["collecte"]
    etats = stockage.lire_json("flux.json", {})
    sem = asyncio.Semaphore(cfg.get("requetes_simultanees", 10))
    actives = [s for s in sources() if s.actif and s.flux]
    async with httpx.AsyncClient(timeout=cfg.get("delai_requete_s", 20), follow_redirects=True,
                                 headers={"User-Agent": AGENT, "Accept": "application/rss+xml, application/xml, */*"},
                                 http2=False) as client:
        taches = [_lire_flux(client, s, etats.setdefault(s.id, {}), sem, fenetre_h) for s in actives]
        resultats = await asyncio.gather(*taches)
    tous: list[dict] = []
    for sid, articles, erreur in resultats:
        e = etats[sid]
        e["derniere_tentative"] = stockage.iso(stockage.maintenant())
        if erreur:
            e["echecs"] = e.get("echecs", 0) + 1
            e["erreur"] = erreur
        else:
            e["echecs"] = 0
            e["erreur"] = None
            e["dernier_succes"] = e["derniere_tentative"]
            if articles:
                e["derniers_articles"] = len(articles)
        tous.extend(articles)
    return tous, etats


# ------------------------------------------------------------------ API (facultatives)
def _source_api(url: str, nom_media: str) -> Source:
    src = source_par_domaine(url)
    if src:
        return src
    return Source(id="api:" + empreinte(nom_media or url, 8), nom=nom_media or "Autre média", pays="??", langue="en",
                  region="monde", nature="generaliste", orientation="autre")


def _parse_date(s: str | None) -> datetime | None:
    if not s:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            d = datetime.strptime(s, fmt)
            return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


async def _collecter_api() -> tuple[list[dict], dict[str, dict]]:
    cfg = config_api()
    articles: list[dict] = []
    medias_hors_catalogue: dict[str, dict] = {}
    async with httpx.AsyncClient(timeout=20, headers={"User-Agent": AGENT}) as client:
        gn = cfg.get("gnews", {})
        cle = os.environ.get(gn.get("cle_env", ""), "")
        if gn.get("actif") and cle:
            for req in gn.get("requetes", []):
                try:
                    r = await client.get("https://gnews.io/api/v4/top-headlines",
                                         params={**req, "max": 10, "apikey": cle})
                    for it in r.json().get("articles", []):
                        nom = (it.get("source") or {}).get("name", "")
                        src = _source_api(it.get("url", ""), nom)
                        a = fabriquer_article(src, it.get("url", ""), it.get("title", ""), it.get("description", ""),
                                              _parse_date(it.get("publishedAt")), [], via="gnews")
                        if a:
                            a["media_nom"] = src.nom
                            articles.append(a)
                            if src.id.startswith("api:"):
                                medias_hors_catalogue[src.id] = {"nom": src.nom}
                except (httpx.HTTPError, ValueError) as exc:
                    log.warning("GNews : %s", exc)
        nd = cfg.get("newsdata", {})
        cle = os.environ.get(nd.get("cle_env", ""), "")
        if nd.get("actif") and cle:
            for req in nd.get("requetes", []):
                try:
                    r = await client.get("https://newsdata.io/api/1/latest", params={**req, "apikey": cle})
                    for it in r.json().get("results", []) or []:
                        nom = it.get("source_name") or it.get("source_id") or ""
                        src = _source_api(it.get("link", ""), nom)
                        a = fabriquer_article(src, it.get("link", ""), it.get("title", ""), it.get("description") or "",
                                              _parse_date(it.get("pubDate")), it.get("category") or [], via="newsdata")
                        if a:
                            a["media_nom"] = src.nom
                            articles.append(a)
                            if src.id.startswith("api:"):
                                medias_hors_catalogue[src.id] = {"nom": src.nom}
                except (httpx.HTTPError, ValueError) as exc:
                    log.warning("NewsData : %s", exc)
        gu = cfg.get("guardian", {})
        cle = os.environ.get(gu.get("cle_env", ""), "")
        if gu.get("actif") and cle:
            try:
                r = await client.get("https://content.guardianapis.com/search",
                                     params={"api-key": cle, "page-size": 50, "order-by": "newest",
                                             "show-fields": "trailText", "section": "world|politics|business|technology|environment"})
                src = next((s for s in sources() if s.id == "guardian"), None) or _source_api("https://theguardian.com", "The Guardian")
                for it in r.json().get("response", {}).get("results", []):
                    a = fabriquer_article(src, it.get("webUrl", ""), it.get("webTitle", ""),
                                          (it.get("fields") or {}).get("trailText", ""),
                                          _parse_date(it.get("webPublicationDate")), [it.get("sectionName", "")],
                                          via="guardian")
                    if a:
                        articles.append(a)
            except (httpx.HTTPError, ValueError) as exc:
                log.warning("Guardian : %s", exc)
    return articles, medias_hors_catalogue


def collecter() -> dict:
    """Lit tous les flux et API, fusionne avec les articles déjà connus, enregistre l'état."""
    cfg = reglages()["collecte"]
    fenetre = max(cfg.get("fenetre_heures", 30), 30)
    nouveaux_rss, etats = asyncio.run(_collecter_rss(fenetre))
    nouveaux_api, hors_cat = asyncio.run(_collecter_api())
    connus = stockage.charger_articles()
    ajoutes = 0
    for a in nouveaux_rss + nouveaux_api:
        if a["id"] in connus:
            # mise à jour légère (titre corrigé, chapô complété) sans changer la date de première collecte
            ancien = connus[a["id"]]
            ancien["titre"], ancien["chapo"] = a["titre"], a["chapo"] or ancien["chapo"]
            continue
        connus[a["id"]] = a
        ajoutes += 1
    stockage.enregistrer_articles(connus, cfg.get("conservation_heures", 72))
    stockage.ecrire_json("flux.json", etats)
    if hors_cat:
        medias = stockage.lire_json("medias_api.json", {})
        medias.update(hors_cat)
        stockage.ecrire_json("medias_api.json", medias)
    echecs = sorted(sid for sid, e in etats.items() if e.get("erreur"))
    bilan = {"etape": "collecte", "articles_ajoutes": ajoutes, "articles_connus": len(connus),
             "flux_en_echec": echecs, "via_api": len(nouveaux_api)}
    stockage.journaliser(bilan)
    log.info("Collecte : %s nouveaux articles, %s flux en échec", ajoutes, len(echecs))
    return bilan
