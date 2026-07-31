import { describe, it, expect } from "vitest";
import {
  applyPreset, byGroup, cliPreview, initialValues, isModified, modifiedCount,
  secondsToMinutes, specDefault,
} from "./options";
import type { OptionSpec } from "./types";

const specs: OptionSpec[] = [
  { name: "time_box", cli: "--time-box", label: "Time-box (s)", help: "", group: "budget",
    type: "float", default: 300.0, advanced: false, min: 1 },
  { name: "seed_polish", cli: "(webapp only)", label: "Seed-polish", help: "", group: "budget",
    type: "int", default: 0, advanced: false, min: 0 },
  { name: "patterns", cli: "--patterns", label: "Patterns per k", help: "", group: "search",
    type: "int", default: 200, min: 1 },
  { name: "k_start", cli: "--k-start", label: "k start", help: "", group: "search",
    type: "int_or_auto", default: "auto" },
  { name: "pattern_family", cli: "--pattern-family", label: "Family", help: "", group: "patterns",
    type: "choice", default: "comb", choices: ["comb", "lane"] },
  { name: "lane_cap", cli: "--lane-cap", label: "Lane cap", help: "", group: "patterns",
    type: "int_or_null", default: null, min: 1 },
  { name: "stub_priority", cli: "--stub-priority", label: "Stub priority", help: "", group: "patterns",
    type: "bool", default: false },
];

describe("specDefault / initialValues", () => {
  it("keeps booleans boolean, stringifies numbers, and blanks a null default", () => {
    expect(initialValues(specs)).toEqual({
      time_box: "300", seed_polish: "0", patterns: "200", k_start: "auto",
      pattern_family: "comb", lane_cap: "", stub_priority: false,
    });
    expect(specDefault(specs[6])).toBe(false);
  });
});

describe("isModified / modifiedCount", () => {
  it("compares against the spec default, not against emptiness", () => {
    const values = initialValues(specs);
    expect(modifiedCount(specs, values)).toBe(0);
    expect(isModified(specs[2], "700")).toBe(true);
    expect(isModified(specs[2], "200")).toBe(false);
    expect(isModified(specs[6], true)).toBe(true);
    expect(modifiedCount(specs, { ...values, patterns: "700", stub_priority: true })).toBe(2);
  });
});

describe("applyPreset", () => {
  it("overwrites only the keys the preset names", () => {
    const values = { ...initialValues(specs), patterns: "700" };
    const next = applyPreset(specs, values, { patterns: 20, time_box: 600.0 });
    expect(next.patterns).toBe("20");
    expect(next.time_box).toBe("600");
    expect(next.k_start).toBe("auto");
  });
});

describe("byGroup", () => {
  it("groups consecutive specs while preserving spec order", () => {
    expect(byGroup(specs).map(([g, s]) => [g, s.map((x) => x.name)])).toEqual([
      ["budget", ["time_box", "seed_polish"]],
      ["search", ["patterns", "k_start"]],
      ["patterns", ["pattern_family", "lane_cap", "stub_priority"]],
    ]);
  });
});

describe("cliPreview", () => {
  it("shows only non-default parameters that have a real CLI flag", () => {
    const values = {
      ...initialValues(specs),
      patterns: "700", pattern_family: "lane", stub_priority: true,
      seed_polish: "8", // webapp-only: no flag, must not appear
    };
    const cli = cliPreview(specs, values);
    expect(cli).toBe(
      "uv run python scripts/exp_roads_first.py city.json " +
      "--patterns 700 --pattern-family lane --stub-priority",
    );
  });

  it("omits a false boolean, a blank nullable, and every untouched knob", () => {
    expect(cliPreview(specs, initialValues(specs)))
      .toBe("uv run python scripts/exp_roads_first.py city.json");
    const values = { ...initialValues(specs), lane_cap: "12", k_start: "105" };
    expect(cliPreview(specs, values))
      .toBe("uv run python scripts/exp_roads_first.py city.json --k-start 105 --lane-cap 12");
  });
});

describe("secondsToMinutes", () => {
  it("converts and floors at one minute", () => {
    expect(secondsToMinutes("300")).toBe(5);
    expect(secondsToMinutes("600")).toBe(10);
    expect(secondsToMinutes("30")).toBe(1);
    expect(secondsToMinutes("")).toBe(1);
  });
});
