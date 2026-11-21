"""Génère un jeu d'articles FICTIFS pour essayer l'application hors ligne (aperçu de la PWA, tests).

Usage :  INFODUJOUR_ETAT=etat-demo python outils/demo.py
puis     INFODUJOUR_ETAT=etat-demo python -m infodujour regrouper && ... rediger && ... publier && ... site
Les sujets sont inventés et clairement marqués « Exemple ».
"""
from __future__ import annotations

import random
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from infodujour import stockage  # noqa: E402
from infodujour.config import sources_par_id  # noqa: E402
from infodujour.texte import empreinte  # noqa: E402

SUJETS = [
    ("france", "politique", "budget", ["Exemple : l'Assemblée nationale examine le projet de budget de l'État",
      "Exemple : budget de l'État, les députés entament l'examen du texte à l'Assemblée nationale",
      "Exemple : le projet de budget arrive à l'Assemblée nationale, l'opposition dénonce des économies"],
     ["Les députés ont commencé mardi l'examen du projet de loi de finances. Le gouvernement prévoit 30 milliards d'euros d'économies. L'opposition annonce une motion de censure.",
      "Le texte budgétaire prévoit une baisse des dépenses de l'État. Les syndicats critiquent la réforme et appellent à une mobilisation.",
      "Selon le ministre, le déficit doit revenir sous 5 % du PIB. La majorité défend un budget « responsable »."],
     ["gauche", "droite", "centre", "non-partisan", "centre-gauche", "centre-droit"]),
    ("france", "societe", "greve", ["Exemple : grève dans les transports franciliens jeudi",
      "Exemple : trafic perturbé jeudi en Île-de-France en raison d'une grève à la RATP",
      "Exemple : grève RATP, les syndicats réclament des hausses de salaire"],
     ["Les syndicats de la RATP appellent à la grève jeudi pour les salaires. Le trafic sera fortement perturbé sur plusieurs lignes de métro à Paris.",
      "La direction de la RATP prévoit un service réduit. Les usagers sont invités à anticiper leurs déplacements."],
     ["gauche", "centre", "non-partisan", "droite", "centre-droit"]),
    ("france", "economie", "smic", ["Exemple : le Smic augmentera de 2 % au 1er janvier",
      "Exemple : revalorisation du Smic, une hausse de 2 % annoncée pour janvier"],
     ["Le salaire minimum sera revalorisé de 2 % au 1er janvier, a annoncé le ministère du Travail. La hausse suit l'inflation.",
      "Le Smic augmentera mécaniquement au 1er janvier. Les organisations patronales jugent la hausse supportable."],
     ["centre", "centre-droit", "non-partisan", "gauche"]),
    ("france", "sport", "psg", ["Exemple : le PSG s'impose face à Marseille au Parc des Princes",
      "Exemple : Ligue 1, Paris remporte le classique contre l'OM"],
     ["Le Paris Saint-Germain a battu l'Olympique de Marseille 2-1 dimanche soir au Parc des Princes, en Ligue 1.",
      "Le club parisien conforte sa première place du championnat après sa victoire contre l'OM."],
     ["centre", "non-partisan", "droite"]),
    ("france", "sante", "grippe", ["Exemple : l'épidémie de grippe progresse en France selon Santé publique France",
      "Exemple : grippe, les hôpitaux face à une hausse des passages aux urgences"],
     ["Santé publique France signale une progression de l'épidémie de grippe dans dix régions. Les passages aux urgences augmentent.",
      "Les autorités sanitaires appellent les personnes fragiles à se faire vacciner contre la grippe."],
     ["non-partisan", "centre", "centre-gauche"]),
    ("international", "politique", "sommet", ["Example: EU leaders meet in Brussels for climate summit",
      "Exemple : sommet européen à Bruxelles sur le climat",
      "Exemple : les dirigeants européens réunis à Bruxelles pour un sommet climat"],
     ["Les chefs d'État et de gouvernement de l'Union européenne se réunissent jeudi à Bruxelles pour fixer un objectif climatique pour 2040.",
      "EU leaders gathered in Brussels on Thursday to agree on a 2040 climate target, amid divisions over costs."],
     ["non-partisan", "centre", "centre-gauche", "centre-droit", "droite"]),
    ("international", "economie", "taux", ["Exemple : la Banque centrale européenne maintient ses taux directeurs",
      "Example: ECB holds interest rates steady"],
     ["La BCE a laissé ses taux directeurs inchangés jeudi, estimant que l'inflation se rapproche de son objectif de 2 %.",
      "The European Central Bank kept interest rates unchanged, saying inflation is close to its 2% target."],
     ["centre-droit", "non-partisan", "centre", "centre-gauche"]),
    ("international", "sciences-environnement", "seisme", ["Exemple : séisme de magnitude 6,8 au large du Japon",
      "Example: magnitude 6.8 earthquake strikes off Japan coast"],
     ["Un séisme de magnitude 6,8 a frappé au large des côtes japonaises vendredi. Une alerte au tsunami a été brièvement émise.",
      "A magnitude 6.8 earthquake struck off the coast of Japan on Friday, prompting a brief tsunami warning."],
     ["non-partisan", "centre", "autre", "centre-gauche"]),
    ("international", "technologie", "ia", ["Exemple : une loi encadrant l'intelligence artificielle adoptée par le Parlement européen",
      "Example: European Parliament adopts AI rules"],
     ["Le Parlement européen a adopté de nouvelles règles sur l'intelligence artificielle. Les entreprises critiquent des obligations jugées lourdes.",
      "Lawmakers adopted new rules on artificial intelligence. Tech companies criticised the obligations."],
     ["centre", "centre-gauche", "centre-droit", "non-partisan"]),
    ("france", "politique", "immigration", ["Exemple : le Sénat adopte un amendement sur l'immigration",
      "Exemple : immigration, la droite sénatoriale durcit le texte"],
     ["Le Sénat a adopté un amendement durcissant les conditions du regroupement familial. La gauche dénonce un texte contraire aux droits.",
      "Les sénateurs ont voté un durcissement du projet de loi immigration. Le gouvernement salue un compromis."],
     ["droite", "droite", "centre-droit", "droite", "gauche"]),
    ("france", "culture", "festival", ["Exemple : le festival d'Angoulême dévoile sa sélection officielle",
      "Exemple : bande dessinée, la sélection d'Angoulême est connue"],
     ["Le Festival international de la bande dessinée d'Angoulême a dévoilé les albums en compétition pour sa prochaine édition.",
      "Quarante-cinq albums figurent dans la sélection officielle du festival d'Angoulême, qui se tiendra fin janvier."],
     ["centre", "centre-gauche", "non-partisan"]),
]


def main() -> None:
    random.seed(4)
    srcs = list(sources_par_id().values())
    par_orient: dict[str, list] = {}
    for s in srcs:
        par_orient.setdefault(s.orientation, []).append(s)
    now = stockage.maintenant()
    articles = {}
    for perimetre, rubrique, cle, titres, chapos, orientations in SUJETS:
        utilises = set()
        for k, o in enumerate(orientations):
            candidats = [s for s in par_orient.get(o, []) if s.id not in utilises
                         and ((s.region == "france") == (perimetre == "france") or o in ("non-partisan", "autre"))]
            if not candidats:
                candidats = [s for s in par_orient.get(o, []) if s.id not in utilises]
            if not candidats:
                continue
            src = random.choice(candidats)
            utilises.add(src.id)
            url = f"https://exemple.invalid/{src.id}/{rubrique}/{cle}-{k}"
            if k == len(orientations) - 1 and rubrique == "politique":
                url = f"https://exemple.invalid/{src.id}/opinions/tribune-{cle}"
            publie = now - timedelta(hours=random.uniform(1, 20))
            articles[empreinte(url)] = {
                "id": empreinte(url), "url": url, "source": src.id, "titre": titres[k % len(titres)],
                "chapo": chapos[k % len(chapos)], "publie_le": stockage.iso(publie), "collecte_le": stockage.iso(now),
                "categories": [rubrique, "France" if perimetre == "france" else "Monde"],
                "opinion": "/opinions/" in url, "accroche": False, "langue": "fr" if titres[k % len(titres)].startswith("Exemple") else "en",
                "via": "demo",
            }
    stockage.enregistrer_articles(articles, 72)
    print(f"{len(articles)} articles fictifs écrits dans {stockage.chemin('articles.json.gz')}")


if __name__ == "__main__":
    main()
