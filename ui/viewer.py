"""Visionneuse de slides interactive (HTML + JavaScript dans un cadre isolé).

Slide en grand avec transition, boutons et flèches du clavier (← →, Début, Fin),
bande de miniatures cliquables, compteur, notes orateur, lecture automatique
(diaporama) et plein écran. Les images sont intégrées en base64 : rien n'est
chargé depuis Internet (NFR-01).
"""
import base64
import html
import json

import streamlit.components.v1 as components

TEMPLATE = """<!doctype html><html><head><meta charset="utf-8"><style>
@font-face { font-family: Outfit; src: url("/app/static/fonts/Outfit.ttf"); font-weight: 100 900; }
* { box-sizing: border-box; margin: 0; }
body { font-family: Outfit, "Segoe UI", sans-serif; color: #1A1A3D; background: transparent; }
.wrap { border: 1px solid #E2E8F0; border-radius: 18px; background: linear-gradient(180deg,#FAF8FF,#fff);
  padding: 14px; box-shadow: 0 8px 24px -12px rgba(26,26,61,.18); }
.wrap:fullscreen { background: #0F0D2A; border: 0; border-radius: 0; padding: 24px;
  display: flex; flex-direction: column; justify-content: center; }
.wrap:fullscreen .notes, .wrap:fullscreen .thumbs { display: none; }
.stage { position: relative; aspect-ratio: 16/9; max-height: __MAXH__px; margin: 0 auto;
  border-radius: 12px; overflow: hidden; background: #fff; box-shadow: 0 24px 50px -28px rgba(76,29,149,.55); }
.wrap:fullscreen .stage { max-height: 88vh; }
.stage img { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: contain;
  opacity: 0; transform: scale(1.015); transition: opacity .45s ease, transform .6s cubic-bezier(.2,.8,.2,1); }
.stage img.on { opacity: 1; transform: none; }
.nav { position: absolute; top: 50%; translate: 0 -50%; width: 42px; height: 42px; border: 0;
  border-radius: 50%; background: rgba(255,255,255,.92); color: #7C3AED; font-size: 20px; cursor: pointer;
  box-shadow: 0 6px 18px -6px rgba(26,26,61,.4); opacity: 0; transition: opacity .25s, transform .2s; }
.stage:hover .nav { opacity: 1; }
.nav:hover { transform: scale(1.08); }
.nav.prev { left: 12px; } .nav.next { right: 12px; }
.bar { display: flex; align-items: center; gap: 10px; margin: 12px 2px 10px; }
.count { font-weight: 600; font-variant-numeric: tabular-nums; min-width: 64px; }
.title { flex: 1; color: #475569; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.btn { border: 1px solid #E2E8F0; background: #fff; border-radius: 10px; padding: 7px 12px;
  font: inherit; font-size: 13px; font-weight: 600; color: #1A1A3D; cursor: pointer;
  transition: border-color .2s, color .2s, transform .15s; }
.btn:hover { border-color: #7C3AED; color: #7C3AED; } .btn:active { transform: scale(.96); }
.btn.on { background: linear-gradient(90deg,#7C3AED,#D946EF); color: #fff; border-color: transparent; }
.progress { height: 4px; border-radius: 4px; background: #EDE9FE; overflow: hidden; margin: 0 2px 10px; }
.progress div { height: 100%; width: 0; background: linear-gradient(90deg,#7C3AED,#D946EF);
  transition: width .45s cubic-bezier(.2,.8,.2,1); }
.thumbs { display: flex; gap: 8px; overflow-x: auto; padding: 4px 2px 8px; scroll-behavior: smooth; }
.thumbs img { height: 62px; aspect-ratio: 16/9; object-fit: cover; border-radius: 7px; cursor: pointer;
  border: 2px solid transparent; opacity: .55; transition: opacity .25s, border-color .25s, transform .25s; }
.thumbs img:hover { opacity: .9; transform: translateY(-2px); }
.thumbs img.on { opacity: 1; border-color: #7C3AED; box-shadow: 0 6px 14px -6px rgba(124,58,237,.6); }
.notes { margin-top: 6px; padding: 10px 14px; border-radius: 12px; background: #F5F3FF;
  color: #3B3680; font-size: 14px; line-height: 1.5; min-height: 46px; }
.notes b { color: #7C3AED; font-size: 12px; letter-spacing: .08em; text-transform: uppercase; }
.notes.hide { display: none; }
@media (prefers-reduced-motion: reduce) { * { transition: none !important; } }
</style></head><body>
<div class="wrap" id="wrap" tabindex="0">
  <div class="stage" id="stage">__SLIDES__
    <button class="nav prev" id="prev" aria-label="Slide précédente">‹</button>
    <button class="nav next" id="next" aria-label="Slide suivante">›</button>
  </div>
  <div class="bar">
    <span class="count" id="count"></span><span class="title" id="title"></span>
    <button class="btn" id="play" title="Lecture automatique (espace)">▶ Diaporama</button>
    <button class="btn on" id="notesBtn" title="Notes orateur (N)">Notes</button>
    <button class="btn" id="full" title="Plein écran (F)">⛶ Plein écran</button>
  </div>
  <div class="progress"><div id="prog"></div></div>
  <div class="thumbs" id="thumbs">__THUMBS__</div>
  <div class="notes" id="notes"></div>
</div>
<script>
const data = __DATA__;
const slides = [...document.querySelectorAll('.stage img')];
const thumbs = [...document.querySelectorAll('.thumbs img')];
let i = 0, timer = null;
function show(n) {
  i = (n + slides.length) % slides.length;
  slides.forEach((s, k) => s.classList.toggle('on', k === i));
  thumbs.forEach((t, k) => t.classList.toggle('on', k === i));
  thumbs[i].scrollIntoView({block: 'nearest', inline: 'center'});
  document.getElementById('count').textContent = (i + 1) + ' / ' + slides.length;
  document.getElementById('title').textContent = data.titles[i];
  document.getElementById('notes').innerHTML = '<b>Notes orateur</b><br>' + (data.notes[i] || '—');
  document.getElementById('prog').style.width = ((i + 1) / slides.length * 100) + '%';
}
function play(on) {
  clearInterval(timer); timer = null;
  const b = document.getElementById('play');
  if (on) { timer = setInterval(() => show(i + 1), 4000); b.textContent = '❚❚ Pause'; b.classList.add('on'); }
  else { b.textContent = '▶ Diaporama'; b.classList.remove('on'); }
}
document.getElementById('prev').onclick = () => show(i - 1);
document.getElementById('next').onclick = () => show(i + 1);
document.getElementById('play').onclick = () => play(!timer);
document.getElementById('notesBtn').onclick = (e) => {
  e.currentTarget.classList.toggle('on'); document.getElementById('notes').classList.toggle('hide'); };
document.getElementById('full').onclick = () => {
  const w = document.getElementById('wrap');
  if (document.fullscreenElement) document.exitFullscreen();
  else if (w.requestFullscreen) w.requestFullscreen().catch(() => {});
};
thumbs.forEach((t, k) => t.onclick = () => show(k));
document.addEventListener('keydown', (e) => {
  if (e.key === 'ArrowRight' || e.key === 'PageDown') show(i + 1);
  else if (e.key === 'ArrowLeft' || e.key === 'PageUp') show(i - 1);
  else if (e.key === 'Home') show(0);
  else if (e.key === 'End') show(slides.length - 1);
  else if (e.key === ' ') { e.preventDefault(); play(!timer); }
  else if (e.key === 'f' || e.key === 'F') document.getElementById('full').click();
  else if (e.key === 'n' || e.key === 'N') document.getElementById('notesBtn').click();
});
let x0 = null;  // balayage tactile
document.getElementById('stage').addEventListener('touchstart', e => x0 = e.touches[0].clientX);
document.getElementById('stage').addEventListener('touchend', e => {
  if (x0 === null) return; const dx = e.changedTouches[0].clientX - x0;
  if (Math.abs(dx) > 40) show(i + (dx < 0 ? 1 : -1)); x0 = null; });
show(data.start);
</script></body></html>"""


def _src(png: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(png).decode("ascii")


def slide_viewer(images: list[bytes], titles: list[str], notes: list[str], start: int = 0,
                 max_height: int = 520) -> None:
    if not images:
        return
    slides = "".join(f'<img src="{_src(p)}" alt="Slide {k + 1}">' for k, p in enumerate(images))
    thumbs = "".join(f'<img src="{_src(p)}" alt="Miniature {k + 1}" title="{html.escape(t)}">'
                     for k, (p, t) in enumerate(zip(images, titles)))
    data = json.dumps({"titles": titles, "notes": [html.escape(n) for n in notes],
                       "start": min(max(start, 0), len(images) - 1)}, ensure_ascii=False)
    page = (TEMPLATE.replace("__SLIDES__", slides).replace("__THUMBS__", thumbs)
            .replace("__DATA__", data.replace("</", "<\\/")).replace("__MAXH__", str(max_height)))
    components.html(page, height=max_height + 270)
