"""Édition audio (facultative) : synthèse vocale locale avec Piper, sans IA à quota.

Activée par « audio: actif: true » dans config/reglages.yaml. Le workflow installe alors piper-tts.
Seules les 7 dernières éditions audio sont conservées pour ne pas alourdir le dépôt.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from . import stockage
from .config import reglages
from .edition import _ecrire_edition, sans_references

log = logging.getLogger(__name__)


def texte_a_lire(edition: dict) -> str:
    morceaux = [f"Info du Jour, édition du {edition['date']}."]
    ess = (edition.get("essentiel") or {}).get("texte")
    if ess:
        morceaux += ["L'essentiel.", sans_references(ess)]
    for perimetre, titre in (("france", "En France."), ("international", "À l'international.")):
        morceaux.append(titre)
        for sid in edition["tops"][perimetre][:5]:
            s = edition["sujets"][sid]
            morceaux.append(f"{s['titre']}. {sans_references(s['resume'])}")
    morceaux.append("Retrouvez toutes les sources et les points de vue dans l'application.")
    return "\n".join(morceaux)


def generer() -> bool:
    cfg = reglages().get("audio", {})
    if not cfg.get("actif"):
        return False
    edition = stockage.lire_json("public/edition.json")
    if not edition:
        return False
    voix = cfg.get("voix", "fr_FR-siwis-medium")
    dossier_voix = stockage.chemin("voix", "x").parent
    try:
        if not (dossier_voix / f"{voix}.onnx").exists():
            subprocess.run([sys.executable, "-m", "piper.download_voices", "--download-dir", str(dossier_voix), voix],
                           check=True, timeout=300)
        with tempfile.TemporaryDirectory() as tmp:
            wav = Path(tmp) / "edition.wav"
            subprocess.run([sys.executable, "-m", "piper", "-m", str(dossier_voix / f"{voix}.onnx"), "-f", str(wav)],
                           input=texte_a_lire(edition).encode("utf-8"), check=True, timeout=900)
            sortie = stockage.chemin("public", "audio", f"{edition['date']}.mp3")
            if shutil.which("ffmpeg"):
                subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav), "-ac", "1", "-b:a", "48k",
                                str(sortie)], check=True, timeout=300)
            else:
                sortie = sortie.with_suffix(".wav")
                shutil.copy(wav, sortie)
    except (subprocess.SubprocessError, OSError) as exc:
        log.warning("Édition audio impossible : %s", exc)
        return False
    edition["audio"] = f"audio/{sortie.name}"
    _ecrire_edition(edition)
    fichiers = sorted(stockage.chemin("public", "audio", "x").parent.glob("*.*"))
    for vieux in fichiers[:-7]:
        vieux.unlink()
    return True
