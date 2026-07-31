import type { OptionSpec, OptionValues } from "./types";

/**
 * Pure helpers for the spec-driven Optimize panel.
 *
 * The panel never hardcodes a parameter list: webapp/params.py declares them,
 * /api/options serves that declaration, and everything here works off it.
 * Number fields are held as strings so a half-typed value stays editable; the
 * server is the single validator and coerces on submit.
 */

/** "" for a null default (a blank nullable field), booleans stay booleans. */
export function specDefault(spec: OptionSpec): string | boolean {
  if (spec.type === "bool") return spec.default === true;
  return spec.default === null || spec.default === undefined ? "" : String(spec.default);
}

export function initialValues(specs: OptionSpec[]): OptionValues {
  return Object.fromEntries(specs.map((s) => [s.name, specDefault(s)]));
}

export function applyPreset(
  specs: OptionSpec[],
  values: OptionValues,
  preset: Record<string, number | string | boolean | null>,
): OptionValues {
  const next = { ...values };
  for (const spec of specs) {
    if (!(spec.name in preset)) continue;
    const raw = preset[spec.name];
    next[spec.name] = spec.type === "bool" ? raw === true
      : raw === null ? "" : String(raw);
  }
  return next;
}

export function isModified(spec: OptionSpec, value: string | boolean | undefined): boolean {
  return value !== undefined && value !== specDefault(spec);
}

export function modifiedCount(specs: OptionSpec[], values: OptionValues): number {
  return specs.filter((s) => isModified(s, values[s.name])).length;
}

/** Spec order preserved, grouped by `group` — drives the section layout. */
export function byGroup(specs: OptionSpec[]): [string, OptionSpec[]][] {
  const out: [string, OptionSpec[]][] = [];
  for (const spec of specs) {
    const last = out[out.length - 1];
    if (last && last[0] === spec.group) last[1].push(spec);
    else out.push([spec.group, [spec]]);
  }
  return out;
}

/**
 * The equivalent `scripts/exp_roads_first.py` invocation for the current
 * values — non-default parameters only, and only those that map to a real CLI
 * flag (seed_polish / concurrent_levels are webapp-side and have none).
 */
export function cliPreview(specs: OptionSpec[], values: OptionValues): string {
  const parts: string[] = [];
  for (const spec of specs) {
    const value = values[spec.name];
    if (!spec.cli.startsWith("--") || !isModified(spec, value)) continue;
    if (spec.type === "bool") {
      if (value === true) parts.push(spec.cli);
    } else if (value !== "") {
      parts.push(`${spec.cli} ${value}`);
    }
  }
  return `uv run python scripts/exp_roads_first.py city.json${parts.length ? " " + parts.join(" ") : ""}`;
}

/** Minutes shown in the basic panel <-> the seconds the API takes. */
export function secondsToMinutes(seconds: string | boolean): number {
  const n = Number(seconds);
  return Number.isFinite(n) && n > 0 ? Math.max(1, Math.round(n / 60)) : 1;
}
