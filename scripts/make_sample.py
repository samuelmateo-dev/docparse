"""Régénère data/sample/ (bruit 15 %, graine 7) et data/sample_noisy/ (bruit 80 %, graine 11) :
60 factures fictives en PDF chacun + la vérité. Nécessite fpdf2 (pip install -e .[dev]).
Les graines ont été fixées avant de regarder les résultats.

Usage : python scripts/make_sample.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from fpdf import FPDF

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from docparse.synth import generate  # noqa: E402

FONTS = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/usr/share/fonts/dejavu/DejaVuSansMono.ttf",
    "C:/Windows/Fonts/consola.ttf",
)


def write_pdf(text: str, path: Path) -> None:
    pdf = FPDF()
    pdf.add_page()
    font = next((f for f in FONTS if Path(f).exists()), None)
    if font:
        pdf.add_font("Mono", fname=font)
        pdf.set_font("Mono", size=9)
    else:  # police intégrée : pas de « € » possible
        pdf.set_font("Courier", size=9)
        text = text.replace("€", "EUR")
    for line in text.splitlines():
        pdf.cell(0, 5, line, new_x="LMARGIN", new_y="NEXT")
    pdf.output(str(path))


def build(folder: Path, n: int, seed: int, noise_rate: float) -> None:
    (folder / "invoices").mkdir(parents=True, exist_ok=True)
    truth = {}
    for invoice in generate(n, seed, noise_rate):
        write_pdf(invoice.text, folder / "invoices" / invoice.name)
        truth[invoice.name] = invoice.truth
    (folder / "truth.json").write_text(json.dumps({"files": truth}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(truth)} factures écrites dans {folder}")


def main() -> None:
    data = Path(__file__).resolve().parents[1] / "data"
    build(data / "sample", 60, seed=7, noise_rate=0.15)
    build(data / "sample_noisy", 60, seed=11, noise_rate=0.8)


if __name__ == "__main__":
    main()
