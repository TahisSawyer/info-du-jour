"""Ligne de commande : python -m infodujour <commande>

Commandes :
  planifier          décide des étapes à exécuter (utilisé par le workflow GitHub)
  collecter          lit les flux RSS et les API
  regrouper          regroupe les articles en sujets et les classe (--mode edition|preparation)
  rediger            rédige les sujets retenus (IA, puis repli sans IA)
  publier            écrit l'édition dans etat/public/
  rattraper          relance l'IA sur les sujets restés sans IA (--forcer)
  audio              génère l'édition audio (si activée)
  site               assemble le site à publier (--sortie _site)
  verifier-flux      teste chaque flux du catalogue et affiche un rapport
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import shutil
import sys
from pathlib import Path

from . import stockage
from .config import DOSSIER_ETAT, RACINE


def _site(sortie: str) -> None:
    dest = Path(sortie)
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(RACINE / "site", dest)
    public = DOSSIER_ETAT / "public"
    if public.exists():
        shutil.copytree(public, dest / "donnees")
    else:
        (dest / "donnees").mkdir()
    depot = os.environ.get("GITHUB_REPOSITORY", "")
    (dest / "config.json").write_text(json.dumps({
        "depot": depot,
        "workflow": "infodujour.yml",
        "branche": os.environ.get("GITHUB_REF_NAME", "main"),
    }, ensure_ascii=False), encoding="utf-8")
    (dest / ".nojekyll").write_text("")
    print(f"Site assemblé dans {dest}")


def _message() -> None:
    """Écrit dans GITHUB_OUTPUT le titre et le texte de la notification « édition disponible »."""
    from datetime import date

    e = stockage.lire_json("public/edition.json") or {}
    if not e:
        return
    jours = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
    mois = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre",
            "novembre", "décembre"]
    d = date.fromisoformat(e["date"])
    titre = f"Bat News · {jours[d.weekday()]} {d.day} {mois[d.month - 1]}"
    une = e["sujets"].get((e["tops"].get("france") or [""])[0], {}).get("titre", "")
    ia = e.get("couverture_ia", {})
    texte = f"Nouvelle édition disponible. À la une : {une}" if une else "Nouvelle édition disponible."
    if ia and ia.get("ia") != ia.get("total"):
        texte += f" (résumés IA : {ia.get('ia')}/{ia.get('total')})"
    sortie = os.environ.get("GITHUB_OUTPUT")
    if sortie:
        with open(sortie, "a", encoding="utf-8") as f:
            f.write(f"titre={titre}\ntexte={texte.replace(chr(10), ' ')}\n")
    print(titre, "—", texte)


def _verifier_flux() -> int:
    from .collecte import _lire_flux
    from .config import sources
    import httpx

    async def tout():
        sem = asyncio.Semaphore(10)
        async with httpx.AsyncClient(timeout=20, follow_redirects=True,
                                     headers={"User-Agent": "InfoDuJour/1.0 (verification)"}) as client:
            return await asyncio.gather(*[_lire_flux(client, s, {}, sem, 48) for s in sources() if s.flux])

    resultats = asyncio.run(tout())
    noms = {s.id: s.nom for s in sources()}
    lignes = ["| Média | Résultat | Articles (48 h) |", "| --- | --- | --- |"]
    ko = 0
    for sid, articles, erreur in sorted(resultats, key=lambda r: (r[2] is None, r[0])):
        if erreur or not articles:
            ko += 1
        lignes.append(f"| {noms.get(sid, sid)} | {'❌ ' + erreur if erreur else ('⚠️ aucun article récent' if not articles else '✅')} | {len(articles)} |")
    rapport = f"### Vérification des flux : {len(resultats) - ko} OK, {ko} à revoir\n\n" + "\n".join(lignes)
    print(rapport)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(rapport + "\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s : %(message)s")
    p = argparse.ArgumentParser(prog="infodujour")
    sp = p.add_subparsers(dest="commande", required=True)
    pl = sp.add_parser("planifier")
    pl.add_argument("--evenement", default=os.environ.get("GITHUB_EVENT_NAME", "schedule"))
    pl.add_argument("--mode", default=os.environ.get("MODE_DEMANDE", ""))
    pl.add_argument("--forcer", default=os.environ.get("FORCER", "false"))
    sp.add_parser("collecter")
    rg = sp.add_parser("regrouper")
    rg.add_argument("--mode", default="edition", choices=["edition", "preparation"])
    rg.add_argument("--declenchement", default="planifie")
    sp.add_parser("rediger")
    sp.add_parser("publier")
    rt = sp.add_parser("rattraper")
    rt.add_argument("--forcer", action="store_true")
    sp.add_parser("audio")
    st = sp.add_parser("site")
    st.add_argument("--sortie", default="_site")
    sp.add_parser("verifier-flux")
    sp.add_parser("message")
    a = p.parse_args(argv)

    if a.commande == "planifier":
        from .planif import decider, ecrire_sorties

        ecrire_sorties(decider(a.evenement, a.mode, str(a.forcer).lower() == "true"))
    elif a.commande == "collecter":
        from .collecte import collecter
        from .vecteurs import precalculer

        collecter()
        try:
            from .classement import fenetre_articles

            n = precalculer(fenetre_articles(stockage.charger_articles()))
            if n:
                logging.info("%s vecteurs précalculés", n)
        except Exception as exc:  # le précalcul est une optimisation : jamais bloquant
            logging.warning("Précalcul des vecteurs ignoré : %s", exc)
    elif a.commande == "regrouper":
        from .edition import regrouper_et_classer

        regrouper_et_classer(a.mode, a.declenchement)
    elif a.commande == "rediger":
        from .edition import rediger

        rediger()
    elif a.commande == "publier":
        from .edition import publier

        e = publier()
        if e:
            print(f"Édition {e['id']} publiée : IA {e['couverture_ia']['ia']}/{e['couverture_ia']['total']}")
        if os.environ.get("GITHUB_OUTPUT"):
            with open(os.environ["GITHUB_OUTPUT"], "a") as f:
                f.write(f"publie={'true' if e else 'false'}\n")
    elif a.commande == "rattraper":
        from .edition import rattraper

        change = rattraper(a.forcer)
        if os.environ.get("GITHUB_OUTPUT"):
            with open(os.environ["GITHUB_OUTPUT"], "a") as f:
                f.write(f"modifie={'true' if change else 'false'}\n")
    elif a.commande == "audio":
        from .audio import generer

        generer()
    elif a.commande == "site":
        _site(a.sortie)
    elif a.commande == "verifier-flux":
        return _verifier_flux()
    elif a.commande == "message":
        _message()
    return 0


if __name__ == "__main__":
    sys.exit(main())
