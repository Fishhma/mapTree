"""Отрисовка раскладки в SVG — для предпросмотра и печати всего древа.

SVG векторный: можно печатать на плоттере любого размера без потери качества.
"""
from __future__ import annotations

from html import escape

from .layout import CARD_H, CARD_W, Layout, Line
from .model import Tree

CORNER_R = 12   # радиус скругления углов линий
JUMP_R = 5      # радиус «мостика», которым горизонтальная линия перепрыгивает вертикальную

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


def line_jumps(lines: list[Line]) -> list[list[tuple[float, float]]]:
    """Где горизонтальный участок линии пересекает вертикальный участок линии другой семьи.

    Для каждой линии — точки (x, y) на её горизонталях; там рисуется «мостик».
    Горизонталь не должна быть у самого своего угла (мостик не поместится). У чужой
    вертикали угол может быть рядом: уже через 6 px скругление почти отвесное
    (отклонение меньше 1 px), и мостик над ним выглядит так же.
    """
    margin, v_margin = CORNER_R + JUMP_R, 6
    hs, vs = [], []
    for i, ln in enumerate(lines):
        for (ax, ay), (bx, by) in zip(ln.points, ln.points[1:]):
            if ay == by and ax != bx:
                hs.append((i, ln.fid, ay, min(ax, bx), max(ax, bx)))
            elif ax == bx and ay != by:
                vs.append((ln.fid, ax, min(ay, by), max(ay, by)))
    out: list[list[tuple[float, float]]] = [[] for _ in lines]
    for i, fid, y, x1, x2 in hs:
        for vfid, x, y1, y2 in vs:
            if vfid != fid and x1 + margin < x < x2 - margin and y1 + v_margin <= y <= y2 - v_margin:
                if (x, y) not in out[i]:
                    out[i].append((x, y))
    return out


def rounded_path(points: list[tuple[float, float]], radius: float = CORNER_R,
                 jumps: list[tuple[float, float]] = ()) -> str:
    """Ломаная → SVG-путь со скруглёнными углами (дуга-кривая вместо прямого угла).

    Радиус уменьшается на коротких отрезках, чтобы скругление не «съело» отрезок.
    jumps — точки на горизонталях, где линия перепрыгивает чужую вертикаль полукругом.
    """
    pts = [p for i, p in enumerate(points) if i == 0 or p != points[i - 1]]
    pts = [p for i, p in enumerate(pts)                      # точки посреди прямого отрезка не нужны
           if i in (0, len(pts) - 1)
           or not (pts[i - 1][0] == p[0] == pts[i + 1][0] or pts[i - 1][1] == p[1] == pts[i + 1][1])]
    d = [f"M {pts[0][0]:.1f} {pts[0][1]:.1f}"]

    def straight(a: tuple[float, float], b: tuple[float, float]) -> None:
        (ax, ay), (bx, by) = a, b
        if ay == by and ax != bx:
            step = 1 if bx > ax else -1
            xs = sorted((x for x, y in jumps if y == ay and min(ax, bx) + JUMP_R < x < max(ax, bx) - JUMP_R),
                        key=lambda x: x * step)
            for x in xs:      # полукруг над чужой линией (выпуклостью вверх)
                d.append(f"L {x - step * JUMP_R:.1f} {ay:.1f} "
                         f"A {JUMP_R} {JUMP_R} 0 0 {1 if step > 0 else 0} {x + step * JUMP_R:.1f} {ay:.1f}")
        d.append(f"L {bx:.1f} {by:.1f}")

    cur = pts[0]
    for (ax, ay), (bx, by), (cx, cy) in zip(pts, pts[1:], pts[2:]):
        len_in = abs(bx - ax) + abs(by - ay)
        len_out = abs(cx - bx) + abs(cy - by)
        r = min(radius, len_in / 2, len_out / 2)
        sx = bx - r * ((bx > ax) - (bx < ax))
        sy = by - r * ((by > ay) - (by < ay))
        ex = bx + r * ((cx > bx) - (cx < bx))
        ey = by + r * ((cy > by) - (cy < by))
        straight(cur, (sx, sy))
        d.append(f"Q {bx:.1f} {by:.1f} {ex:.1f} {ey:.1f}")
        cur = (ex, ey)
    if len(pts) > 1:
        straight(cur, pts[-1])
    return " ".join(d)


def render(tree: Tree, layout: Layout, root: str | None = None, title: str = "") -> str:
    W, H = layout.width + 70, layout.height + (60 if title else 0)
    dy = 60 if title else 0
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W:.0f}" height="{H:.0f}" '
        f'viewBox="0 0 {W:.0f} {H:.0f}" font-family="PT Sans, Segoe UI, DejaVu Sans, sans-serif">',
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
    for line, jumps in zip(layout.lines, line_jumps(layout.lines)):
        d = rounded_path(line.points, jumps=jumps)
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
