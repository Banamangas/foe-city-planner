import { useEffect, useState } from "react";
import { useCityStore } from "../stores/cityStore";
import { apiSaveLayout, apiLayouts, apiLayout } from "../api";
import type { LayoutListItem } from "../types";
import { forServer } from "../edits";

export function ResultPanel() {
  const city = useCityStore((s) => s.city);
  const optimized = useCityStore((s) => s.optimized);
  const optimizedRaw = useCityStore((s) => s.optimizedRaw);
  const applyImprovement = useCityStore((s) => s.applyImprovement);
  const edits = useCityStore((s) => s.edits);
  const [history, setHistory] = useState<LayoutListItem[]>([]);
  const [msg, setMsg] = useState("");

  const refresh = () => {
    if (!city) return;
    const cityId = city.city_id;
    apiLayouts(cityId)
      .then((h) => { if (useCityStore.getState().city?.city_id === cityId) setHistory(h); })
      .catch(() => {});
  };
  useEffect(() => { refresh(); }, [city]);

  if (!city) return null;
  const estimate = city.road_estimate;

  const save = async () => {
    if (!optimizedRaw) return;
    await apiSaveLayout({
      city_id: city.city_id, k: optimizedRaw.k, achieved: optimizedRaw.achieved,
      // A layout made for an edited city keeps its edit set, so reopening it
      // says which edits it was made for.
      layout_json: optimizedRaw.to_store || optimizedRaw.added
        ? { ...optimizedRaw, edits: optimizedRaw.edits ?? forServer(edits) } : optimizedRaw,
      roads_count: optimizedRaw.achieved,
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
    const cityId = city.city_id;
    try {
      const rec = await apiLayout(id);
      if (useCityStore.getState().city?.city_id !== cityId) return;  // stale
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
          {optimizedRaw?.added && optimizedRaw.added.length > 0 && (
            <div className="sub">
              Added: {optimizedRaw.added.map((a) => a.name).join(", ")}
            </div>
          )}
          {optimizedRaw?.to_store && optimizedRaw.to_store.length > 0 && (
            <details className="to-store">
              <summary>To store: {optimizedRaw.to_store.length} building(s)</summary>
              {optimizedRaw.to_store.map((s) => (
                <div className="brow" key={s.entity_id}>
                  <span className="bname">{s.name}</span>
                  <span className="bsize">{s.width}×{s.length}</span>
                  <span className="btype" title={s.reason}>
                    {s.reason === "removed" ? "removed" : "patch"}
                  </span>
                </div>
              ))}
            </details>
          )}
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
