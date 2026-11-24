import { describe, expect, it } from "vitest";
import { drawnBox, imagePoint, movedBox } from "./geometry";

describe("canonical image coordinates", () => {
  it.each([0.25, 0.5, 1, 2])(
    "uses actual CSS bounds at zoom %s without DPR scaling",
    (zoom) => {
      const page = { width: 1000, height: 2000 };
      expect(
        imagePoint(
          { x: 10 + 400 * zoom, y: 20 + 700 * zoom },
          { left: 10, top: 20, width: 1000 * zoom, height: 2000 * zoom },
          page,
        ),
      ).toEqual({ x: 400, y: 700 });
    },
  );
  it("clips reverse and off-page drags into integer image pixels", () => {
    expect(
      drawnBox(
        { x: 110, y: 110 },
        { x: -2, y: 1.5 },
        { width: 100, height: 100 },
        "Q1",
      ),
    ).toEqual({ x: 0, y: 1, width: 100, height: 99, label: "Q1" });
    expect(
      drawnBox(
        { x: 10, y: 10 },
        { x: 10, y: 20 },
        { width: 100, height: 100 },
        "ID",
      ),
    ).toBeNull();
  });
  it("keeps keyboard movement inside page edges", () => {
    expect(
      movedBox({ x: 5, y: 5, width: 20, height: 20, label: "ID" }, -10, 500, {
        width: 100,
        height: 100,
      }),
    ).toEqual({ x: 0, y: 80, width: 20, height: 20, label: "ID" });
  });
});
