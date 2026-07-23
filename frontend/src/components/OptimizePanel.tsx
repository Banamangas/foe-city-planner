import { useRef, useState } from "react";
import { useCityStore } from "../stores/cityStore";
import { apiOptimize, apiStop, openStream } from "../api";

export function OptimizePanel() {
  const city = useCityStore((s) => s.city);
  const job = useCityStore((s) => s.job);
  const applyImprovement = useCityStore((s) => s.applyImprovement);
  const setJob = useCityStore((s) => s.setJob);
  const [minutes, setMinutes] = useState(5);
  const [seedPolish, setSeedPolish] = useState(0);
  const [error, setError] = useState("");
  const esRef = useRef<EventSource | null>(null);

  const running = job?.state === "running";

  const start = async () => {
    if (!city) return;
    setError("");
    try {
      const { job_id } = await apiOptimize({
        city_id: city.city_id,
        time_box: minutes * 60,
        ...(seedPolish > 0 ? { seed_polish: seedPolish } : {}),
      });
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
      <label className="row">
        Time-box (min)
        <input type="number" min={1} max={120} value={minutes}
          onChange={(e) => setMinutes(Math.max(1, Number(e.target.value) || 1))} disabled={running} />
      </label>
      <label className="row" title="After the search, re-solve the best skeleton under this many solver seeds and keep a lower road count. 0 = off. Adds up to this many probe budgets of extra time.">
        Seed-polish (0 = off)
        <input type="number" min={0} max={64} value={seedPolish}
          onChange={(e) => setSeedPolish(Math.max(0, Number(e.target.value) || 0))} disabled={running} />
      </label>
      <div className="row">
        <button onClick={start} disabled={running}>Optimize</button>
        <button onClick={stop} disabled={!running}>Stop</button>
      </div>
      {running && <div className="status">Running… {Math.round(job!.elapsed)}s</div>}
      {error && <div className="error">{error}</div>}
    </div>
  );
}
