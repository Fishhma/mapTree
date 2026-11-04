"""Раскладка всего древа по поколениям (послойный метод в духе Сугиямы).

Шаги:
 1. Поколения → горизонтальные ряды (вверху старшие).
 2. В каждом ряду супруги склеиваются в «блоки»: [1-я жена][Libor][Юлия][её 2-й муж].
    Внутри блока каждый брак — соседние карточки, у брака своя точка-«союз».
 3. Порядок и координаты блоков подбираются итеративно: дети тянутся под
    точку союза родителей, союз тянется к центру своих детей. Перекрытия
    снимаются изотонической регрессией (порядок сохраняется, сдвиг минимален).
 4. Линии: у каждой семьи своя горизонтальная «шина» к детям на отдельной
    дорожке, чтобы линии разных семей не сливались.

Результат — чистые координаты (Layout), рисует их отдельный модуль.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .generations import assign_generations
from .model import Tree

CARD_W = 150
CARD_H = 84
SPOUSE_GAP = 14      # между супругами в блоке
SIBLING_GAP = 34     # между блоками братьев/сестёр
FAMILY_GAP = 72      # между неродственными блоками
RAIL_DY = 14         # от низа карточки до линии брака
TRACK_DY = 9         # шаг дорожек шин
GAP_BASE = 46        # минимальный зазор между рядами (без дорожек)
SNAP_DX = 24         # ребёнок почти под точкой брака: линия входит в карточку не по центру, зато прямая
ITERATIONS = 40


@dataclass
class Box:
    pid: str
    x: float          # центр
    y: float          # верх
    gen: int


@dataclass
class Union:
    fid: str
    x: float
    y: float          # высота точки союза
    attach: list[tuple[float, float]] = field(default_factory=list)  # точки на партнёрах


@dataclass
class Line:
    kind: str                     # marriage | descent
    points: list[tuple[float, float]]
    fid: str


@dataclass
class Layout:
    boxes: dict[str, Box]
    unions: dict[str, Union]
    lines: list[Line]
    rows: dict[int, float]        # поколение → y верха ряда
    width: float
    height: float
    warnings: list[str]


class _Block:
    def __init__(self, members: list[str], layer: int):
        self.members = members
        self.layer = layer
        self.left = 0.0
        self.sort_hint = (9999, 0, 0)

    @property
    def width(self) -> float:
        n = len(self.members)
        return n * CARD_W + (n - 1) * SPOUSE_GAP

    def offset(self, pid: str) -> float:
        i = self.members.index(pid)
        return i * (CARD_W + SPOUSE_GAP) + CARD_W / 2


def _isotonic(targets: list[float], weights: list[float]) -> list[float]:
    """Взвешенная изотоническая регрессия (неубывающая), алгоритм PAV."""
    blocks: list[list[float]] = []   # [сумма w*t, сумма w, кол-во]
    for t, w in zip(targets, weights):
        blocks.append([t * w, w, 1])
        while len(blocks) > 1 and blocks[-2][0] / blocks[-2][1] > blocks[-1][0] / blocks[-1][1]:
            s, ww, n = blocks.pop()
            blocks[-1][0] += s
            blocks[-1][1] += ww
            blocks[-1][2] += n
    out = []
    for s, w, n in blocks:
        out += [s / w] * n
    return out


class _Engine:
    def __init__(self, tree: Tree, root: str):
        self.t = tree
        self.gen, self.warnings = assign_generations(tree, root)
        self.max_gen = max(self.gen.values())
        self.layers: dict[int, list[_Block]] = {}
        self.block_of: dict[str, _Block] = {}
        self._build_blocks()

    # ---------- блоки супругов ----------
    def _same_layer_spouses(self, pid: str) -> list[str]:
        out = []
        for fid in self.t.people[pid].families:
            for s in self.t.families[fid].partners:
                if s != pid and self.gen[s] == self.gen[pid] and s not in out:
                    out.append(s)
        return out

    def _arrange(self, group: set[str]) -> list[str]:
        p = self.t.people
        start = max(group, key=lambda m: (len(self._same_layer_spouses(m)),
                                          p[m].parent_family is not None,
                                          p[m].sex == "M"))
        visited = {start}

        def outward(pid: str) -> list[str]:
            rest = [s for s in self._same_layer_spouses(pid) if s not in visited]
            visited.update(rest)
            seq = [pid]
            for s in rest:
                seq += outward(s)
            return seq

        rest = [s for s in self._same_layer_spouses(start) if s not in visited]
        visited.update(rest)
        if len(rest) == 1:
            left, right = ([], rest) if p[start].sex != "F" else (rest, [])
        else:
            half = len(rest) // 2
            left, right = rest[:half], rest[half:]
        seq_left: list[str] = []
        for s in left:
            seq_left = list(reversed(outward(s))) + seq_left
        seq_right: list[str] = []
        for s in right:
            seq_right += outward(s)
        return seq_left + [start] + seq_right

    def _build_blocks(self) -> None:
        seen: set[str] = set()
        for pid in self.t.people:
            if pid in seen:
                continue
            group, stack = {pid}, [pid]
            while stack:
                for s in self._same_layer_spouses(stack.pop()):
                    if s not in group:
                        group.add(s)
                        stack.append(s)
            seen |= group
            layer = self.max_gen - self.gen[pid]
            block = _Block(self._arrange(group), layer)
            block.sort_hint = min(self.t.people[m].birth_key for m in block.members
                                  if self.t.people[m].parent_family) if any(
                self.t.people[m].parent_family for m in block.members) else (9999, 0, 0)
            self.layers.setdefault(layer, []).append(block)
            for m in block.members:
                self.block_of[m] = block

    # ---------- координаты ----------
    def x(self, pid: str) -> float:
        b = self.block_of[pid]
        return b.left + b.offset(pid)

    def attach_points(self, fid: str) -> list[float]:
        fam = self.t.families[fid]
        if len(fam.partners) == 2:
            a, b = fam.partners
            ba, bb = self.block_of[a], self.block_of[b]
            if ba is bb and abs(ba.members.index(a) - ba.members.index(b)) == 1:
                if ba.members.index(a) > ba.members.index(b):
                    a, b = b, a
                return [self.x(a) + CARD_W / 4, self.x(b) - CARD_W / 4]
            return [self.x(a), self.x(b)]
        return [self.x(p) for p in fam.partners]

    def union_x(self, fid: str) -> float | None:
        pts = self.attach_points(fid)
        return sum(pts) / len(pts) if pts else None

    def _gap(self, a: _Block, b: _Block) -> float:
        fa = {self.t.people[m].parent_family for m in a.members} - {None}
        fb = {self.t.people[m].parent_family for m in b.members} - {None}
        return SIBLING_GAP if fa & fb else FAMILY_GAP

    def _desired(self, block: _Block, use_up: bool, use_down: bool) -> float | None:
        votes: list[float] = []
        if use_down:   # тянемся под союз своих родителей
            for m in block.members:
                fid = self.t.people[m].parent_family
                if fid and self.t.families[fid].partners:
                    ux = self.union_x(fid)
                    votes.append(ux - block.offset(m))
        if use_up:     # союз тянется к центру своих детей
            for m in block.members:
                for fid in self.t.people[m].families:
                    fam = self.t.families[fid]
                    if not fam.children or any(self.block_of[p] is not block for p in fam.partners):
                        continue
                    xs = [self.x(c) for c in fam.children]
                    target = (min(xs) + max(xs)) / 2
                    votes.append(target - (self.union_x(fid) - block.left))
        if not votes:
            return None
        return sum(votes) / len(votes)

    def _orient(self, block: _Block) -> None:
        """Разворачиваем блок, если так супруги ближе к своим родителям."""
        if len(block.members) < 2:
            return

        def cost() -> float:
            c = 0.0
            for m in block.members:
                fid = self.t.people[m].parent_family
                if fid and self.t.families[fid].partners:
                    c += abs(self.x(m) - self.union_x(fid))
            return c
        before = cost()
        block.members.reverse()
        if cost() >= before:
            block.members.reverse()

    def _place_layer(self, layer: int, up: bool, down: bool, reorder: bool = True) -> None:
        blocks = self.layers[layer]
        if down and reorder:
            for b in blocks:
                self._orient(b)
        desired = []
        for b in blocks:
            d = self._desired(b, up, down)
            desired.append(b.left if d is None else d)
        if reorder:
            order = sorted(range(len(blocks)),
                           key=lambda i: (desired[i] + blocks[i].width / 2, blocks[i].sort_hint))
            blocks[:] = [blocks[i] for i in order]
            desired = [desired[i] for i in order]
        offsets, acc = [], 0.0
        for i, b in enumerate(blocks):
            offsets.append(acc)
            acc += b.width + (self._gap(b, blocks[i + 1]) if i + 1 < len(blocks) else 0)
        ys = _isotonic([d - o for d, o in zip(desired, offsets)], [1.0] * len(blocks))
        for b, y, o in zip(blocks, ys, offsets):
            b.left = y + o

    def _initial_order(self, root: str) -> None:
        """Начальный порядок — обход в глубину от опорного человека."""
        index: dict[str, int] = {}
        stack = [root]
        while stack:
            cur = stack.pop()
            if cur in index:
                continue
            index[cur] = len(index)
            nxt = self.t.parents(cur) + self.t.spouses(cur) + self.t.siblings(cur) + self.t.children(cur)
            stack += reversed(nxt)
        for layer, blocks in self.layers.items():
            blocks.sort(key=lambda b: min(index.get(m, 10**6) for m in b.members))
            acc = 0.0
            for i, b in enumerate(blocks):
                b.left = acc
                acc += b.width + (self._gap(b, blocks[i + 1]) if i + 1 < len(blocks) else 0)

    def run(self, root: str) -> Layout:
        self._initial_order(root)
        layers = sorted(self.layers)
        for it in range(ITERATIONS):
            for L in layers[1:]:
                self._place_layer(L, up=False, down=True)
            for L in reversed(layers[:-1]):
                self._place_layer(L, up=True, down=False)
        for _ in range(6):
            for L in layers:
                self._place_layer(L, up=True, down=True)
        # Устранение пересечений перестановкой соседних блоков, затем
        # подгонка координат при фиксированном порядке.
        for _ in range(8):
            improved = False
            for L in layers:
                improved |= self._transpose(L)
            for _ in range(10):
                for L in layers[1:]:
                    self._place_layer(L, up=False, down=True, reorder=False)
                for L in reversed(layers[:-1]):
                    self._place_layer(L, up=True, down=False, reorder=False)
            if not improved:
                break
        for _ in range(10):
            for L in layers:
                self._place_layer(L, up=True, down=True, reorder=False)
        return self._finish()

    # ---------- пересечения ----------
    def _layer_crossings(self, layer: int) -> int:
        """Пересечения линий, входящих в ряд сверху и выходящих из него вниз."""
        groups: dict[int, list[tuple[float, float]]] = {}
        for fid, fam in self.t.families.items():
            if not fam.partners or not fam.children:
                continue
            ulayer = max(self.block_of[p].layer for p in fam.partners)
            for c in fam.children:
                clayer = self.block_of[c].layer
                if layer in (ulayer, clayer):
                    groups.setdefault(clayer, []).append((self.union_x(fid), self.x(c)))
        total = 0
        for edges in groups.values():
            for i in range(len(edges)):
                for j in range(i + 1, len(edges)):
                    (a1, b1), (a2, b2) = edges[i], edges[j]
                    if (a1 - a2) * (b1 - b2) < 0:
                        total += 1
        return total

    def _transpose(self, layer: int) -> bool:
        blocks = self.layers[layer]
        improved_any = False
        changed = True
        while changed:
            changed = False
            for b in blocks:                      # разворот блока супругов
                if len(b.members) > 1:
                    before = self._layer_crossings(layer)
                    b.members.reverse()
                    if self._layer_crossings(layer) >= before:
                        b.members.reverse()
                    else:
                        changed = improved_any = True
            for i in range(len(blocks) - 1):      # перестановка соседей
                a, b = blocks[i], blocks[i + 1]
                before = self._layer_crossings(layer)
                la, lb = a.left, b.left
                blocks[i], blocks[i + 1] = b, a
                b.left = la
                a.left = la + b.width + (lb - la - a.width)
                if self._layer_crossings(layer) < before:
                    changed = improved_any = True
                else:
                    blocks[i], blocks[i + 1] = a, b
                    a.left, b.left = la, lb
        return improved_any

    # ---------- вертикаль и линии ----------
    def _finish(self) -> Layout:
        layers = sorted(self.layers)
        min_x = min(b.left for bl in self.layers.values() for b in bl)
        for bl in self.layers.values():
            for b in bl:
                b.left -= min_x - 40

        # дорожки шин: семьи, чьи дети ниже этого ряда
        bus_track: dict[str, int] = {}
        tracks_in_layer: dict[int, int] = {}
        for L in layers:
            spans = []
            for fid, fam in self.t.families.items():
                if not fam.partners or not fam.children:
                    continue
                if max(self.block_of[p].layer for p in fam.partners) != L:
                    continue
                ux = self.union_x(fid)
                xs = [self.x(c) for c in fam.children] + [ux]
                spans.append((min(xs), max(xs), fid))
            spans.sort()
            ends: list[float] = []
            for lo, hi, fid in spans:
                for t, end in enumerate(ends):
                    if lo > end + 12:
                        ends[t] = hi
                        bus_track[fid] = t
                        break
                else:
                    ends.append(hi)
                    bus_track[fid] = len(ends) - 1
            tracks_in_layer[L] = len(ends)

        rows: dict[int, float] = {}
        y = 40.0
        for L in layers:
            rows[L] = y
            y += CARD_H + GAP_BASE + max(0, tracks_in_layer.get(L, 0) - 1) * TRACK_DY

        boxes = {pid: Box(pid, self.x(pid), rows[self.block_of[pid].layer], self.gen[pid])
                 for pid in self.t.people}
        unions: dict[str, Union] = {}
        lines: list[Line] = []
        for fid, fam in self.t.families.items():
            if not fam.partners or (len(fam.partners) == 1 and not fam.children):
                continue          # одинокий партнёр без детей — не брак, рисовать нечего
            pts = self.attach_points(fid)
            bottoms = [boxes[p].y + CARD_H for p in fam.partners]
            jy = max(bottoms) + RAIL_DY
            ux = sum(pts) / len(pts)
            unions[fid] = Union(fid, ux, jy, list(zip(pts, bottoms)))
            if len(pts) == 2:
                (ax, ay), (bx, by) = sorted(zip(pts, bottoms))
                lines.append(Line("marriage", [(ax, ay), (ax, jy), (bx, jy), (bx, by)], fid))
            else:
                lines.append(Line("marriage", [(pts[0], bottoms[0]), (pts[0], jy)], fid))
            if fam.children:
                # Ствол от точки брака вниз до шины, от шины — ветка к каждому ребёнку
                # (скругляется только поворот к ребёнку). Один ребёнок — одна ломаная.
                bus_y = jy + 14 + bus_track.get(fid, 0) * TRACK_DY
                drops = [(c, ux if abs(boxes[c].x - ux) <= SNAP_DX else boxes[c].x) for c in fam.children]
                if len(drops) == 1:
                    (c, cx), = drops
                    lines.append(Line("descent", [(ux, jy), (ux, bus_y), (cx, bus_y), (cx, boxes[c].y)], fid))
                else:
                    lines.append(Line("descent", [(ux, jy), (ux, bus_y)], fid))
                    for c, cx in drops:
                        lines.append(Line("descent", [(ux, bus_y), (cx, bus_y), (cx, boxes[c].y)], fid))

        width = max(b.left + b.width for bl in self.layers.values() for b in bl) + 40
        height = y + 20
        gen_rows = {self.max_gen - L: rows[L] for L in layers}
        return Layout(boxes, unions, lines, gen_rows, width, height, self.warnings)


def compute_layout(tree: Tree, root: str) -> Layout:
    return _Engine(tree, root).run(root)


def count_crossings(tree: Tree, layout: Layout) -> int:
    """Метрика качества: сколько линий «родители→дети» пересекаются между рядами."""
    edges = []
    for fid, fam in tree.families.items():
        u = layout.unions.get(fid)
        if not u:
            continue
        for c in fam.children:
            edges.append((u.y, u.x, layout.boxes[c].x))
    crossings = 0
    for i in range(len(edges)):
        for j in range(i + 1, len(edges)):
            (y1, a1, b1), (y2, a2, b2) = edges[i], edges[j]
            if y1 == y2 and (a1 - a2) * (b1 - b2) < 0:
                crossings += 1
    return crossings
