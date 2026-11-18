"""Génère les fichiers de test de l'ingestion (texte, PDF natif, PDF « scanné »).

Usage : python samples/make_samples.py
"""
from pathlib import Path

import pymupdf

HERE = Path(__file__).resolve().parent

MARKDOWN = """# Rapport Verdi 2025

L'entreprise Verdi a réalisé un chiffre d'affaires de 4,2 millions d'euros en 2025,
en hausse de 12 % par rapport à 2024.

## Ventes

Les ventes en ligne représentent désormais 38 % du total.

| Trimestre | Ventes (k€) |
|---|---|
| T1 | 950 |
| T2 | 1 020 |
| T3 | 1 060 |
| T4 | 1 170 |

## Perspectives

L'entreprise compte 45 salariés et prévoit d'ouvrir une agence à Lyon en 2026.
"""

PAGES = [
    """<h1>Rapport annuel Verdi 2025</h1>
    <p>L'entreprise Verdi a réalisé un chiffre d'affaires de 4,2 millions d'euros en 2025,
    en hausse de 12 % par rapport à 2024. Cette croissance est portée par le commerce en ligne
    et par l'arrivée de deux nouveaux clients dans le secteur de la santé.</p>
    <h2>Ventes par trimestre</h2>
    <p>Le tableau suivant présente les ventes trimestrielles en milliers d'euros.</p>
    <table border="1" cellpadding="4">
      <tr><th>Trimestre</th><th>Ventes (k€)</th><th>Part en ligne</th></tr>
      <tr><td>T1</td><td>950</td><td>34 %</td></tr>
      <tr><td>T2</td><td>1 020</td><td>37 %</td></tr>
      <tr><td>T3</td><td>1 060</td><td>39 %</td></tr>
      <tr><td>T4</td><td>1 170</td><td>41 %</td></tr>
    </table>""",
    """<h2>Ressources humaines</h2>
    <p>L'entreprise compte 45 salariés au 31 décembre 2025, contre 38 un an plus tôt.
    Le principal défi reste le recrutement de profils techniques, en particulier
    des développeurs et des data scientists.</p>
    <h2>Perspectives 2026</h2>
    <p>Verdi prévoit d'ouvrir une agence à Lyon au second semestre 2026 et vise
    un chiffre d'affaires de 5 millions d'euros.</p>""",
    """<h2>Conclusion</h2>
    <p>L'année 2025 confirme la solidité du modèle de Verdi. La priorité de 2026 sera
    de réussir l'ouverture lyonnaise tout en maintenant la rentabilité.</p>""",
]


def make_pdf(path: Path) -> None:
    doc = pymupdf.open()
    for i, html in enumerate(PAGES, start=1):
        page = doc.new_page()  # A4
        # En-tête et pied de page répétés : doivent être ignorés par l'ingestion.
        page.insert_text((50, 30), "Verdi — Rapport confidentiel", fontsize=8)
        page.insert_text((280, 820), f"Page {i} / {len(PAGES)}", fontsize=8)
        page.insert_htmlbox(pymupdf.Rect(50, 50, 545, 790), html)
    doc.save(path)


def make_scanned_pdf(src: Path, dst: Path) -> None:
    """Simule un PDF scanné : chaque page devient une image, sans couche texte."""
    with pymupdf.open(src) as doc, pymupdf.open() as out:
        for page in doc:
            pix = page.get_pixmap(dpi=150)
            new = out.new_page(width=page.rect.width, height=page.rect.height)
            new.insert_image(new.rect, pixmap=pix)
        out.save(dst)


# --- Images (étape 10) : un graphique, un schéma, une page de texte -------

SALES = {"T1": 950, "T2": 1020, "T3": 1060, "T4": 1170}
PROCESS = ["Prospection", "Devis", "Signature", "Livraison", "Facturation"]


def make_chart(path: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(8, 5), dpi=120)
    bars = ax.bar(list(SALES), list(SALES.values()), color="#1F3A5F")
    ax.bar_label(bars, labels=[str(v) for v in SALES.values()], padding=3, fontsize=12)
    ax.set_title("Ventes trimestrielles Verdi 2025 (k€)", fontsize=14)
    ax.set_ylabel("k€")
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def make_diagram(path: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(12, 3), dpi=120)
    ax.set_xlim(0, len(PROCESS) * 2.4)
    ax.set_ylim(0, 3)
    ax.axis("off")
    for i, step in enumerate(PROCESS):
        x = 0.2 + i * 2.4
        ax.add_patch(plt.Rectangle((x, 0.9), 1.8, 1.2, color="#1F3A5F"))
        ax.text(x + 0.9, 1.5, step, color="white", ha="center", va="center", fontsize=12)
        if i < len(PROCESS) - 1:
            ax.annotate("", xy=(x + 2.35, 1.5), xytext=(x + 1.85, 1.5),
                        arrowprops={"arrowstyle": "->", "lw": 2, "color": "#E07A2E"})
    ax.text(len(PROCESS) * 1.2, 2.6, "Processus commercial Verdi", ha="center", fontsize=14)
    fig.savefig(path, format="jpg")
    plt.close(fig)


def make_text_image(src: Path, path: Path) -> None:
    """Capture d'une page de texte (page 2 du PDF), comme une photo d'écran."""
    with pymupdf.open(src) as doc:
        doc[1].get_pixmap(dpi=150, clip=pymupdf.Rect(40, 40, 555, 330)).save(path)


# --- Jeu d'acceptation (étape 14) : texte anglais, PDF budget, scan arabe ----

ENGLISH_NOTE = """Greenfield Cooperative - Annual Note 2025

Greenfield is a farming cooperative with 120 member farms in the Loire valley.
In 2025 the cooperative sold 8,400 tonnes of vegetables, up 6% from 2024.
Revenue reached 14.5 million euros, while operating costs stayed at 12.1 million euros.

Members and organisation
The cooperative employs 35 staff. Member farms elect a board of 9 people every three years.
Two new farms joined in 2025, and one farm left after the owner retired.

Sustainability
Water use per tonne fell by 11% thanks to drip irrigation on 40 farms.
Solar panels on the main warehouse now cover 30% of its electricity needs.

How a harvest reaches the shops
1. Harvest: farms pick and sort the vegetables.
2. Collection: trucks bring the crates to the central warehouse.
3. Quality control: each batch is checked and graded.
4. Packaging: vegetables are washed, weighed and packed.
5. Delivery: orders leave for 210 shops within 24 hours.

Outlook 2026
The board plans a second warehouse near Angers and a target of 9,000 tonnes.
"""

BUDGET_PAGES = [
    """<h1>Bilan 2025 de l'association Lire Ensemble</h1>
    <p>L'association Lire Ensemble anime des ateliers de lecture dans 14 écoles de Rennes.
    En 2025, elle a accompagné 620 enfants, contre 540 en 2024, avec 48 bénévoles.</p>
    <h2>Répartition du budget</h2>
    <p>Le budget 2025 s'élève à 86 000 euros, réparti comme suit.</p>
    <table border="1" cellpadding="4">
      <tr><th>Poste</th><th>Part du budget</th></tr>
      <tr><td>Ateliers</td><td>52 %</td></tr>
      <tr><td>Achat de livres</td><td>23 %</td></tr>
      <tr><td>Formation des bénévoles</td><td>15 %</td></tr>
      <tr><td>Fonctionnement</td><td>10 %</td></tr>
    </table>""",
    """<h2>Déroulement d'un atelier</h2>
    <p>1. Accueil : les enfants choisissent un livre dans la malle.</p>
    <p>2. Lecture à voix haute : un bénévole lit une histoire au groupe.</p>
    <p>3. Échange : les enfants racontent ce qu'ils ont compris.</p>
    <p>4. Lecture en binôme : chaque enfant lit une page à un camarade.</p>
    <h2>Objectifs 2026</h2>
    <p>L'association veut ouvrir des ateliers dans 4 nouvelles écoles et recruter
    20 bénévoles supplémentaires.</p>""",
]

ARABIC_PAGES = [
    """<h1>تقرير جمعية النور 2025</h1>
    <p>تعمل جمعية النور في مجال محو الأمية في مدينة صفاقس منذ عام 2015.
    في عام 2025 استفاد من برامجها 340 متعلما، مقابل 290 في عام 2024.</p>
    <h2>الموارد البشرية</h2>
    <p>يعمل في الجمعية 12 موظفا و 60 متطوعا. ويتلقى كل متطوع تكوينا مدته 20 ساعة.</p>""",
    """<h2>الميزانية</h2>
    <p>بلغت ميزانية الجمعية 95 ألف دينار، خصص 70 بالمئة منها للدروس.</p>
    <h2>آفاق 2026</h2>
    <p>تسعى الجمعية إلى فتح مركزين جديدين واستقبال 400 متعلم.</p>""",
]


def make_html_pdf(pages: list[str], path: Path, css: str = "", rtl: bool = False) -> None:
    doc = pymupdf.open()
    for html in pages:
        page = doc.new_page()
        if rtl:
            html = f'<div dir="rtl" style="text-align: right">{html}</div>'
        page.insert_htmlbox(pymupdf.Rect(50, 50, 545, 790), html, css=css)
    doc.save(path)


if __name__ == "__main__":
    (HERE / "greenfield_note.txt").write_text(ENGLISH_NOTE, encoding="utf-8")
    make_html_pdf(BUDGET_PAGES, HERE / "bilan_lire_ensemble.pdf")
    arial = "@font-face {font-family: Arial; src: url(C:/Windows/Fonts/arial.ttf);} " \
            "* {font-family: Arial;}"
    make_html_pdf(ARABIC_PAGES, HERE / "_rapport_nour.pdf", css=arial, rtl=True)
    make_scanned_pdf(HERE / "_rapport_nour.pdf", HERE / "rapport_nour_scanne.pdf")
    (HERE / "_rapport_nour.pdf").unlink()
    (HERE / "rapport_verdi.md").write_text(MARKDOWN, encoding="utf-8")
    make_pdf(HERE / "rapport_verdi.pdf")
    make_scanned_pdf(HERE / "rapport_verdi.pdf", HERE / "rapport_verdi_scanne.pdf")
    make_chart(HERE / "verdi_ventes.png")
    make_diagram(HERE / "verdi_processus.jpg")
    make_text_image(HERE / "rapport_verdi.pdf", HERE / "verdi_note.png")
    print("Fichiers de test créés dans", HERE)
