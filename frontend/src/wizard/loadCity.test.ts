import { describe, expect, it } from "vitest";
import { classifyLoadProblem, validateCustom } from "./loadCity";

const resp = (exportable: boolean) => ({ resp: { exportable } as any });

describe("classifyLoadProblem", () => {
  it("422 with unknown buildings", () => {
    const items = [{ cityentity_id: "W_X", count: 2 }];
    expect(classifyLoadProblem({ status: 422, body: { unknown_buildings: items } })).toEqual({
      kind: "unknown_buildings",
      items,
    });
  });
  it("network failure means the app is not running", () => {
    expect(classifyLoadProblem({ status: 0, body: { error: "x" } })).toEqual({ kind: "app_not_running" });
  });
  it("other 4xx is unreadable and keeps the details", () => {
    const p = classifyLoadProblem({ status: 400, body: { error: "could not parse city: KeyError 'x'" } });
    expect(p?.kind).toBe("unreadable");
    expect((p as any).details).toContain("KeyError");
  });
  it("exportable false is not Forge Hammer", () => {
    expect(classifyLoadProblem(resp(false))).toEqual({ kind: "not_forge_hammer" });
  });
  it("exportable true is fine", () => {
    expect(classifyLoadProblem(resp(true))).toBeNull();
  });
});

describe("validateCustom", () => {
  it("lists the invalid ids", () => {
    expect(
      validateCustom({
        a: { width: 0, length: 3, road: 1 },
        b: { width: 2, length: 2, road: 2 },
        c: { width: 2, length: 21, road: 0 },
      }),
    ).toEqual(["a", "c"]);
  });
});
