import { useEffect, useState } from "react";
import { useCityStore } from "../stores/cityStore";
import { apiSaveLayout, apiLayouts, apiLayout } from "../api";
import type { LayoutListItem } from "../types";

export function ResultPanel() {
  const city = useCityStore((s) => s.city);
  const optimized = useCityStore((s) => s.optimized);
  const optimizedRaw = useCityStore((s) => s.optimizedRaw);
  const applyImprovement = useCityStore((s) => s.applyImprovement);
  const [history, setHistory] = useState<LayoutListItem[]>([]);
  const [msg, setMsg] = useState("");

  const refresh = () => {
    if (city) apiLayouts(city.city_id).then(setHistory).catch(() => {});
  };
  useEffect(() => { refresh(); }, [city]);

  if (!city) return null;
  const estimate = city.road_estimate;

  const save = async () => {
    if (!optimizedRaw) return;
    await apiSaveLayout({
      city_id: city.city_id, k: optimizedRaw.k, achieved: optimizedRaw.achieved,
      layout_json: optimizedRaw, roads_count: optimizedRaw.achieved,
    });
    setMsg("saved");
    refresh();
  };

  const exportLayout = () => {
    if (!optimizedRaw) return;
    const blob = new Blob([JSON.stringify(optimizedRaw)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${city.city_id}-k${optimizedRaw.k}.layout.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const loadHistory = async (id: string) => {
    try {
      const rec = await apiLayout(id);
      if (rec?.layout) applyImprovement(rec.layout);
    } catch { /* ignore */ }
  };

  return (
    <div className="panel">
      <h3>Result</h3>
      {optimized ? (
        <div className="result">
          <div className="big">{optimized.achieved} roads</div>
          <div className="sub">was ~{estimate} · k={optimized.k}</div>
          <div className="row">
            <button onClick={save}>Save</button>
            <button onClick={exportLayout}>Export</button>
          </div>
          {msg && <div className="status">{msg}</div>}
        </div>
      ) : (
        <div className="sub">No optimized layout yet.</div>
      )}
      {history.length > 0 && (
        <div className="history">
          <h4>History</h4>
          {history.map((h) => (
            <div className="brow clickable" key={h.id} onClick={() => loadHistory(h.id)}>
              <span>{h.achieved} roads</span>
              <span className="bsize">k={h.k}</span>
              <span className="btype">{h.created_at}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
