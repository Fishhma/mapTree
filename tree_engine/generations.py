"""Расчёт поколений.

Поколение считается по связям от опорного человека (тебя): родитель = +1,
ребёнок = −1, супруг = то же поколение. Возраст не важен. В конце номера
сдвигаются так, чтобы самый нижний ряд древа был поколением 1, а выше — 2, 3…
(у опорного человека номер больше 1, если ниже него есть дети, племянники и т. д.).

Обход в ширину (BFS): каждый получает поколение по самой короткой цепочке
от опорного человека. Затем проверка: родитель обязан быть выше ребёнка.
Если родственные браки делают это невозможным, родитель поднимается
выше, и это записывается в предупреждения — программа не падает.
"""
from __future__ import annotations

from collections import deque

from . import _

from .model import Tree


def assign_generations(tree: Tree, root: str) -> tuple[dict[str, int], list[str]]:
    gen: dict[str, int] = {}
    warnings: list[str] = []

    def bfs(start: str, start_gen: int) -> None:
        gen[start] = start_gen
        queue = deque([start])
        while queue:
            cur = queue.popleft()
            steps = ([(p, +1) for p in tree.parents(cur)]
                     + [(s, 0) for s in tree.spouses(cur)]
                     + [(c, -1) for c in tree.children(cur)]
                     + [(s, 0) for s in tree.siblings(cur)])
            for nxt, delta in steps:
                if nxt not in gen:
                    gen[nxt] = gen[cur] + delta
                    queue.append(nxt)

    bfs(root, 1)
    for pid in tree.people:            # островки: считаем отдельно и предупреждаем
        if pid not in gen:
            warnings.append(_("%(pid)s не связан с опорным человеком") % {"pid": pid})
            bfs(pid, 1)

    # Родитель строго выше ребёнка. Поднимаем родителей, пока не сойдётся.
    for _round in range(len(tree.people) + 1):
        changed = False
        for fam in tree.families.values():
            for child in fam.children:
                for parent in fam.partners:
                    if gen[parent] < gen[child] + 1:
                        gen[parent] = gen[child] + 1
                        changed = True
        if not changed:
            break
    else:
        raise ValueError(_("Цикл в предках: человек оказался собственным предком"))

    # Нумерация снизу: самое младшее поколение — 1.
    shift = 1 - min(gen.values(), default=1)
    gen = {pid: g + shift for pid, g in gen.items()}

    for fam in tree.families.values():
        if len(fam.partners) == 2:
            a, b = fam.partners
            if gen[a] != gen[b]:
                warnings.append(_("Супруги %(a)s и %(b)s в разных поколениях (%(ga)s и %(gb)s)")
                                % {"a": a, "b": b, "ga": gen[a], "gb": gen[b]})
        for child in fam.children:
            for parent in fam.partners:
                if gen[parent] - gen[child] > 1:
                    warnings.append(_("%(parent)s выше ребёнка %(child)s на %(n)s поколения")
                                    % {"parent": parent, "child": child, "n": gen[parent] - gen[child]})
    return gen, warnings
