export function connectGraphInteractions({ svg, viewport, controls, onBackground }) {
  let transform = { x: 0, y: 0, scale: 1 };
  let dragging = false;
  let start = null;
  const apply = () => viewport.setAttribute("transform", `translate(${transform.x} ${transform.y}) scale(${transform.scale})`);
  const boundsFor = (layout, visibleIds) => {
    const points = [...layout.people].filter(([id]) => !visibleIds || visibleIds.has(id)).map(([, point]) => point);
    if (!points.length) return { minX: 0, minY: 0, maxX: 800, maxY: 500 };
    return {
      minX: Math.min(...points.map((point) => point.x - 110)),
      maxX: Math.max(...points.map((point) => point.x + 110)),
      minY: Math.min(...points.map((point) => point.y - 105)),
      maxY: Math.max(...points.map((point) => point.y + 105)),
    };
  };
  const fit = (layout, visibleIds = null, focusId = null) => {
    const bounds = boundsFor(layout, visibleIds);
    if (focusId && layout.people.has(focusId)) {
      const focus = layout.people.get(focusId);
      bounds.minX = focus.x - 170;
      bounds.maxX = focus.x + 170;
      bounds.minY = focus.y - 145;
      bounds.maxY = focus.y + 145;
    }
    const viewBox = svg.viewBox.baseVal;
    const width = Math.max(bounds.maxX - bounds.minX, 200);
    const height = Math.max(bounds.maxY - bounds.minY, 200);
    const scale = Math.min((viewBox.width * 0.9) / width, (viewBox.height * 0.9) / height, 1.35);
    const centerX = (bounds.minX + bounds.maxX) / 2;
    const centerY = (bounds.minY + bounds.maxY) / 2;
    transform = {
      x: viewBox.width / 2 - centerX * scale,
      y: viewBox.height / 2 - centerY * scale,
      scale: Math.max(Number.EPSILON, scale),
    };
    apply();
  };

  svg.addEventListener("wheel", (event) => {
    event.preventDefault();
    const viewPoint = svg.createSVGPoint();
    viewPoint.x = event.clientX;
    viewPoint.y = event.clientY;
    const anchor = viewPoint.matrixTransform(svg.getScreenCTM().inverse());
    const previous = transform.scale;
    const next = Math.max(0.2, Math.min(2.5, previous * (event.deltaY < 0 ? 1.1 : 0.9)));
    transform.x = anchor.x - (anchor.x - transform.x) * (next / previous);
    transform.y = anchor.y - (anchor.y - transform.y) * (next / previous);
    transform.scale = next;
    apply();
  }, { passive: false });
  svg.addEventListener("pointerdown", (event) => {
    if (event.target.closest(".person-node")) return;
    dragging = true;
    const pointer = svg.createSVGPoint();
    pointer.x = event.clientX;
    pointer.y = event.clientY;
    const point = pointer.matrixTransform(svg.getScreenCTM().inverse());
    start = { point, x: transform.x, y: transform.y };
    svg.setPointerCapture(event.pointerId);
  });
  svg.addEventListener("pointermove", (event) => {
    if (!dragging) return;
    const pointer = svg.createSVGPoint();
    pointer.x = event.clientX;
    pointer.y = event.clientY;
    const point = pointer.matrixTransform(svg.getScreenCTM().inverse());
    transform.x = start.x + point.x - start.point.x;
    transform.y = start.y + point.y - start.point.y;
    apply();
  });
  svg.addEventListener("pointerup", () => { dragging = false; });
  svg.addEventListener("pointercancel", () => { dragging = false; });
  svg.addEventListener("click", (event) => {
    if (!event.target.closest(".person-node")) onBackground();
  });
  controls.zoomIn.addEventListener("click", () => { transform.scale = Math.min(2.5, transform.scale * 1.2); apply(); });
  controls.zoomOut.addEventListener("click", () => { transform.scale = Math.max(0.2, transform.scale / 1.2); apply(); });
  return { fit, apply };
}
