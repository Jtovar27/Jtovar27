#!/usr/bin/env python3
"""Build the animated RuutDev-style images used by the GitHub profile README.

Run from the repository root:

    pip install fonttools==4.67.0 brotli==1.2.1 uharfbuzz==0.57.0
    python tools/build_assets.py

Everything it draws comes from tools/profile.json. All text is turned into vector
outlines, so the images look the same on every device and never depend on an
outside service.
"""
import io
import json
import random
import re
from pathlib import Path

import uharfbuzz as hb
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"
OUT = ROOT / "assets"
DATA = json.loads((TOOLS / "profile.json").read_text(encoding="utf-8"))
random.seed(27)

# ---------------------------------------------------------------- RuutDev palette
NAVY = "#00001A"      # logo background
TILE = "#070B2C"      # raised surface on navy
EDGE = "#1A2052"      # hairline borders
LIME = "#B4FB0C"      # logo dot
LIME_L = "#B9FF05"
LIME_R = "#A6EF1A"
BLUE = "#0A5CFF"      # glow behind the R
WHITE = "#FFFFFF"
MUTED = "#9AA1C6"
FAINT = "#545A88"


# ---------------------------------------------------------------- fonts
class Font:
    def __init__(self, file, key):
        tt = TTFont(str(TOOLS / "fonts" / file))
        tt.flavor = None
        buf = io.BytesIO()
        tt.save(buf)
        data = buf.getvalue()
        self.tt = TTFont(io.BytesIO(data))
        self.key = key
        self.upem = self.tt["head"].unitsPerEm
        self.gs = self.tt.getGlyphSet()
        self.order = self.tt.getGlyphOrder()
        self.cmap = self.tt.getBestCmap()
        self.hb = hb.Font(hb.Face(data))
        self._paths = {}

    def shape(self, text, size, tracking=0.0):
        buf = hb.Buffer()
        buf.add_str(text)
        buf.guess_segment_properties()
        hb.shape(self.hb, buf, {"kern": True, "liga": False})
        s = size / self.upem
        x, out = 0.0, []
        for info, pos in zip(buf.glyph_infos, buf.glyph_positions):
            out.append((self.order[info.codepoint], x + pos.x_offset * s, pos.y_offset * s))
            x += pos.x_advance * s + tracking
        return out, (x - tracking if out else 0.0)

    def width(self, text, size, tracking=0.0):
        return self.shape(text, size, tracking)[1]

    def advance(self, gname, size):
        return self.tt["hmtx"][gname][0] * size / self.upem

    def path(self, gname):
        if gname not in self._paths:
            pen = SVGPathPen(self.gs, ntos=lambda v: str(int(round(v))))
            self.gs[gname].draw(pen)
            self._paths[gname] = pen.getCommands()
        return self._paths[gname]


F = {
    "i500": Font("inter-500.woff2", "a"),
    "i600": Font("inter-600.woff2", "b"),
    "i700": Font("inter-700.woff2", "c"),
    "i800": Font("inter-800.woff2", "d"),
    "i900": Font("inter-900.woff2", "e"),
    "m500": Font("jetbrains-mono-500.woff2", "f"),
    "m700": Font("jetbrains-mono-700.woff2", "g"),
}


# ---------------------------------------------------------------- svg document
class Doc:
    """Collects glyph outlines once in <defs> and places them with <use>."""

    def __init__(self, w, h, label):
        self.w, self.h, self.label = w, h, label
        self.glyphs = {}
        self.defs = []
        self.body = []
        self.css = []
        self.uid = 0

    def id(self, prefix):
        self.uid += 1
        return f"{prefix}{self.uid}"

    def add(self, s):
        self.body.append(s)

    def glyph_id(self, font, gname):
        gid = font.key + re.sub(r"[^A-Za-z0-9]", "_", gname)
        if gid not in self.glyphs:
            self.glyphs[gid] = font.path(gname)
        return gid

    def glyph_use(self, font, gname, size, x, y, extra=""):
        if not font.path(gname):
            return ""
        k = size / font.upem
        gid = self.glyph_id(font, gname)
        return f'<use href="#{gid}" transform="matrix({k:.5f} 0 0 {-k:.5f} {x:.1f} {y:.1f})"{extra}/>'

    def text(self, font, s, size, x, y, fill=None, tracking=0.0, anchor="start", attrs=""):
        glyphs, adv = font.shape(s, size, tracking)
        if anchor == "end":
            x -= adv
        elif anchor == "middle":
            x -= adv / 2
        uses = "".join(self.glyph_use(font, g, size, x + gx, y - gy) for g, gx, gy in glyphs)
        f = f' fill="{fill}"' if fill else ""
        return f"<g{f}{attrs}>{uses}</g>", adv

    def letters(self, font, s, size, x, y, tracking=0.0):
        """One <use> per visible glyph, for per-letter animation."""
        glyphs, adv = font.shape(s, size, tracking)
        out = []
        for g, gx, gy in glyphs:
            u = self.glyph_use(font, g, size, x + gx, y - gy)
            if u:
                out.append((u, x + gx, font.advance(g, size)))
        return out, adv

    def write(self, name):
        glyph_defs = "".join(f'<path id="{k}" d="{v}"/>' for k, v in self.glyphs.items())
        css = "".join(self.css)
        svg = (
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {self.w} {self.h}" '
            f'width="{self.w}" height="{self.h}" role="img" aria-label="{esc(self.label)}">'
            f"<title>{esc(self.label)}</title>"
            f"<style>{css}</style>"
            f"<defs>{glyph_defs}{''.join(self.defs)}</defs>"
            + "".join(self.body)
            + "</svg>\n"
        )
        path = OUT / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(svg, encoding="utf-8")
        return path, len(svg)


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def wrap(font, text, size, max_w):
    words, lines, cur = text.split(), [], ""
    for w in words:
        trial = f"{cur} {w}".strip()
        if font.width(trial, size) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


# ---------------------------------------------------------------- icons
def _lucide_inner(name):
    raw = (TOOLS / "icons" / "lucide" / f"{name}.svg").read_text()
    body = re.search(r"<svg[^>]*>(.*)</svg>", raw, re.S).group(1)
    return " ".join(re.sub(r"<!--.*?-->", "", body, flags=re.S).split())


def _simple_path(name):
    raw = (TOOLS / "icons" / "simple" / f"{name}.svg").read_text()
    return re.search(r'<path d="([^"]+)"', raw).group(1)


LINKEDIN = (
    '<rect x="2.5" y="2.5" width="19" height="19" rx="4.5"/>'
    '<path d="M8 10.6V17M12 17V10.6M12 13.4c0-1.8 1.2-2.9 2.7-2.9 1.6 0 2.4 1.1 2.4 2.9V17"/>'
    '<circle cx="8" cy="7.7" r=".6" fill="currentColor"/>'
)


def icon(spec, x, y, size, color, stroke=2.0):
    kind, name = spec.split(":")
    k = size / 24
    if kind == "simple":
        return f'<path transform="translate({x:.1f} {y:.1f}) scale({k:.4f})" fill="{color}" d="{_simple_path(name)}"/>'
    body = LINKEDIN if (kind, name) == ("custom", "linkedin") else _lucide_inner(name)
    return (
        f'<g transform="translate({x:.1f} {y:.1f}) scale({k:.4f})" fill="none" stroke="{color}" color="{color}" '
        f'stroke-width="{stroke}" stroke-linecap="round" stroke-linejoin="round">{body}</g>'
    )


# ---------------------------------------------------------------- RuutDev logo
# Traced from the official mark: a 535-unit square R and a lime dot to its left.
R_PATH = (
    "M0 0H438A97 97 0 0 1 535 97V223A97 97 0 0 1 438 320H321L428 427H535V535H407"
    "Q385 535 369 519L170 320H106V535H0ZM106 105V215H429V105Z"
)
LOGO_W = 959.6  # dot left edge to R right edge, in R units


def logo(doc, x, y, h, glow=1.0, cls=""):
    """Draw the RuutDev mark with its glows. x,y = top-left, h = height of the R."""
    k = h / 535
    rx = x + 424.6 * k
    cx, cy, r = x + 141.8 * k, y + 254.3 * k, 141.8 * k
    fb1, fb2, fg = doc.id("fb"), doc.id("fb"), doc.id("lg")
    doc.defs.append(
        f'<filter id="{fb1}" x="-80%" y="-80%" width="260%" height="260%"><feGaussianBlur stdDeviation="16"/></filter>'
        f'<filter id="{fb2}" x="-120%" y="-120%" width="340%" height="340%"><feGaussianBlur stdDeviation="48"/></filter>'
        f'<linearGradient id="{fg}" x1="0" x2="1"><stop offset="0" stop-color="{LIME_L}"/><stop offset="1" stop-color="{LIME_R}"/></linearGradient>'
    )
    rt = f'transform="translate({rx:.2f} {y:.2f}) scale({k:.5f})"'
    dt = f'transform="translate({cx:.2f} {cy:.2f}) scale({k:.5f})"'
    parts = []
    if glow:
        parts += [
            f'<path {rt} d="{R_PATH}" fill-rule="evenodd" fill="{BLUE}" opacity="{0.55 * glow:.2f}" filter="url(#{fb2})"/>',
            f'<path {rt} d="{R_PATH}" fill-rule="evenodd" fill="{BLUE}" opacity="{0.95 * glow:.2f}" filter="url(#{fb1})"/>',
            f'<circle {dt} r="141.8" fill="#2BD600" opacity="{0.35 * glow:.2f}" filter="url(#{fb2})"/>',
            f'<circle {dt} r="141.8" fill="{LIME}" opacity="{0.6 * glow:.2f}" filter="url(#{fb1})"/>',
        ]
    parts += [
        f'<circle {dt} r="141.8" fill="url(#{fg})"/>',
        f'<path {rt} d="{R_PATH}" fill-rule="evenodd" fill="{WHITE}"/>',
    ]
    c = f' class="{cls}"' if cls else ""
    return f"<g{c}>{''.join(parts)}</g>", LOGO_W * k


def lime_dot(doc, cx, cy, r, cls=""):
    fb, fg = doc.id("fb"), doc.id("lg")
    doc.defs.append(
        f'<filter id="{fb}" x="-150%" y="-150%" width="400%" height="400%"><feGaussianBlur stdDeviation="{r * 0.6:.1f}"/></filter>'
        f'<linearGradient id="{fg}" x1="0" x2="1"><stop offset="0" stop-color="{LIME_L}"/><stop offset="1" stop-color="{LIME_R}"/></linearGradient>'
    )
    c = f' class="{cls}"' if cls else ""
    return (
        f'<g{c}><circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r:.1f}" fill="{LIME}" opacity=".55" filter="url(#{fb})"/>'
        f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r:.1f}" fill="url(#{fg})"/></g>'
    )


# ---------------------------------------------------------------- shared pieces
# Every element's resting style is its final, visible state. Animations only add the
# entrance (fill-mode "both"), so any viewer that does not run animations still shows
# the complete image.
BASE_CSS = (
    ".rise{animation:rise .8s cubic-bezier(.2,.8,.2,1) both}"
    "@keyframes rise{from{opacity:0;transform:translateY(8px)}}"
    ".fade{animation:fade .7s ease both}"
    "@keyframes fade{from{opacity:0}}"
    ".up{transform-box:fill-box;animation:up .7s cubic-bezier(.2,.85,.2,1) both}"
    "@keyframes up{from{transform:translateY(118%)}}"
    ".pop{transform-box:fill-box;transform-origin:center;animation:pop .45s cubic-bezier(.3,1.6,.5,1) both}"
    "@keyframes pop{from{transform:scale(0)}}"
    ".sweep{transform-box:fill-box;transform-origin:left;transform:scaleX(0);animation:sweep 1.1s cubic-bezier(.7,0,.2,1) both}"
    "@keyframes sweep{0%{transform:scaleX(0);transform-origin:left}45%{transform:scaleX(1);transform-origin:left}"
    "46%{transform:scaleX(1);transform-origin:right}100%{transform:scaleX(0);transform-origin:right}}"
    ".grow{transform-box:fill-box;transform-origin:left;animation:grow .6s cubic-bezier(.2,.8,.2,1) both}"
    "@keyframes grow{from{transform:scaleX(0)}}"
    ".blink{animation:blink 1s steps(1) infinite}"
    "@keyframes blink{50%{opacity:0}}"
    ".breathe{animation:breathe 4s ease-in-out infinite}"
    "@keyframes breathe{50%{opacity:.55}}"
    ".ping{transform-box:fill-box;transform-origin:center;opacity:0;animation:ping 2.6s cubic-bezier(.2,.6,.3,1) infinite}"
    "@keyframes ping{0%{transform:scale(1);opacity:.7}80%,100%{transform:scale(1.9);opacity:0}}"
    "@media (prefers-reduced-motion:reduce){*{animation:none!important}}"
)


def card(doc, w, h, rx=18, glow_at=(0.92, 0.05), glow_op=0.20):
    rg, cp = doc.id("rg"), doc.id("cp")
    doc.defs.append(
        f'<radialGradient id="{rg}" cx="{glow_at[0]}" cy="{glow_at[1]}" r=".75">'
        f'<stop offset="0" stop-color="{BLUE}" stop-opacity="{glow_op}"/><stop offset="1" stop-color="{BLUE}" stop-opacity="0"/></radialGradient>'
        f'<clipPath id="{cp}"><rect width="{w}" height="{h}" rx="{rx}"/></clipPath>'
    )
    doc.add(
        f'<rect width="{w}" height="{h}" rx="{rx}" fill="{NAVY}"/>'
        f'<rect width="{w}" height="{h}" fill="url(#{rg})" clip-path="url(#{cp})"/>'
        f'<rect x=".75" y=".75" width="{w - 1.5}" height="{h - 1.5}" rx="{rx - 0.75}" fill="none" stroke="{EDGE}" stroke-width="1.5"/>'
    )


def delay(t):
    return f' style="animation-delay:{t:.2f}s"'


# ---------------------------------------------------------------- header (decrypt)
def build_header():
    W, H, MX = 1200, 380, 64
    d = Doc(W, H, f"{DATA['name'].title()}. {DATA['subtitle'].replace('  ·  ', ', ')}")
    d.css.append(BASE_CSS)
    card(d, W, H, glow_op=0.24)

    # HUD corners
    L, I = 22, 22
    for cx, cy, dx, dy in [(I, I, 1, 1), (W - I, I, -1, 1), (I, H - I, 1, -1), (W - I, H - I, -1, -1)]:
        d.add(f'<path class="fade" d="M{cx} {cy + dy * L}V{cy}H{cx + dx * L}" fill="none" stroke="{LIME}" stroke-opacity=".5" stroke-width="2"/>')

    # brand row
    mark, mw = logo(d, MX, 54, 26, glow=0.8, cls="fade")
    d.add(mark)
    t, _ = d.text(F["i600"], "RUUTDEV", 13, MX + mw + 14, 72, MUTED, 3.2, attrs=' class="fade"')
    d.add(t)
    t, _ = d.text(F["m500"], DATA["handle"], 15, W - MX, 72, FAINT, anchor="end", attrs=' class="fade"')
    d.add(t)

    # name: each letter decrypts through random glyphs, then locks in white
    name, size, base = DATA["name"], 118, 212
    font = F["i900"]
    nw = font.width(name, size, -2)
    dot_r = size * 0.085
    if nw + 6 + 2 * dot_r > W - 2 * MX:
        size *= (W - 2 * MX) / (nw + 6 + 2 * dot_r)
        nw, dot_r = font.width(name, size, -2), size * 0.085
    pool = list("ABCDEFGHKMNPRSUVWXYZ0123456789#$%&@")
    FRAME = 0.055
    glyphs, _ = font.shape(name, size, -2)
    letters = [(g, gx) for g, gx, _ in glyphs if font.path(g)]
    end = 0.0
    for i, (g, gx) in enumerate(letters):
        start, frames = 0.35 + i * 0.06, 7 + i
        adv_final = font.advance(g, size)
        for f in range(frames):
            rg = font.cmap[ord(random.choice(pool))]
            ox = (adv_final - font.advance(rg, size)) / 2
            op = 0.55 + 0.45 * f / frames
            d.add(d.glyph_use(font, rg, size, MX + gx + ox, base, f' fill="{LIME}" opacity="0"')[:-2]
                  + f'><set attributeName="opacity" to="{op:.2f}" begin="{start + f * FRAME:.3f}s" dur="{FRAME}s"/></use>')
        lock = start + frames * FRAME
        end = max(end, lock)
        # visible by default; hidden only while its scramble plays
        d.add(d.glyph_use(font, g, size, MX + gx, base, f' fill="{WHITE}"')[:-2]
              + f'><set attributeName="opacity" to="0" begin="0s" dur="{lock:.3f}s"/></use>')
    d.add(lime_dot(d, MX + nw + 6 + dot_r, base - dot_r, dot_r, cls="pop").replace('class="pop"', f'class="pop"{delay(end + 0.05)}'))

    # subtitle + divider
    t, _ = d.text(F["i600"], DATA["subtitle"], 19, MX + 2, 260, MUTED, 3.0, attrs=f' class="rise"{delay(end - 0.2)}')
    d.add(t)
    fg = d.id("fd")
    d.defs.append(f'<linearGradient id="{fg}" x1="0" x2="1"><stop offset="0" stop-color="{LIME}" stop-opacity=".55"/><stop offset="1" stop-color="{LIME}" stop-opacity="0"/></linearGradient>')
    d.add(f'<rect class="grow"{delay(end)} x="{MX}" y="288" width="{W - 2 * MX}" height="1.5" fill="url(#{fg})"/>')

    # terminal line that types, holds and deletes each message
    TY, TS = 336, 21
    mono = F["m500"]
    t, padv = d.text(mono, "$", TS, MX, TY, LIME, attrs=f' class="fade"{delay(end)}')
    d.add(t)
    tx = MX + padv + 14
    cw = mono.advance(mono.cmap[ord("M")], TS)
    lines = DATA["terminal"]
    TYPE, HOLD, DEL, GAP = 0.05, 2.3, 0.02, 0.35
    events, t0 = [], 0.0
    for li, line in enumerate(lines):
        n = len(line)
        events += [(t0 + k * TYPE, li, k) for k in range(n + 1)]
        t0 += n * TYPE + HOLD
        events += [(t0 + (n - k) * DEL, li, k) for k in range(n, -1, -1)]
        t0 += n * DEL + GAP
    total = t0
    by_t = {}
    for tt, li, k in events:
        by_t.setdefault(round(tt, 4), []).append((li, k))
    state, timeline = {i: 0 for i in range(len(lines))}, []
    for tt in sorted(by_t):
        for li, k in by_t[tt]:
            state[li] = k
        timeline.append((tt, dict(state)))
    keys = ";".join(f"{tt / total:.5f}" for tt, _ in timeline)
    start = end + 0.4
    first_w = len(lines[0]) * cw
    for li, line in enumerate(lines):
        cid = d.id("tc")
        widths = ";".join(f"{st[li] * cw:.1f}" for _, st in timeline)
        # resting width shows the first line fully typed (the no-animation fallback)
        rest_w = first_w + 4 if li == 0 else 0
        d.defs.append(
            f'<clipPath id="{cid}"><rect x="{tx - 2:.1f}" y="{TY - 28}" width="{rest_w:.1f}" height="40">'
            f'<set attributeName="width" to="0" begin="0s" dur="{start:.2f}s"/>'
            f'<animate attributeName="width" values="{widths}" keyTimes="{keys}" calcMode="discrete" dur="{total:.2f}s" begin="{start:.2f}s" repeatCount="indefinite"/></rect></clipPath>'
        )
        key, _, rest = line.partition(":")
        g1, a1 = d.text(mono, key + ":", TS, tx, TY, LIME)
        g2, _ = d.text(mono, rest, TS, tx + a1, TY, WHITE)
        d.add(f'<g clip-path="url(#{cid})">{g1}{g2}</g>')
    cursor = ";".join(f"{sum(st.values()) * cw:.1f} 0" for _, st in timeline)
    d.add(
        f'<g class="fade"{delay(end)}><g transform="translate({first_w + 2:.1f} 0)"><rect class="blink" x="{tx:.1f}" y="{TY - 19}" width="{cw * 0.62:.1f}" height="24" fill="{LIME}"/>'
        f'<animateTransform attributeName="transform" type="translate" values="0 0" begin="0s" dur="{start:.2f}s"/>'
        f'<animateTransform attributeName="transform" type="translate" values="{cursor}" keyTimes="{keys}" calcMode="discrete" dur="{total:.2f}s" begin="{start:.2f}s" repeatCount="indefinite"/></g></g>'
    )
    return d.write("header.svg")


# ---------------------------------------------------------------- section titles (reveal)
def build_section(key):
    s = DATA["sections"][key]
    W, H = 1200, 112
    d = Doc(W, H, s["title"].title())
    d.css.append(BASE_CSS)
    card(d, W, H, rx=16, glow_at=(0.0, 0.5), glow_op=0.14)
    # icon tile
    d.add(
        f'<g class="pop"{delay(0.15)}><rect x="34" y="26" width="60" height="60" rx="14" fill="{TILE}" stroke="{LIME}" stroke-opacity=".35" stroke-width="1.5"/>'
        + icon(s["icon"], 49, 41, 30, LIME, 2.1) + "</g>"
    )
    # index
    t, _ = d.text(F["m700"], s["index"], 15, 118, 44, LIME, 2, attrs=f' class="fade"{delay(0.2)}')
    d.add(t)
    # title letters rise from behind a mask
    cp = d.id("cp")
    d.defs.append(f'<clipPath id="{cp}"><rect x="110" y="44" width="900" height="44"/></clipPath>')
    lets, tw = d.letters(F["i800"], s["title"], 36, 116, 84, 1.5)
    d.add(f'<g clip-path="url(#{cp})" fill="{WHITE}">' + "".join(f'<g class="up"{delay(0.25 + i * 0.035)}>{u}</g>' for i, (u, _, _) in enumerate(lets)) + "</g>")
    d.add(f'<rect class="sweep"{delay(0.2)} x="116" y="94" width="{tw:.0f}" height="3" fill="{LIME}"/>')
    t, _ = d.text(F["m500"], s["tag"], 17, W - 40, 64, FAINT, anchor="end", attrs=f' class="fade"{delay(0.6)}')
    d.add(t)
    return d.write(f"sections/{key}.svg")


# ---------------------------------------------------------------- current focus (path reveal)
def build_focus():
    rows = DATA["focus"]
    W, PAD, RH = 1200, 44, 88
    H = PAD * 2 + RH * len(rows) - 8
    d = Doc(W, H, "Current focus: " + "; ".join(f"{r['title']} ({r['status'].title()})" for r in rows))
    d.css.append(BASE_CSS)
    card(d, W, H, glow_op=0.16)
    NX = 86
    ys = [PAD + i * RH + 36 for i in range(len(rows))]

    # connecting line, drawn top to bottom
    cid = d.id("cl")
    total_h = ys[-1] - ys[0]
    dur = 0.2 + 0.25 * len(rows)
    d.defs.append(
        f'<clipPath id="{cid}"><rect x="{NX - 4}" y="{ys[0]}" width="8" height="{total_h}">'
        f'<animate attributeName="height" values="0;0;{total_h}" keyTimes="0;{0.2 / dur:.3f};1" begin="0s" dur="{dur:.2f}s" '
        f'calcMode="spline" keySplines="0 0 1 1;.2 .8 .2 1"/></rect></clipPath>'
    )
    segs = []
    for i in range(len(rows) - 1):
        nxt = rows[i + 1]["state"]
        if nxt == "next":
            segs.append(f'<line x1="{NX}" y1="{ys[i] + 28}" x2="{NX}" y2="{ys[i + 1] - 28}" stroke="{FAINT}" stroke-width="2" stroke-dasharray="4 6"/>')
        else:
            segs.append(f'<line x1="{NX}" y1="{ys[i] + 28}" x2="{NX}" y2="{ys[i + 1] - 28}" stroke="{LIME}" stroke-opacity=".7" stroke-width="2"/>')
    d.add(f'<g clip-path="url(#{cid})">{"".join(segs)}</g>')

    for i, (r, y) in enumerate(zip(rows, ys)):
        t0 = 0.2 + i * 0.25
        st = r["state"]
        # node
        if st == "done":
            node = f'<circle cx="{NX}" cy="{y}" r="26" fill="{LIME}"/>' + icon(r["icon"], NX - 12, y - 12, 24, NAVY, 2.3)
        elif st == "active":
            node = (
                f'<circle class="ping"{delay(t0 + 0.6)} cx="{NX}" cy="{y}" r="26" fill="none" stroke="{LIME}" stroke-width="2"/>'
                f'<circle cx="{NX}" cy="{y}" r="26" fill="{TILE}" stroke="{LIME}" stroke-width="2.5"/>'
                + icon(r["icon"], NX - 12, y - 12, 24, LIME, 2.1)
            )
        else:
            node = f'<circle cx="{NX}" cy="{y}" r="26" fill="{NAVY}" stroke="{FAINT}" stroke-width="2" stroke-dasharray="5 5"/>' + icon(r["icon"], NX - 12, y - 12, 24, MUTED, 2.0)
        d.add(f'<g class="pop"{delay(t0)}>{node}</g>')
        # text
        tcol = WHITE if st != "next" else "#D9DCF0"
        t1, _ = d.text(F["i700"], r["title"], 27, 140, y - 2, tcol)
        t2, _ = d.text(F["i500"], r["org"], 17, 140, y + 24, MUTED)
        d.add(f'<g class="rise"{delay(t0 + 0.08)}>{t1}{t2}</g>')
        # status chip
        mono = F["m700"]
        label = r["status"]
        lw = mono.width(label, 14, 1.4)
        cw_ = lw + 36 + (14 if st == "active" else 0)
        x1 = W - 52 - cw_
        if st == "done":
            chip = f'<rect x="{x1:.1f}" y="{y - 17}" width="{cw_:.1f}" height="34" rx="17" fill="{LIME}" fill-opacity=".14" stroke="{LIME}" stroke-opacity=".5"/>'
            tc, tx = LIME, x1 + 18
        elif st == "active":
            chip = (f'<rect x="{x1:.1f}" y="{y - 17}" width="{cw_:.1f}" height="34" rx="17" fill="{TILE}" stroke="{LIME}" stroke-width="1.5"/>'
                    f'<circle class="blink" cx="{x1 + 19:.1f}" cy="{y}" r="4" fill="{LIME}"/>')
            tc, tx = LIME, x1 + 32
        else:
            chip = f'<rect x="{x1:.1f}" y="{y - 17}" width="{cw_:.1f}" height="34" rx="17" fill="none" stroke="{FAINT}" stroke-width="1.5"/>'
            tc, tx = MUTED, x1 + 18
        t3, _ = d.text(mono, label, 14, tx, y + 5, tc, 1.4)
        d.add(f'<g class="rise"{delay(t0 + 0.15)}>{chip}{t3}</g>')
    return d.write("focus.svg")


# ---------------------------------------------------------------- toolkit (staggered reveal)
def build_toolkit():
    groups = DATA["toolkit"]
    W, PAD, TS, PITCH = 1200, 46, 84, 101
    H = PAD * 2 + len(groups) * (24 + TS + 40) + (len(groups) - 1) * 26 - 10
    labels = ", ".join(f"{g['group'].title()}: " + ", ".join(it["label"] for it in g["items"]) for g in groups)
    d = Doc(W, H, "Toolkit. " + labels)
    d.css.append(BASE_CSS)
    card(d, W, H, glow_op=0.14)
    y, n = PAD, 0
    for g in groups:
        t, gw = d.text(F["m700"], g["group"], 14, PAD, y + 12, LIME, 2.2, attrs=f' class="fade"{delay(0.1 + n * 0.03)}')
        d.add(t)
        d.add(f'<rect class="grow"{delay(0.15 + n * 0.03)} x="{PAD + gw + 16:.0f}" y="{y + 6}" width="{W - 2 * PAD - gw - 16:.0f}" height="1" fill="{EDGE}"/>')
        ty = y + 28
        for j, it in enumerate(g["items"]):
            x = PAD + j * PITCH
            tile = (f'<rect x="{x}" y="{ty}" width="{TS}" height="{TS}" rx="18" fill="{TILE}" stroke="{EDGE}" stroke-width="1.5"/>'
                    + icon(it["icon"], x + 22, ty + 22, 40, LIME, 1.9))
            lab, _ = d.text(F["i600"], it["label"], 15, x + TS / 2, ty + TS + 26, MUTED, anchor="middle")
            d.add(f'<g class="rise"{delay(0.2 + n * 0.045)}>{tile}{lab}</g>')
            n += 1
        y = ty + TS + 40 + 26
    return d.write("toolkit.svg")


# ---------------------------------------------------------------- project cards
def build_project(p):
    W, H, PX = 600, 352, 34
    d = Doc(W, H, f"{p['name']}. {p['desc']} Stack: {', '.join(p['stack'])}. Security: {p['security']}")
    d.css.append(BASE_CSS)
    card(d, W, H, glow_op=0.16)
    t, kw = d.text(F["m700"], p["kind"], 13, PX, 52, LIME, 2.0, attrs=f' class="fade"{delay(0.1)}')
    d.add(t)
    d.add(f'<g class="fade"{delay(0.3)}>' + icon("lucide:arrow-up-right", W - PX - 24, 34, 24, MUTED, 2) + "</g>")
    cp = d.id("cp")
    d.defs.append(f'<clipPath id="{cp}"><rect x="{PX - 4}" y="62" width="{W - 2 * PX}" height="40"/></clipPath>')
    lets, tw = d.letters(F["i800"], p["name"], 30, PX, 96, 0)
    d.add(f'<g clip-path="url(#{cp})" fill="{WHITE}">' + "".join(f'<g class="up"{delay(0.15 + i * 0.025)}>{u}</g>' for i, (u, _, _) in enumerate(lets)) + "</g>")
    d.add(f'<rect class="sweep"{delay(0.15)} x="{PX}" y="106" width="{tw:.0f}" height="2.5" fill="{LIME}"/>')
    y = 140
    for line in wrap(F["i500"], p["desc"], 18, W - 2 * PX)[:3]:
        t, _ = d.text(F["i500"], line, 18, PX, y, MUTED, attrs=f' class="rise"{delay(0.35)}')
        d.add(t)
        y += 26
    # stack chips
    x, cy = PX, 222
    chips = []
    for s in p["stack"]:
        w = F["m500"].width(s, 13) + 26
        t, _ = d.text(F["m500"], s, 13, x + 13, cy + 19, WHITE)
        chips.append(f'<rect x="{x:.1f}" y="{cy}" width="{w:.1f}" height="28" rx="14" fill="{TILE}" stroke="{EDGE}" stroke-width="1.5"/>{t}')
        x += w + 8
    d.add(f'<g class="rise"{delay(0.45)}>{"".join(chips)}</g>')
    d.add(f'<rect x="{PX}" y="270" width="{W - 2 * PX}" height="1" fill="{EDGE}"/>')
    sec = [icon("lucide:shield-check", PX, 284, 20, LIME, 2.1)]
    sy = 300
    for line in wrap(F["i500"], p["security"], 15, W - 2 * PX - 30)[:2]:
        t, _ = d.text(F["i500"], line, 15, PX + 30, sy, "#D9DCF0")
        sec.append(t)
        sy += 22
    d.add(f'<g class="rise"{delay(0.55)}>{"".join(sec)}</g>')
    return d.write(f"projects/{p['file']}.svg")


# ---------------------------------------------------------------- content / RuutDev card
def build_content():
    c = DATA["content"]
    W, H = 1200, 300
    d = Doc(W, H, f"RuutDev. {c['tagline']} {c['desc']}")
    d.css.append(BASE_CSS)
    card(d, W, H, glow_at=(0.12, 0.5), glow_op=0.28)
    mark, mw = logo(d, 74, 86, 128, glow=1.0, cls="breathe")
    d.add(f'<g class="fade"{delay(0.1)}>{mark}</g>')
    X = 74 + mw + 70
    cp = d.id("cp")
    d.defs.append(f'<clipPath id="{cp}"><rect x="{X - 4}" y="62" width="700" height="52"/></clipPath>')
    lets, tw = d.letters(F["i900"], c["title"], 46, X, 108, 2)
    d.add(f'<g clip-path="url(#{cp})" fill="{WHITE}">' + "".join(f'<g class="up"{delay(0.2 + i * 0.04)}>{u}</g>' for i, (u, _, _) in enumerate(lets)) + "</g>")
    t, _ = d.text(F["i700"], c["tagline"], 22, X, 150, LIME, attrs=f' class="rise"{delay(0.5)}')
    d.add(t)
    y = 194
    for line in wrap(F["i500"], c["desc"], 18, W - X - 60)[:3]:
        t, _ = d.text(F["i500"], line, 18, X, y, MUTED, attrs=f' class="rise"{delay(0.6)}')
        d.add(t)
        y += 27
    return d.write("content.svg")


# ---------------------------------------------------------------- buttons and fact icons
def build_button(b):
    H = 52
    lw = F["i700"].width(b["label"], 17)
    W = int(18 + 22 + 12 + lw + 22)
    d = Doc(W, H, b["label"])
    d.add(f'<rect x=".75" y=".75" width="{W - 1.5}" height="{H - 1.5}" rx="12" fill="{NAVY}" stroke="{EDGE}" stroke-width="1.5"/>')
    d.add(icon(b["icon"], 18, 15, 22, LIME, 2.1))
    t, _ = d.text(F["i700"], b["label"], 17, 52, 32, WHITE)
    d.add(t)
    return d.write(f"buttons/{b['file']}.svg")


def build_fact(f):
    d = Doc(32, 32, "")
    d.add(f'<rect width="32" height="32" rx="8" fill="{NAVY}"/>')
    d.add(icon(f["icon"], 7, 7, 18, LIME, 2.2))
    return d.write(f"icons/{f['file']}.svg")


def build_logo_icon():
    d = Doc(32, 32, "RuutDev")
    d.add(f'<rect width="32" height="32" rx="8" fill="{NAVY}"/>')
    mark, mw = logo(d, 0, 0, 13, glow=0.9)
    d.add(f'<g transform="translate({(32 - mw) / 2:.2f} 9.5)">{mark}</g>')
    return d.write("icons/ruutdev.svg")


# ---------------------------------------------------------------- footer (glitch)
def build_footer():
    W, H = 1200, 150
    tag = DATA["footer"]
    d = Doc(W, H, f"RuutDev. {tag}")
    d.css.append(BASE_CSS)
    d.css.append(
        ".gl-a,.gl-b,.gl-s1,.gl-s2{opacity:0;animation:7s steps(1) 1s infinite}"
        ".gl-a{animation-name:gla}.gl-b{animation-name:glb}.gl-s1{animation-name:gls1}.gl-s2{animation-name:gls2}"
        "@keyframes gla{0%{opacity:.9;transform:translate(-5px,0)}2%{transform:translate(4px,-1px)}4%{transform:translate(-2px,1px)}6%{opacity:.9;transform:translate(1px,0)}8%,100%{opacity:0;transform:none}}"
        "@keyframes glb{0%{opacity:.8;transform:translate(5px,0)}2%{transform:translate(-4px,1px)}4%{transform:translate(3px,-1px)}6%{opacity:.8;transform:translate(-1px,0)}8%,100%{opacity:0;transform:none}}"
        "@keyframes gls1{1%{opacity:1;transform:translate(14px,0)}3%{transform:translate(-9px,0)}5%{opacity:1;transform:translate(5px,0)}7%,100%{opacity:0;transform:none}}"
        "@keyframes gls2{2%{opacity:1;transform:translate(-12px,0)}4%{transform:translate(7px,0)}6%,100%{opacity:0;transform:none}}"
    )
    card(d, W, H, glow_at=(0.06, 0.5), glow_op=0.22)
    mark, mw = logo(d, 64, 56, 38, glow=1.0)
    d.add(mark)
    t, _ = d.text(F["i600"], "RUUTDEV", 14, 64 + mw + 18, 81, MUTED, 3.4)
    d.add(t)
    size = 24
    tg, _ = d.text(F["i700"], tag, size, W - 64, 84, None, anchor="end")
    gid, s1, s2 = d.id("tg"), d.id("sl"), d.id("sl")
    d.defs.append(
        f'<g id="{gid}">{tg[3:-4]}</g>'
        f'<clipPath id="{s1}"><rect x="0" y="62" width="{W}" height="9"/></clipPath>'
        f'<clipPath id="{s2}"><rect x="0" y="76" width="{W}" height="7"/></clipPath>'
    )
    d.add(
        f'<use href="#{gid}" class="gl-a" fill="{LIME}"/>'
        f'<use href="#{gid}" class="gl-b" fill="{BLUE}"/>'
        f'<use href="#{gid}" fill="{WHITE}"/>'
        f'<use href="#{gid}" class="gl-s1" fill="{WHITE}" clip-path="url(#{s1})"/>'
        f'<use href="#{gid}" class="gl-s2" fill="{LIME}" clip-path="url(#{s2})"/>'
    )
    return d.write("footer.svg")


# ---------------------------------------------------------------- main
def main():
    built = [build_header(), build_focus(), build_toolkit(), build_content(), build_footer(), build_logo_icon()]
    built += [build_section(k) for k in DATA["sections"]]
    built += [build_project(p) for p in DATA["projects"]]
    built += [build_button(b) for b in DATA["buttons"]]
    built += [build_fact(f) for f in DATA["facts"]]
    for path, size in built:
        print(f"{path.relative_to(ROOT)}  {size / 1024:.1f} KB")


if __name__ == "__main__":
    main()
