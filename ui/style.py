"""Style de la maquette SmartDeck-app.html, appliqué à Streamlit, avec animations.

Couleurs : encre #1A1A3D, violet #7C3AED, magenta #D946EF, barre latérale #1E1B4B.
Police : Outfit, servie en local depuis static/fonts (.streamlit/config.toml) ;
aucun appel à Google Fonts, l'application reste hors ligne (NFR-01).

Animations en CSS pur (pas de bibliothèque externe) : apparition en fondu des blocs,
survols qui soulèvent les cartes, dégradés et halos animés, compteurs qui défilent,
étapes de génération pulsées. Tout est coupé si le système demande moins de mouvement
(prefers-reduced-motion), pour le confort et l'accessibilité.
"""
import html

import streamlit as st

INK, VIOLET, MAGENTA = "#1A1A3D", "#7C3AED", "#D946EF"

CSS = f"""
<style>
@property --sd-num {{ syntax: '<integer>'; inherits: false; initial-value: 0; }}
:root {{
  --sd-ink: {INK}; --sd-violet: {VIOLET}; --sd-magenta: {MAGENTA};
  --sd-muted: #64748B; --sd-line: #E2E8F0; --sd-soft: #F5F3FF;
  --sd-grad: linear-gradient(90deg, {VIOLET}, {MAGENTA});
  --sd-ease: cubic-bezier(.2, .8, .2, 1);
  --sd-shadow: 0 1px 2px rgba(26,26,61,.04), 0 8px 24px -12px rgba(26,26,61,.12);
  --sd-shadow-hover: 0 2px 4px rgba(26,26,61,.05), 0 22px 40px -18px rgba(124,58,237,.35);
}}

/* ---------- Bases ---------- */
h1, h2, h3 {{ color: var(--sd-ink); letter-spacing: -0.025em; font-weight: 700; }}
.block-container {{ padding-top: 2rem; max-width: 1200px; }}
::selection {{ background: #EDE9FE; color: var(--sd-ink); }}
::-webkit-scrollbar {{ width: 10px; height: 10px; }}
::-webkit-scrollbar-thumb {{ background: #DDD6FE; border-radius: 99px; border: 2px solid #fff; }}

/* Apparition en fondu, décalée bloc après bloc */
@keyframes sd-fade-up {{ from {{ opacity: 0; transform: translateY(14px); }}
                        to {{ opacity: 1; transform: none; }} }}
@keyframes sd-fade {{ from {{ opacity: 0; }} to {{ opacity: 1; }} }}
[data-testid="stMainBlockContainer"] > [data-testid="stVerticalBlock"] > div {{
  animation: sd-fade-up .55s var(--sd-ease) both;
}}
{"".join(f'''[data-testid="stMainBlockContainer"] > [data-testid="stVerticalBlock"] > div:nth-child({i}) {{ animation-delay: {i * 45}ms; }}
''' for i in range(1, 13))}

/* ---------- Titres et textes ---------- */
.sd-gradient {{ background: linear-gradient(90deg, {VIOLET}, {MAGENTA}, {VIOLET});
  background-size: 200% auto; -webkit-background-clip: text; background-clip: text;
  color: transparent; animation: sd-shine 6s linear infinite; }}
@keyframes sd-shine {{ to {{ background-position: 200% center; }} }}
.sd-eyebrow {{ display: inline-flex; align-items: center; gap: .45rem; color: var(--sd-violet);
  font-weight: 600; font-size: .78rem; letter-spacing: .16em; text-transform: uppercase;
  background: #F5F3FF; border: 1px solid #EDE9FE; padding: .3rem .8rem; border-radius: 99px; }}
.sd-eyebrow .dot {{ width: .45rem; height: .45rem; border-radius: 50%; background: var(--sd-grad);
  box-shadow: 0 0 0 0 rgba(124,58,237,.5); animation: sd-ping 2s infinite; }}
@keyframes sd-ping {{ 0% {{ box-shadow: 0 0 0 0 rgba(124,58,237,.45); }}
  70% {{ box-shadow: 0 0 0 9px rgba(124,58,237,0); }} 100% {{ box-shadow: 0 0 0 0 rgba(124,58,237,0); }} }}
.sd-page-title {{ margin-bottom: .1rem; font-size: 2.1rem; }}
.sd-subtitle {{ color: var(--sd-muted); margin-bottom: 1.2rem; font-size: 1.02rem; }}

/* ---------- Accueil : halo animé et maquettes de slides flottantes ---------- */
.sd-hero {{ position: relative; text-align: center; padding: 3.6rem 1rem 2.4rem; overflow: hidden;
  border-radius: 1.6rem; isolation: isolate; }}
.sd-hero::before, .sd-hero::after {{ content: ""; position: absolute; z-index: -1;
  width: 520px; height: 520px; border-radius: 50%; filter: blur(70px); opacity: .45; }}
.sd-hero::before {{ background: #C4B5FD; top: -260px; left: -120px;
  animation: sd-float-a 14s ease-in-out infinite; }}
.sd-hero::after {{ background: #F0ABFC; bottom: -300px; right: -140px;
  animation: sd-float-b 16s ease-in-out infinite; }}
@keyframes sd-float-a {{ 50% {{ transform: translate(120px, 60px) scale(1.1); }} }}
@keyframes sd-float-b {{ 50% {{ transform: translate(-110px, -50px) scale(1.08); }} }}
.sd-hero h1 {{ font-size: clamp(2.4rem, 5vw, 4rem); line-height: 1.03; margin: 1rem 0 1.1rem; }}
.sd-hero p {{ color: #475569; font-size: 1.15rem; max-width: 640px; margin: 0 auto; }}
.sd-stage {{ position: relative; height: 230px; margin: 2.2rem auto 0; max-width: 760px;
  perspective: 1200px; }}
.sd-mock {{ position: absolute; width: 300px; height: 170px; border-radius: 14px; background: #fff;
  border: 1px solid #EDE9FE; box-shadow: 0 30px 60px -30px rgba(76,29,149,.45);
  padding: 16px 18px; text-align: left; transition: transform .5s var(--sd-ease); }}
.sd-mock .bar {{ height: 9px; border-radius: 9px; background: #EEF2FF; margin: 8px 0; }}
.sd-mock .bar.title {{ width: 62%; height: 13px; background: var(--sd-grad); opacity: .85; }}
.sd-mock .bars {{ display: flex; align-items: end; gap: 9px; height: 70px; margin-top: 12px; }}
.sd-mock .bars span {{ flex: 1; border-radius: 6px 6px 2px 2px; background: var(--sd-grad);
  transform-origin: bottom; animation: sd-grow 2.8s var(--sd-ease) infinite alternate; }}
@keyframes sd-grow {{ from {{ transform: scaleY(.35); }} to {{ transform: scaleY(1); }} }}
.sd-mock.m1 {{ left: 4%; top: 40px; transform: rotateY(18deg) rotateZ(-5deg);
  animation: sd-bob 7s ease-in-out infinite; }}
.sd-mock.m2 {{ left: calc(50% - 150px); top: 0; z-index: 2; animation: sd-bob 6s ease-in-out -2s infinite; }}
.sd-mock.m3 {{ right: 4%; top: 46px; transform: rotateY(-18deg) rotateZ(5deg);
  animation: sd-bob 8s ease-in-out -4s infinite; }}
@keyframes sd-bob {{ 50% {{ translate: 0 -12px; }} }}
.sd-stage:hover .sd-mock.m1 {{ transform: rotateY(8deg) rotateZ(-2deg) translateX(-20px); }}
.sd-stage:hover .sd-mock.m3 {{ transform: rotateY(-8deg) rotateZ(2deg) translateX(20px); }}

/* ---------- Cartes ---------- */
.sd-card {{ position: relative; background: #fff; border: 1px solid var(--sd-line);
  border-radius: 1.1rem; padding: 1.25rem 1.35rem; box-shadow: var(--sd-shadow); height: 100%;
  transition: transform .35s var(--sd-ease), box-shadow .35s var(--sd-ease), border-color .35s; }}
.sd-card:hover {{ transform: translateY(-4px); box-shadow: var(--sd-shadow-hover);
  border-color: #DDD6FE; }}
.sd-card h4 {{ margin: .65rem 0 .3rem; color: var(--sd-ink); font-size: 1.03rem; }}
.sd-card p {{ color: var(--sd-muted); margin: 0; font-size: .92rem; line-height: 1.5; }}
.sd-icon {{ display: inline-flex; width: 2.5rem; height: 2.5rem; border-radius: .8rem;
  align-items: center; justify-content: center; font-size: 1.2rem;
  background: linear-gradient(135deg, #EDE9FE, #FAE8FF); transition: transform .4s var(--sd-ease); }}
.sd-card:hover .sd-icon {{ transform: rotate(-8deg) scale(1.08); }}

/* Statistiques : le chiffre défile de 0 à sa valeur */
.sd-stat {{ display: flex; align-items: center; gap: .9rem; }}
.sd-stat .sd-icon {{ flex: none; }}
.sd-num {{ font-size: 2rem; font-weight: 700; color: var(--sd-ink); line-height: 1.1;
  font-variant-numeric: tabular-nums; }}
.sd-num.count {{ animation: sd-count 1.4s var(--sd-ease) forwards; counter-reset: n var(--sd-num); }}
.sd-num.count::after {{ content: counter(n); }}
@keyframes sd-count {{ from {{ --sd-num: 0; }} to {{ --sd-num: var(--sd-target); }} }}
.sd-stat-label {{ color: var(--sd-muted); font-size: .85rem; }}

/* Bandeau d'accueil du tableau de bord */
.sd-banner {{ position: relative; overflow: hidden; border-radius: 1.4rem; padding: 1.8rem 2rem;
  color: #fff; background: linear-gradient(120deg, #1E1B4B, #4C1D95 45%, {VIOLET} 75%, {MAGENTA});
  background-size: 200% 200%; animation: sd-pan 14s ease infinite; margin-bottom: .6rem; }}
@keyframes sd-pan {{ 50% {{ background-position: 100% 50%; }} }}
.sd-banner h2 {{ color: #fff; margin: 0 0 .35rem; font-size: 1.9rem; }}
.sd-banner p {{ color: #E9D5FF; margin: 0; }}
.sd-banner::after {{ content: ""; position: absolute; width: 260px; height: 260px; right: -60px;
  top: -90px; border-radius: 50%; background: radial-gradient(circle, rgba(255,255,255,.28), transparent 70%);
  animation: sd-float-a 10s ease-in-out infinite; }}

/* Badges d'état */
.sd-badge {{ display: inline-flex; align-items: center; gap: .35rem; padding: .18rem .7rem;
  border-radius: 9999px; font-size: .78rem; font-weight: 600; white-space: nowrap; }}
.sd-badge::before {{ content: ""; width: .42rem; height: .42rem; border-radius: 50%;
  background: currentColor; }}
.sd-badge.ready {{ background: #D1FAE5; color: #065F46; }}
.sd-badge.outline {{ background: #E0E7FF; color: #3730A3; }}
.sd-badge.generating {{ background: #FEF3C7; color: #92400E; }}
.sd-badge.generating::before {{ animation: sd-ping 1.4s infinite; }}
.sd-badge.failed {{ background: #FFE4E6; color: #9F1239; }}

/* ---------- Conteneurs Streamlit à clé (classe st-key-…) ---------- */
[class*="st-key-sd-hover"] {{ border-radius: 1.1rem; transition: transform .35s var(--sd-ease),
  box-shadow .35s var(--sd-ease), border-color .35s; background: #fff; }}
[class*="st-key-sd-hover"]:hover {{ transform: translateY(-3px); box-shadow: var(--sd-shadow-hover);
  border-color: #DDD6FE !important; }}
[class*="st-key-sd-panel"] {{ background: linear-gradient(180deg, #FAF8FF, #fff); border-radius: 1.1rem; }}
[class*="st-key-sd-thumb"] img {{ border-radius: .7rem; transition: transform .5s var(--sd-ease); }}
[class*="st-key-sd-thumb"]:hover img {{ transform: scale(1.03); }}

/* ---------- Boutons ---------- */
.stButton > button, .stDownloadButton > button, .stFormSubmitButton > button {{
  border-radius: .8rem; font-weight: 600; transition: transform .2s var(--sd-ease),
  box-shadow .25s, border-color .25s, color .25s, filter .25s; }}
.stButton > button:active, .stDownloadButton > button:active {{ transform: scale(.97); }}
.stButton > button[kind="secondary"]:hover, .stDownloadButton > button[kind="secondary"]:hover {{
  border-color: var(--sd-violet); color: var(--sd-violet); transform: translateY(-1px); }}
.stButton > button[kind="primary"], .stDownloadButton > button[kind="primary"],
.stFormSubmitButton > button[kind="primary"] {{ position: relative; overflow: hidden;
  background: var(--sd-grad); border: none; color: #fff;
  box-shadow: 0 8px 22px -8px rgba(124,58,237,.55); }}
.stButton > button[kind="primary"]::after, .stDownloadButton > button[kind="primary"]::after,
.stFormSubmitButton > button[kind="primary"]::after {{ content: ""; position: absolute; inset: 0;
  background: linear-gradient(110deg, transparent 30%, rgba(255,255,255,.35) 50%, transparent 70%);
  transform: translateX(-120%); transition: transform .7s var(--sd-ease); }}
.stButton > button[kind="primary"]:hover::after, .stDownloadButton > button[kind="primary"]:hover::after,
.stFormSubmitButton > button[kind="primary"]:hover::after {{ transform: translateX(120%); }}
.stButton > button[kind="primary"]:hover, .stFormSubmitButton > button[kind="primary"]:hover {{
  color: #fff; transform: translateY(-1px); box-shadow: 0 12px 28px -8px rgba(124,58,237,.6); }}
.stButton > button:disabled {{ box-shadow: none; filter: grayscale(.3); opacity: .55; }}

/* Champs : halo violet au focus */
[data-baseweb="input"]:focus-within, [data-baseweb="textarea"]:focus-within,
[data-baseweb="select"] > div:focus-within {{ box-shadow: 0 0 0 4px rgba(124,58,237,.15);
  border-color: var(--sd-violet) !important; transition: box-shadow .25s; }}
[data-testid="stFileUploaderDropzone"] {{ border: 1.5px dashed #C4B5FD; background: #FAF8FF;
  border-radius: 1rem; transition: background .3s, border-color .3s, transform .3s var(--sd-ease); }}
[data-testid="stFileUploaderDropzone"]:hover {{ background: #F5F3FF; border-color: var(--sd-violet);
  transform: translateY(-1px); }}

/* Onglets : soulignement en dégradé */
.stTabs [data-baseweb="tab-list"] {{ gap: .3rem; }}
.stTabs [data-baseweb="tab"] {{ border-radius: .6rem .6rem 0 0; transition: color .25s, background .25s; }}
.stTabs [data-baseweb="tab"]:hover {{ background: #F5F3FF; color: var(--sd-violet); }}
.stTabs [data-baseweb="tab-highlight"] {{ background: var(--sd-grad); height: 3px; border-radius: 3px; }}
.stTabs [data-baseweb="tab-panel"] {{ animation: sd-fade .4s var(--sd-ease); }}

/* Barre de progression : dégradé à rayures animées */
[data-testid="stProgress"] > div > div > div > div {{
  background-image: linear-gradient(90deg, {VIOLET}, {MAGENTA}),
    linear-gradient(45deg, rgba(255,255,255,.25) 25%, transparent 25%, transparent 50%,
                    rgba(255,255,255,.25) 50%, rgba(255,255,255,.25) 75%, transparent 75%);
  background-blend-mode: overlay; background-size: 100% 100%, 28px 28px;
  animation: sd-stripes 1s linear infinite; }}
@keyframes sd-stripes {{ to {{ background-position: 0 0, 28px 0; }} }}

/* ---------- Étapes de génération ---------- */
.sd-steps {{ display: flex; gap: .5rem; margin: .4rem 0 1rem; flex-wrap: wrap; }}
.sd-step {{ flex: 1 1 120px; display: flex; align-items: center; gap: .55rem; padding: .7rem .8rem;
  border-radius: .9rem; border: 1px solid var(--sd-line); background: #fff; color: var(--sd-muted);
  font-size: .88rem; font-weight: 500; transition: all .4s var(--sd-ease); }}
.sd-step .n {{ flex: none; width: 1.7rem; height: 1.7rem; border-radius: 50%; display: inline-flex;
  align-items: center; justify-content: center; font-weight: 700; font-size: .8rem;
  background: #F1F5F9; color: #94A3B8; transition: all .4s var(--sd-ease); }}
.sd-step small {{ display: block; font-size: .74rem; color: #94A3B8; }}
.sd-step.done {{ color: #065F46; border-color: #A7F3D0; background: #F0FDF4; }}
.sd-step.done .n {{ background: #10B981; color: #fff; }}
.sd-step.active {{ color: var(--sd-ink); border-color: #C4B5FD; background: #FAF8FF;
  box-shadow: 0 10px 26px -14px rgba(124,58,237,.6); transform: translateY(-2px); }}
.sd-step.active .n {{ background: var(--sd-grad); color: #fff; animation: sd-ping 1.6s infinite; }}

/* ---------- Barre latérale indigo ---------- */
[data-testid="stSidebar"] {{ background: radial-gradient(120% 60% at 0% 0%, #312E81 0%, #1E1B4B 55%) !important; }}
[data-testid="stSidebar"] .sd-brand {{ display: flex; align-items: center; gap: .6rem;
  font-weight: 700; font-size: 1.2rem; color: #fff; padding: .3rem 0 1.1rem; }}
[data-testid="stSidebar"] .sd-brand .logo {{ display: inline-flex; width: 2rem; height: 2rem;
  border-radius: .6rem; align-items: center; justify-content: center; color: #fff;
  background: var(--sd-grad); box-shadow: 0 6px 18px -6px rgba(217,70,239,.7);
  animation: sd-spin-in .9s var(--sd-ease); }}
@keyframes sd-spin-in {{ from {{ transform: rotate(-90deg) scale(.5); opacity: 0; }} }}
[data-testid="stSidebar"] .sd-user {{ display: flex; align-items: center; gap: .6rem; color: #C7D2FE;
  font-size: .85rem; padding: .6rem .7rem; border-radius: .8rem; background: rgba(255,255,255,.06);
  margin-bottom: .8rem; }}
[data-testid="stSidebar"] .sd-user .avatar {{ width: 2rem; height: 2rem; border-radius: 50%;
  display: inline-flex; align-items: center; justify-content: center; font-weight: 700;
  color: #fff; background: var(--sd-grad); }}
[data-testid="stSidebar"] .sd-user b {{ color: #fff; display: block; font-size: .92rem; }}
[data-testid="stSidebar"] a[data-testid="stPageLink-NavLink"] {{ border-radius: .7rem; padding: .45rem .7rem;
  transition: background .25s, transform .25s var(--sd-ease); }}
[data-testid="stSidebar"] a[data-testid="stPageLink-NavLink"]:hover {{ background: rgba(255,255,255,.08);
  transform: translateX(3px); }}
/* Notifications */
[data-testid="stToast"] {{ border-radius: 1rem; border: 1px solid #EDE9FE;
  box-shadow: 0 20px 40px -20px rgba(76,29,149,.45); }}

/* Moins de mouvement si le système le demande */
@media (prefers-reduced-motion: reduce) {{
  *, *::before, *::after {{ animation: none !important; transition: none !important; }}
  .sd-num.count {{ --sd-num: var(--sd-target); }}
}}
</style>
"""

BADGES = {"ready": "Prête", "outline": "Plan à valider", "generating": "En cours",
          "failed": "Échec"}


def apply() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def esc(text) -> str:
    return html.escape(str(text))


def page_header(title: str, subtitle: str = "") -> None:
    st.markdown(f'<h1 class="sd-page-title">{esc(title)}</h1>', unsafe_allow_html=True)
    if subtitle:
        st.markdown(f'<div class="sd-subtitle">{esc(subtitle)}</div>', unsafe_allow_html=True)


def card(icon: str, title: str, text: str) -> None:
    st.markdown(f'<div class="sd-card"><span class="sd-icon">{icon}</span>'
                f'<h4>{esc(title)}</h4><p>{esc(text)}</p></div>', unsafe_allow_html=True)


def stat(value, label: str, icon: str = "") -> None:
    """Carte de statistique ; un entier défile de 0 à sa valeur."""
    if isinstance(value, int) and value >= 0:
        number = f'<div class="sd-num count" style="--sd-target:{value}"></div>'
    else:
        number = f'<div class="sd-num">{esc(value)}</div>'
    icon_html = f'<span class="sd-icon">{icon}</span>' if icon else ""
    st.markdown(f'<div class="sd-card sd-stat">{icon_html}<div>{number}'
                f'<div class="sd-stat-label">{esc(label)}</div></div></div>',
                unsafe_allow_html=True)


def badge(status: str) -> str:
    return f'<span class="sd-badge {esc(status)}">{esc(BADGES.get(status, status))}</span>'


def banner(title: str, text: str) -> None:
    st.markdown(f'<div class="sd-banner"><h2>{esc(title)}</h2><p>{esc(text)}</p></div>',
                unsafe_allow_html=True)


STEPS = [("Lecture", "du document"), ("Plan", "des slides"), ("Rédaction", "puces et notes"),
         ("Mise en page", "PPTX et visuels"), ("Export", "PDF")]


def steps_html(current: int, detail: str = "", steps=STEPS) -> str:
    """Étapes de génération : terminées (✓), en cours (pulsée), à venir."""
    items = []
    for i, (name, sub) in enumerate(steps, start=1):
        state = "done" if i < current else "active" if i == current else ""
        mark = "✓" if i < current else str(i)
        small = esc(detail) if i == current and detail else esc(sub)
        items.append(f'<div class="sd-step {state}"><span class="n">{mark}</span>'
                     f'<div>{esc(name)}<small>{small}</small></div></div>')
    return f'<div class="sd-steps">{"".join(items)}</div>'


def active_link(url_path: str) -> None:
    """Met en valeur le lien de la page courante dans la barre latérale."""
    href = url_path or ""
    st.markdown(f"""<style>
[data-testid="stSidebar"] a[data-testid="stPageLink-NavLink"][href="{esc(href)}"] {{
  background: linear-gradient(90deg, rgba(124,58,237,.55), rgba(217,70,239,.35));
  box-shadow: inset 3px 0 0 #F0ABFC; }}
[data-testid="stSidebar"] a[data-testid="stPageLink-NavLink"][href="{esc(href)}"] span {{
  color: #fff; font-weight: 600; }}
</style>""", unsafe_allow_html=True)


def brand(user_name: str | None = None) -> None:
    with st.sidebar:
        st.markdown('<div class="sd-brand"><span class="logo">✦</span>SmartDeck</div>',
                    unsafe_allow_html=True)
        if user_name:
            initials = "".join(w[0] for w in user_name.split()[:2]).upper() or "?"
            st.markdown(f'<div class="sd-user"><span class="avatar">{esc(initials)}</span>'
                        f'<div><b>{esc(user_name)}</b>Espace personnel</div></div>',
                        unsafe_allow_html=True)


def hero_html() -> str:
    """Accueil : titre en dégradé animé et trois slides qui flottent (survol : elles s'écartent)."""
    return """
<div class="sd-hero">
  <span class="sd-eyebrow"><span class="dot"></span>SmartDeck · 100 % local</span>
  <h1>De vos documents à des<br><span class="sd-gradient">slides réussies.</span></h1>
  <p>Transformez un texte, un PDF ou une image en présentation structurée : plan,
  graphiques, diagrammes et notes orateur. Tout reste sur votre PC.</p>
  <div class="sd-stage">
    <div class="sd-mock m1"><div class="bar title"></div><div class="bar"></div>
      <div class="bar" style="width:80%"></div><div class="bar" style="width:65%"></div></div>
    <div class="sd-mock m2"><div class="bar title"></div>
      <div class="bars"><span style="height:45%"></span><span style="height:62%;animation-delay:-.6s"></span>
      <span style="height:78%;animation-delay:-1.2s"></span><span style="height:100%;animation-delay:-1.8s"></span></div></div>
    <div class="sd-mock m3"><div class="bar title"></div><div class="bar" style="width:90%"></div>
      <div class="bar" style="width:70%"></div><div class="bar" style="width:84%"></div></div>
  </div>
</div>"""
