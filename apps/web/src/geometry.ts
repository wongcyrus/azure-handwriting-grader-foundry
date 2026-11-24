import type { Box } from "./types";

export interface Point {
  x: number;
  y: number;
}

export interface Dimensions {
  width: number;
  height: number;
}

const clamp = (value: number, maximum: number) =>
  Math.max(0, Math.min(maximum, value));

export function imagePoint(
  client: Point,
  rect: Dimensions & { left: number; top: number },
  page: Dimensions,
): Point {
  if (rect.width <= 0 || rect.height <= 0)
    throw new Error("Page is not visible.");
  // Both client positions and DOM bounds are CSS pixels, independent of DPR.
  return {
    x: clamp(((client.x - rect.left) / rect.width) * page.width, page.width),
    y: clamp(((client.y - rect.top) / rect.height) * page.height, page.height),
  };
}

export function drawnBox(
  start: Point,
  end: Point,
  page: Dimensions,
  label: string,
): Box | null {
  const x = Math.floor(clamp(Math.min(start.x, end.x), page.width));
  const y = Math.floor(clamp(Math.min(start.y, end.y), page.height));
  const right = Math.ceil(clamp(Math.max(start.x, end.x), page.width));
  const bottom = Math.ceil(clamp(Math.max(start.y, end.y), page.height));
  return right > x && bottom > y
    ? { x, y, width: right - x, height: bottom - y, label }
    : null;
}

export function movedBox(
  box: Box,
  dx: number,
  dy: number,
  page: Dimensions,
): Box {
  return {
    ...box,
    x: clamp(box.x + dx, page.width - box.width),
    y: clamp(box.y + dy, page.height - box.height),
  };
}

export function validBox(box: Box, page: Dimensions): boolean {
  return (
    [box.x, box.y, box.width, box.height].every(Number.isInteger) &&
    box.x >= 0 &&
    box.y >= 0 &&
    box.width > 0 &&
    box.height > 0 &&
    box.x + box.width <= page.width &&
    box.y + box.height <= page.height
  );
}
