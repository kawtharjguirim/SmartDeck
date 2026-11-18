"""Étape 12 : export du PPTX en PDF (FR-10) avec LibreOffice sans fenêtre (headless).

- LibreOffice : tools/libreoffice (extrait à l'étape 12), sinon installation standard
  ou PATH. Profil dédié dans .cache/ : pas de conflit avec un LibreOffice ouvert.
- Secours : PowerPoint (Windows), s'il est installé et que LibreOffice est absent.
"""
import shutil
import subprocess
import sys
import time
from pathlib import Path

import config

STANDARD_PATHS = [
    Path(r"C:\Program Files\LibreOffice\program\soffice.exe"),
    Path(r"C:\Program Files (x86)\LibreOffice\program\soffice.exe"),
]
POWERPOINT_SCRIPT = config.ROOT_DIR / "tools" / "pptx_to_pdf.ps1"


class PdfExportError(RuntimeError):
    pass


def find_soffice() -> str | None:
    for candidate in [Path(config.SOFFICE), *STANDARD_PATHS]:
        if candidate.exists():
            return str(candidate)
    return shutil.which("soffice")


def _libreoffice(soffice: str, pptx: Path, out_dir: Path) -> None:
    profile = config.LIBREOFFICE_PROFILE.resolve().as_uri()
    result = subprocess.run(
        [soffice, "--headless", "--norestore", "--nolockcheck",
         f"-env:UserInstallation={profile}",
         "--convert-to", "pdf", "--outdir", str(out_dir), str(pptx)],
        capture_output=True, timeout=config.PDF_TIMEOUT,
    )
    if result.returncode != 0:
        raise PdfExportError("LibreOffice : " + result.stderr.decode("utf-8", "replace").strip())


def _powerpoint(pptx: Path, pdf: Path) -> None:
    result = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
         str(POWERPOINT_SCRIPT), str(pptx), str(pdf)],
        capture_output=True, timeout=config.PDF_TIMEOUT,
    )
    if result.returncode != 0:
        raise PdfExportError("PowerPoint : " + result.stderr.decode("utf-8", "replace").strip())


def export_pdf(pptx: Path, out_dir: Path | None = None) -> tuple[Path, str]:
    """Convertit `pptx` en PDF. Renvoie (chemin du PDF, outil utilisé)."""
    pptx = pptx.resolve()
    out_dir = (out_dir or pptx.parent).resolve()
    pdf = out_dir / f"{pptx.stem}.pdf"
    start = time.time()

    soffice = find_soffice()
    try:
        if soffice:
            _libreoffice(soffice, pptx, out_dir)
            tool = "LibreOffice"
        elif sys.platform == "win32" and POWERPOINT_SCRIPT.exists():
            _powerpoint(pptx, pdf)
            tool = "PowerPoint"
        else:
            raise PdfExportError("LibreOffice introuvable (tools/libreoffice, Program Files "
                                 "ou PATH) : PDF non généré")
    except subprocess.TimeoutExpired as e:
        raise PdfExportError(f"conversion PDF trop longue (> {config.PDF_TIMEOUT} s)") from e

    # Un ancien PDF du même nom ne doit pas passer pour le nouveau.
    if not pdf.exists() or pdf.stat().st_mtime < start - 1:
        raise PdfExportError(f"{tool} n'a pas produit {pdf.name}")
    return pdf, tool
