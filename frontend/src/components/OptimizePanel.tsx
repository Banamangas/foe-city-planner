import { useEffect, useRef, useState } from "react";
import { useCityStore } from "../stores/cityStore";
import { apiOptimize, apiOptions, apiStop, openStream } from "../api";
import {
  applyPreset, byGroup, cliPreview, initialValues, isModified, modifiedCount,
  secondsToMinutes,
} from "../options";
import type { CityScreen, OptionSpec, OptionValues, OptionsResponse } from "../types";

/** One parameter's control, chosen by its declared type. */
function Field({ spec, value, disabled, onChange }: {
  spec: OptionSpec;
  value: string | boolean;
  disabled: boolean;
  onChange: (v: string | boolean) => void;
}) {
  const title = `${spec.help}${spec.cli.startsWith("--") ? `\n\nCLI: ${spec.cli}` : ""}`;
  const modified = isModified(spec, value);
  const label = (
    <span className={modified ? "opt-label modified" : "opt-label"}>{spec.label}</span>
  );

  if (spec.type === "bool") {
    return (
      <label className="row opt" title={title}>
        <input type="checkbox" checked={value === true} disabled={disabled}
          onChange={(e) => onChange(e.target.checked)} />
        {label}
      </label>
    );
  }
  if (spec.type === "choice") {
    return (
      <label className="row opt" title={title}>
        {label}
        <select value={String(value)} disabled={disabled}
          onChange={(e) => onChange(e.target.value)}>
          {spec.choices!.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
      </label>
    );
  }
  // int_or_auto ("auto" or a number) needs a text box; the rest are numeric.
  const isText = spec.type === "int_or_auto";
  return (
    <label className="row opt" title={title}>
      {label}
      <input
        type={isText ? "text" : "number"}
        value={String(value)}
        placeholder={spec.type === "int_or_null" ? "none" : isText ? "auto" : ""}
        min={isText ? undefined : spec.min}
        max={isText ? undefined : spec.max}
        step={spec.type === "float" ? "any" : 1}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
      />
    </label>
  );
}

/** Advisory instance screen. Never disables the run — a user may always try a
 *  city we predict poorly for. Calibrated on three cities and confounded with
 *  building count, so it explains its reasoning rather than asserting a limit. */
function ScreenBanner({ screen }: { screen: CityScreen }) {
  if (screen.verdict === "LIKELY") return null;
  const cls = screen.verdict === "INFEASIBLE" ? "screen-bad"
    : screen.verdict === "UNLIKELY" ? "screen-bad" : "screen-warn";
  const heading = screen.verdict === "INFEASIBLE"
    ? "This city cannot be optimised"
    : screen.verdict === "UNLIKELY"
      ? "This city is unlikely to yield a result"
      : "This city is outside the measured range";
  return (
    <div className={cls}>
      <strong>{heading}</strong>
      <div className="screen-reason">{screen.reason}</div>
      <div className="screen-detail">
        road pressure {screen.road_pressure} · {screen.consumers} buildings need
        road access · {screen.slack} free cells
      </div>
      {screen.verdict !== "INFEASIBLE" && (
        <div className="screen-detail">You can still run it — this is a prediction, not a limit.</div>
      )}
    </div>
  );
}

export function OptimizePanel() {
  const city = useCityStore((s) => s.city);
  const job = useCityStore((s) => s.job);
  const applyImprovement = useCityStore((s) => s.applyImprovement);
  const setJob = useCityStore((s) => s.setJob);
  const [spec, setSpec] = useState<OptionsResponse | null>(null);
  const [values, setValues] = useState<OptionValues>({});
  const [error, setError] = useState("");
  const esRef = useRef<EventSource | null>(null);

  // The parameter list is served, not hardcoded: adding a knob to
  // webapp/params.py makes it appear here with no frontend change.
  useEffect(() => {
    apiOptions()
      .then((res) => { setSpec(res); setValues(initialValues(res.options)); })
      .catch((err) => setError(String(err)));
  }, []);

  const running = job?.state === "running";
  const specs = spec?.options ?? [];
  const basic = specs.filter((s) => s.advanced === false);
  const advanced = specs.filter((s) => s.advanced !== false);
  const changed = modifiedCount(advanced, values);
  const set = (name: string, v: string | boolean) =>
    setValues((prev) => ({ ...prev, [name]: v }));

  const start = async () => {
    if (!city) return;
    setError("");
    try {
      const { job_id } = await apiOptimize({ city_id: city.city_id, ...values });
      setJob({ id: job_id, state: "running", elapsed: 0 });
      esRef.current = openStream(job_id, {
        onImprovement: (imp) => applyImprovement(imp),
        onHeartbeat: (st) => setJob({ id: job_id, state: "running", elapsed: st.elapsed ?? 0 }),
        onDone: () => setJob({ id: job_id, state: "done", elapsed: 0 }),
      });
    } catch (err) {
      setError(String(err));
    }
  };

  const stop = async () => {
    if (job) await apiStop(job.id).catch(() => {});
  };

  if (!city) return null;
  return (
    <div className="panel">
      <h3>Optimize</h3>

      {city.screen && <ScreenBanner screen={city.screen} />}

      {spec?.presets?.best && (
        <div className="row">
          <button disabled={running} className="preset-best"
            title="The configuration that holds this project's records on both measured cities (darkzig 94 roads, FR16 76) — non-uniform skeletons filtered to the productive quality band, with seed polish."
            onClick={() => setValues(applyPreset(specs, values, spec.presets.best))}>
            Use best-known settings
          </button>
        </div>
      )}

      {basic.map((s) => (
        s.name === "time_box" ? (
          // Edited in minutes here; the API and the CLI flag are in seconds.
          <label className="row opt" key={s.name} title={s.help}>
            <span className="opt-label">Time-box (min)</span>
            <input type="number" min={1} max={1440} disabled={running}
              value={secondsToMinutes(values.time_box ?? "")}
              onChange={(e) => set("time_box", String(Math.max(1, Number(e.target.value) || 1) * 60))} />
          </label>
        ) : (
          <Field key={s.name} spec={s} value={values[s.name] ?? ""} disabled={running}
            onChange={(v) => set(s.name, v)} />
        )
      ))}

      {advanced.length > 0 && (
        <details className="advanced">
          <summary>
            Advanced options{changed > 0 ? ` (${changed} changed)` : ""}
          </summary>
          {byGroup(advanced).map(([group, groupSpecs]) => (
            <div key={group}>
              <h4>{spec!.groups[group] ?? group}</h4>
              {groupSpecs.map((s) => (
                <Field key={s.name} spec={s} value={values[s.name] ?? ""} disabled={running}
                  onChange={(v) => set(s.name, v)} />
              ))}
            </div>
          ))}
          <div className="row">
            <button disabled={running}
              onClick={() => setValues(initialValues(specs))}>Reset defaults</button>
            {spec!.presets.smoke && (
              <button disabled={running} title="Tiny, fast run for checking the pipeline end to end"
                onClick={() => setValues(applyPreset(specs, values, spec!.presets.smoke))}>Smoke</button>
            )}
          </div>
          <div className="sub">Equivalent CLI</div>
          <code className="cli-preview">{cliPreview(specs, values)}</code>
        </details>
      )}

      <div className="row">
        <button onClick={start} disabled={running || !spec}>Optimize</button>
        <button onClick={stop} disabled={!running}>Stop</button>
      </div>
      {running && <div className="status">Running… {Math.round(job!.elapsed)}s</div>}
      {error && <div className="error">{error}</div>}
    </div>
  );
}
