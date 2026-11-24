import { useEffect, useRef, useState } from "react";
import { useCityStore } from "../stores/cityStore";
import type { Job } from "../stores/cityStore";
import { apiOptimize, apiOptions, apiStop, openStream } from "../api";
import { forServer, isEmptyEdits } from "../edits";
import {
  applyPreset, budgetWarning, byGroup, cliPreview, initialValues, isModified,
  modifiedCount, screenBanner, secondsToMinutes,
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
  const banner = screenBanner(screen);
  if (!banner) return null;
  return (
    <div className={banner.severity === "bad" ? "screen-bad" : "screen-warn"}>
      <strong>{banner.heading}</strong>
      <div className="screen-reason">{screen.reason}</div>
      <div className="screen-detail">
        road pressure {screen.road_pressure} · {screen.consumers} buildings need
        road access · {screen.slack} free cells
      </div>
      {banner.canStillRun && (
        <div className="screen-detail">You can still run it — this is a prediction, not a limit.</div>
      )}
    </div>
  );
}

/** Final report of a finished run: what came out and whether it is game-legal. */
function RunReport({ job }: { job: Job }) {
  const r = job.result;
  const legality = r?.legality;
  const best = r?.best_achieved;
  // The upload (or the edited city) was published first; nothing beat it.
  const start = r?.seed_input?.used ? r.seed_input.roads : null;
  const noGain = best != null && start != null && best >= start;
  return (
    <div className="status">
      {job.stopped ? "Stopped" : "Finished"} after {Math.round(job.elapsed)}s
      {best != null ? ` · best ${best} roads` : " · no layout found"}
      {r?.verdict && r.verdict !== "DONE" && !noGain ? ` · ${r.verdict}` : ""}
      {legality && (
        <span className={legality.status === "valid" ? "" : "error"}>
          {" · "}{legality.status === "valid" ? "game-legal" : `legality: ${legality.status}`}
          {legality.military === "unconnected" ? " (two-lane buildings left unconnected)" : ""}
        </span>
      )}
      {noGain && (
        <div className="sub">
          No layout with fewer roads than the starting city ({start}) was found, so the
          result is the starting city itself{job.stopped ? "" : "; a longer run may still find one"}.
        </div>
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
  const [seedNote, setSeedNote] = useState("");
  const edits = useCityStore((s) => s.edits);
  const esRef = useRef<EventSource | null>(null);
  // The server-side run this panel owns. A ref, not store state: loading a new
  // city clears the store's job BEFORE the cleanup below runs.
  const activeJobRef = useRef<string | null>(null);

  // The parameter list is served, not hardcoded: adding a knob to
  // webapp/params.py makes it appear here with no frontend change.
  useEffect(() => {
    apiOptions()
      .then((res) => { setSpec(res); setValues(initialValues(res.options)); })
      .catch((err) => setError(String(err)));
  }, []);

  const running = job?.state === "running" || job?.state === "submitting";

  // Leaving a city (or unmounting) closes its stream and stops its run, so no
  // late event can write into the next city and the server slot is freed.
  useEffect(() => {
    return () => {
      esRef.current?.close();
      esRef.current = null;
      if (activeJobRef.current) apiStop(activeJobRef.current).catch(() => {});
      activeJobRef.current = null;
    };
  }, [city?.city_id]);
  const specs = spec?.options ?? [];
  const basic = specs.filter((s) => s.advanced === false);
  const advanced = specs.filter((s) => s.advanced !== false);
  const changed = modifiedCount(advanced, values);
  const set = (name: string, v: string | boolean) =>
    setValues((prev) => ({ ...prev, [name]: v }));

  const start = async () => {
    if (!city || running) return;   // no double submit
    const cityId = city.city_id;
    setError("");
    setJob({ id: "", cityId, state: "submitting", elapsed: 0 });
    try {
      // Plan E: an edited city sends its edit set; an unedited one sends
      // exactly the historical body.
      const edited = !isEmptyEdits(edits);
      const res = await apiOptimize(edited
        ? { city_id: cityId, ...values, edits: forServer(edits) }
        : { city_id: cityId, ...values });
      const job_id = res.job_id;
      const seed = (res as { report?: { seed?: { possible: boolean; reason: string | null } } }).report?.seed;
      setSeedNote(edited && seed && !seed.possible
        ? `Edited city: no instant first result (${seed.reason}); the search starts from scratch.`
        : "");
      const current = () => {
        const j = useCityStore.getState().job;
        return j !== null && j.id === job_id && j.cityId === cityId;
      };
      if (useCityStore.getState().city?.city_id !== cityId) {
        apiStop(job_id).catch(() => {});   // the user moved on while submitting
        return;
      }
      esRef.current?.close();
      activeJobRef.current = job_id;
      setJob({ id: job_id, cityId, state: "running", elapsed: 0 });
      esRef.current = openStream(job_id, {
        onImprovement: (imp) => applyImprovement(imp, job_id),
        onHeartbeat: (st) => {
          if (current()) setJob({ id: job_id, cityId, state: "running", elapsed: st.elapsed ?? 0 });
        },
        onDone: (env) => {
          if (activeJobRef.current === job_id) activeJobRef.current = null;
          if (!current()) return;
          setJob({
            id: job_id, cityId, state: env?.state === "error" ? "error" : "done",
            elapsed: env?.elapsed ?? 0, error: env?.error ?? null,
            result: env?.result ?? null, stopped: env?.stopped ?? false,
          });
        },
      });
    } catch (err) {
      setJob(null);
      setError(err instanceof Error ? err.message : String(err));
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
            title="Best measured configuration: at a 10-minute box it reached darkzig 88 (game-legal: two-lane tile and chains kept), FR16 67, FR17 103, FR24 220 roads (2 minutes: 88-91, 67, 106). Non-uniform skeletons in the productive quality band, the symmetry-free position model, a placement objective on every feasible skeleton plus an end-of-run objective polish, a rebased polish on the roads actually kept, the solver's own road network when it is smaller, exact filler repair and an exact road finish. A legal uploaded city is the starting point, so dense cities still get polished. Seed polish is off: it does not pay inside a short box."
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

      {budgetWarning(values) && (
        <div className="screen-warn">
          <strong>Budget mismatch</strong>
          <div className="screen-reason">{budgetWarning(values)}</div>
        </div>
      )}

      {!isEmptyEdits(edits) && (
        <div className="sub">
          Runs on the edited city: {edits.remove.length} removed, {edits.add.reduce((n, a) => n + a.count, 0)} added.
        </div>
      )}
      <div className="row">
        <button onClick={start} disabled={running || !spec}>Optimize</button>
        <button onClick={stop} disabled={!running}>Stop</button>
      </div>
      {running && (
        <div className="status">
          {job!.state === "submitting" ? "Starting…" : `Running… ${Math.round(job!.elapsed)}s`}
        </div>
      )}
      {job?.state === "error" && (
        <div className="error">Run failed after {Math.round(job.elapsed)}s: {job.error}</div>
      )}
      {job?.state === "done" && <RunReport job={job} />}
      {seedNote && <div className="sub">{seedNote}</div>}
      {error && <div className="error">{error}</div>}
    </div>
  );
}
