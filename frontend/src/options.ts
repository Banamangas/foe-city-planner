import type { CityScreen, FillerFailures, OptionSpec, OptionValues } from "./types";

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


/** Warn when a phase would spend a large share of the time box on ONE probe.
 *
 * The k-walk checks its deadline only between probes, so a `probe_limit` at or
 * above the box means the user waits for the probe rather than the box —
 * measured 292s for a 120s box at probe_limit=300 (2.43x). BEST_PRESET was
 * fixed, but a hand-set combination still overruns, and the library does not
 * clamp it (someone may legitimately want one deep probe). So: warn, never block.
 *
 * Returns null when the settings are fine, otherwise the message to show.
 */
export function budgetWarning(values: OptionValues): string | null {
  const box = Number(values.time_box);
  const probe = Number(values.probe_limit);
  if (!Number.isFinite(box) || !Number.isFinite(probe) || box <= 0 || probe <= 0) {
    return null;
  }
  if (probe >= box) {
    return `One probe (${probe}s) is as long as the whole time-box (${Math.round(box)}s). `
      + `The run will take at least ${probe}s — the deadline is only checked between probes.`;
  }
  if (probe > box / 2) {
    return `One probe (${probe}s) is over half the time-box (${Math.round(box)}s), `
      + `so the run may overshoot by up to one probe.`;
  }
  return null;
}


/** What (if anything) to show for an instance screen, as a pure decision.
 *
 * Kept out of the component so the rules are testable without a DOM: which
 * verdicts warn, how severely, and — the rule that matters — that the run is
 * NEVER blocked. The screen is calibrated on three cities and confounded with
 * building count, so it has earned the right to warn and not to refuse.
 */
export function screenBanner(screen: CityScreen | undefined | null):
  { severity: "bad" | "warn"; heading: string; canStillRun: boolean } | null {
  if (!screen || screen.verdict === "LIKELY") return null;
  if (screen.verdict === "INFEASIBLE") {
    return { severity: "bad", canStillRun: false,
             heading: "This city cannot be optimised" };
  }
  if (screen.verdict === "UNLIKELY") {
    return { severity: "bad", canStillRun: true,
             heading: "This city is unlikely to yield a result" };
  }
  return { severity: "warn", canStillRun: true,
           heading: "This city is outside the measured range" };
}


/** Explain a run that died at the filler stage, as a pure decision.
 *
 * Without this a user whose run ends this way sees "found nothing" and has no
 * idea why: the search DID solve the hard part — every road-needing building
 * was placed — and then failed on the leftovers. Returns null when no layout
 * died this way, so the caller renders nothing in the normal case.
 */
export function fillerFailureNote(
  ff: FillerFailures | undefined | null,
  foundLayout: boolean,
): { heading: string; detail: string; blames: string[] } | null {
  if (!ff || ff.failures < 1) return null;
  const shortfall = Math.max(0, ff.mean_total - ff.mean_placed);
  const heading = foundLayout
    ? `${ff.failures} candidate layout${ff.failures === 1 ? "" : "s"} discarded at the packing stage`
    : `No layout: ${ff.failures} candidate${ff.failures === 1 ? " was" : "s were"} solved, then could not be filled`;
  const detail =
    `Every road-needing building was placed, but on average only `
    + `${ff.mean_placed} of ${ff.mean_total} remaining buildings fitted `
    + `(short by about ${shortfall.toFixed(1)}; worst case ${ff.worst_placed}). `
    + `This is a space problem, not a road problem — removing a few large `
    + `buildings, or freeing region cells, is more likely to help than a longer run.`;
  return { heading, detail, blames: ff.top_unplaced.map((u) => u.name) };
}
