"""Отрисовка раскладки в SVG — для предпросмотра и печати всего древа.

SVG векторный: можно печатать на плоттере любого размера без потери качества.
"""
from __future__ import annotations

from html import escape

from .layout import CARD_H, CARD_W, Layout
from .model import Tree

COLORS = {
    "paper": "#eef1ee",
    "card": "#ffffff",
    "ink": "#1d2a30",
    "muted": "#66757c",
    "line": "#7d8b90",
    "male": "#2f9cba",
    "female": "#c8406f",
    "unknown": "#9aa5a8",
    "root": "#e2b13c",
}


def _fit(text: str, size: float, width: float) -> str:
    max_chars = int(width / (size * 0.56))
    return text if len(text) <= max_chars else text[: max_chars - 1] + "…"


def render(tree: Tree, layout: Layout, root: str | None = None, title: str = "") -> str:
    W, H = layout.width + 70, layout.height + (60 if title else 0)
    dy = 60 if title else 0
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W:.0f}" height="{H:.0f}" '
        f'viewBox="0 0 {W:.0f} {H:.0f}" font-family="DejaVu Sans, Segoe UI, sans-serif">',
        f'<rect width="100%" height="100%" fill="{COLORS["paper"]}"/>',
    ]
    if title:
        out.append(f'<text x="40" y="44" font-size="26" font-weight="600" fill="{COLORS["ink"]}">{escape(title)}</text>')
    out.append(f'<g transform="translate(70,{dy})">')

    # подписи поколений и полосы рядов
    for gen, y in sorted(layout.rows.items()):
        out.append(f'<text x="-58" y="{y + CARD_H / 2 + 4:.0f}" font-size="13" fill="{COLORS["muted"]}">{gen}</text>')
        out.append(f'<line x1="-30" y1="{y + CARD_H / 2:.0f}" x2="-6" y2="{y + CARD_H / 2:.0f}" '
                   f'stroke="{COLORS["muted"]}" stroke-width="1"/>')

    # линии
    for line in layout.lines:
        d = "M " + " L ".join(f"{x:.1f} {y:.1f}" for x, y in line.points)
        w = 1.6 if line.kind == "marriage" else 1.3
        out.append(f'<path d="{d}" fill="none" stroke="{COLORS["line"]}" stroke-width="{w}" '
                   f'stroke-linejoin="round" data-family="{escape(line.fid)}"/>')
    for u in layout.unions.values():
        out.append(f'<circle cx="{u.x:.1f}" cy="{u.y:.1f}" r="3.2" fill="{COLORS["line"]}"/>')

    # карточки
    for pid, box in layout.boxes.items():
        p = tree.people[pid]
        left, top = box.x - CARD_W / 2, box.y
        accent = COLORS["male"] if p.sex == "M" else COLORS["female"] if p.sex == "F" else COLORS["unknown"]
        is_root = pid == root
        out.append(f'<g data-person="{escape(pid)}">')
        out.append(f'<rect x="{left:.1f}" y="{top:.1f}" width="{CARD_W}" height="{CARD_H}" rx="6" '
                   f'fill="{COLORS["card"]}" stroke="{COLORS["root"] if is_root else "#cfd6d6"}" '
                   f'stroke-width="{2.5 if is_root else 1}"/>')
        out.append(f'<rect x="{left:.1f}" y="{top:.1f}" width="{CARD_W}" height="5" rx="2" fill="{accent}"/>')
        given = _fit(p.given or "?", 13, CARD_W - 14)
        lines = [(given, 13, 600)]
        if p.patronymic:
            lines.append((_fit(p.patronymic, 11, CARD_W - 14), 11, 400))
        lines.append((_fit(p.surname or "", 13, CARD_W - 14), 13, 600))
        ty = top + 24
        for text, size, weight in lines:
            if text:
                out.append(f'<text x="{box.x:.1f}" y="{ty:.1f}" text-anchor="middle" font-size="{size}" '
                           f'font-weight="{weight}" fill="{COLORS["ink"]}">{escape(text)}</text>')
            ty += size + 4
        years = p.years()
        if years:
            out.append(f'<text x="{box.x:.1f}" y="{top + CARD_H - 9:.1f}" text-anchor="middle" font-size="11" '
                       f'fill="{COLORS["muted"]}">{escape(years)}</text>')
        out.append("</g>")
    out.append("</g></svg>")
    return "\n".join(out)
