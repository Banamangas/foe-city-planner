import { useEffect, useRef, useState } from "react";
import { apiOptimizeResult, apiOptions, apiStop, openStream } from "../../api";
import { useCityStore } from "../../stores/cityStore";
import {
  afterRun, buildOptimizeBody, CUSTOM_MAX, CUSTOM_MIN, DEFAULT_MINUTES, PHASE_STEPS, phaseIndex,
  progressPct, RUN_PRESETS_MIN, startDecision, timeLeft,
} from "../run";
import { StepNav } from "../StepNav";
import type { LayoutEntry, MachineInfo } from "../types";
import { useT, useWizardStore } from "../wizardStore";

type Notice = { kind: "none_found" | "failed" | "overflow"; n?: number; details?: string } | null;

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/** Stop an old job and wait (max 10 s) until the server reports it finished. */
async function stopAndWait(jobId: string): Promise<void> {
  const deadline = Date.now() + 10_000;
  while (Date.now() < deadline) {
    try {
      const r = await apiStop(jobId);
      if (r?.already_done) return;
    } catch {
      return;
    }
    await sleep(500);
  }
}

export function OptimizeStep() {
  const t = useT();
  const go = useWizardStore((s) => s.go);
  const run = useWizardStore((s) => s.run);
  const setRun = useWizardStore((s) => s.setRun);
  const layouts = useWizardStore((s) => s.layouts);
  const addLayouts = useWizardStore((s) => s.addLayouts);
  const select = useWizardStore((s) => s.select);
  const keepUnconnected = useWizardStore((s) => s.keepUnconnected);
  const city = useCityStore((s) => s.city);
  const edits = useCityStore((s) => s.edits);

  const [minutes, setMinutes] = useState(DEFAULT_MINUTES);
  const [custom, setCustom] = useState(false);
  const [machine, setMachine] = useState<MachineInfo | null>(null);
  const [best, setBest] = useState<Record<string, unknown> | null>(null);
  const [starting, setStarting] = useState(false);
  const [notice, setNotice] = useState<Notice>(null);
  const [copied, setCopied] = useState(false);
  const esRef = useRef<EventSource | null>(null);
  const aliveRef = useRef(true);

  useEffect(() => {
    aliveRef.current = true;
    apiOptions()
      .then((o) => {
        if (!aliveRef.current) return;
        setBest(o.presets.best);
        setMachine(o.machine ?? null);
      })
      .catch(() => {
        if (aliveRef.current) setNotice({ kind: "failed" });
      });
    return () => {
      aliveRef.current = false;
      esRef.current?.close();
      esRef.current = null;
    };
  }, []);

  const running = run?.state === "running";
  const bestRoads = layouts.length ? Math.min(...layouts.map((l) => l.stats.roads)) : null;

  const finish = (state: "done" | "error", extra: LayoutEntry[], details?: string) => {
    esRef.current?.close();
    esRef.current = null;
    if (extra.length) addLayouts(extra);
    const all = useWizardStore.getState().layouts;
    const next = afterRun(all, state);
    if (next === "choose") {
      select(all[0].id);
      go(4);
    } else {
      setNotice({ kind: next, details });
    }
  };

  const attach = (jobId: string, timeBoxS: number) => {
    esRef.current = openStream(jobId, {
      onLayout: (e) => aliveRef.current && addLayouts([e]),
      onHeartbeat: (d) => {
        if (!aliveRef.current) return;
        const prev = useWizardStore.getState().run?.maxPhaseIdx ?? 0;
        setRun({
          elapsed: d.elapsed ?? 0,
          phase: d.phase ?? null,
          maxPhaseIdx: phaseIndex(d.phase ?? null, prev),
          layoutsFound: d.layouts_found ?? 0,
        });
      },
      onDone: (d) => {
        if (!aliveRef.current) return;
        const state = d.state === "error" ? "error" : "done";
        setRun({ state, stopped: !!d.stopped, elapsed: d.elapsed ?? timeBoxS, error: d.error ?? null });
        finish(state, d.result?.layouts ?? [], d.error ?? undefined);
      },
    });
  };

  const start = async () => {
    if (!city || !best || starting) return;
    setNotice(null);
    setStarting(true);
    const body = buildOptimizeBody({
      cityId: city.city_id,
      best,
      minutes,
      edits,
      keepUnconnected: keepUnconnected ?? [],
    });
    let r = await apiOptimizeResult(body);
    let decision = startDecision(r, false);
    if (typeof decision === "object") {
      await stopAndWait(decision.stopThenRetry);
      r = await apiOptimizeResult(body);
      decision = startDecision(r, true);
    }
    if (!aliveRef.current) return;
    setStarting(false);
    if (decision !== "started" || !r.ok) {
      const space = !r.ok ? r.body?.space : null;
      if (space && space.fits_without_roads === false) {
        setNotice({ kind: "overflow", n: space.overflow });
      } else {
        setNotice({ kind: "failed", details: !r.ok ? JSON.stringify(r.body) : undefined });
      }
      return;
    }
    setRun({
      jobId: r.job_id, state: "running", stopped: false, elapsed: 0, timeBoxS: minutes * 60,
      phase: null, maxPhaseIdx: 0, layoutsFound: 0, error: null,
    });
    attach(r.job_id, minutes * 60);
  };

  const copy = async (details: string) => {
    try {
      await navigator.clipboard?.writeText(details);
      setCopied(true);
    } catch {
      /* clipboard blocked: nothing to confirm */
    }
  };

  const setCustomMinutes = (raw: string) => {
    const n = Math.round(Number(raw));
    if (Number.isFinite(n)) setMinutes(Math.min(CUSTOM_MAX, Math.max(CUSTOM_MIN, n)));
  };

  const noticeText = notice
    ? notice.kind === "overflow"
      ? t("buildings.overflow", { n: notice.n ?? 0 })
      : notice.kind === "none_found"
        ? t("run.noneFound")
        : t("run.failed")
    : null;

  return (
    <section className="step-body">
      <h2>{t("step.optimize")}</h2>
      {!running && (
        <div className="run-setup">
          <h3>{t("run.title")}</h3>
          <div className="run-presets" role="group" aria-label={t("run.title")}>
            {RUN_PRESETS_MIN.map((m) => (
              <button
                key={m}
                type="button"
                className={`btn${!custom && minutes === m ? " on" : ""}`}
                aria-pressed={!custom && minutes === m}
                onClick={() => { setCustom(false); setMinutes(m); }}
              >
                {t("run.minutes", { n: m })}
              </button>
            ))}
            <button
              type="button"
              className={`btn${custom ? " on" : ""}`}
              aria-pressed={custom}
              onClick={() => setCustom(true)}
            >
              {t("run.custom")}
            </button>
            {custom && (
              <label className="run-custom">
                {t("run.customMinutes")}
                <input
                  type="number"
                  min={CUSTOM_MIN}
                  max={CUSTOM_MAX}
                  value={minutes}
                  onChange={(e) => setCustomMinutes(e.target.value)}
                />
              </label>
            )}
          </div>
          <p className="private-note">{t("run.hint")}</p>
          {machine && (
            <div className="run-machine">
              <p className="private-note">
                {t("run.machine", { cpus: machine.logical_cpus ?? machine.threads, threads: machine.threads })}
              </p>
              {machine.reduced && <p className="cascade-note">{t("run.reduced")}</p>}
              {machine.warn && <p className="cascade-note">{t("run.warn")}</p>}
            </div>
          )}
          <button
            type="button"
            className="btn primary"
            disabled={!city || !best || starting}
            onClick={start}
          >
            {starting ? t("run.starting") : t("run.start")}
          </button>
        </div>
      )}
      {running && run && (
        <div className="run-progress">
          <div
            className="progress-bar"
            role="progressbar"
            aria-label={t("run.progress")}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={progressPct(run.elapsed, run.timeBoxS, false)}
          >
            <div className="progress-fill" style={{ width: `${progressPct(run.elapsed, run.timeBoxS, false)}%` }} />
          </div>
          <ul className="phase-list">
            {PHASE_STEPS.map((p, i) => {
              const status = i < run.maxPhaseIdx ? "done" : i === run.maxPhaseIdx ? "current" : "upcoming";
              const mark = status === "done" ? "✓" : status === "current" ? "▶" : "○";
              return (
                <li key={p.key} className={`phase ${status}`} aria-current={status === "current" ? "step" : undefined}>
                  <span className="phase-mark" aria-hidden="true">{mark}</span> {t(p.key)}
                </li>
              );
            })}
          </ul>
          <dl className="run-numbers">
            <div><dt>{t("run.roadsBefore")}</dt><dd data-testid="roads-before">{city?.stats?.roads ?? "–"}</dd></div>
            <div><dt>{t("run.roadsBest")}</dt><dd data-testid="roads-best">{bestRoads ?? "–"}</dd></div>
            <div><dt>{t("run.layouts")}</dt><dd data-testid="layouts-found">{run.layoutsFound}</dd></div>
            <div><dt>{t("run.timeLeft")}</dt><dd data-testid="time-left">{timeLeft(run.elapsed, run.timeBoxS)}</dd></div>
          </dl>
          <button type="button" className="btn" onClick={() => { void apiStop(run.jobId).catch(() => undefined); }}>
            {t("run.stop")}
          </button>
        </div>
      )}
      {noticeText && (
        <div className="problem">
          <p className={notice?.kind === "none_found" ? undefined : "field-error"}>{noticeText}</p>
          {notice?.kind === "failed" && (
            <>
              <button type="button" className="btn" onClick={() => copy(notice.details ?? "")}>
                {t("error.copyDetails")}
              </button>
              {copied && <span className="copied"> {t("error.copied")}</span>}
            </>
          )}
        </div>
      )}
      <StepNav canBack={!running && !starting} canNext={false} onBack={() => go(2)} onNext={() => go(4)} />
    </section>
  );
}
