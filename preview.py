"""Предпросмотр: python preview.py древо.ged out.svg [ID опорного человека]"""
import sys

from tree_engine.gedcom import load
from tree_engine.layout import compute_layout, count_crossings
from tree_engine.render_svg import render

src, dst = sys.argv[1], sys.argv[2]
tree = load(src)
root = sys.argv[3] if len(sys.argv) > 3 else next(iter(tree.people))
layout = compute_layout(tree, root)
with open(dst, "w", encoding="utf-8") as f:
    f.write(render(tree, layout, root=root))
print(f"{len(tree.people)} человек, {len(tree.families)} семей, "
      f"{len(layout.rows)} поколений, {layout.width:.0f}×{layout.height:.0f}px, "
      f"пересечений: {count_crossings(tree, layout)}")
for w in layout.warnings:
    print("!", w)
