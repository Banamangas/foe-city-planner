import { useEffect, useRef, useState } from "react";
import { useCityStore } from "../stores/cityStore";
import { apiLoad, apiCities, apiCity } from "../api";
import type { CityListItem } from "../types";

export function LoadPanel() {
  const setCity = useCityStore((s) => s.setCity);
  const [phase, setPhase] = useState<string>("");
  const [error, setError] = useState<string>("");
  const [cities, setCities] = useState<CityListItem[]>([]);
  const workerRef = useRef<Worker | null>(null);

  const refreshCities = () => apiCities().then(setCities).catch(() => {});
  useEffect(() => { refreshCities(); }, []);

  const loadSlim = async (slim: unknown) => {
    setPhase("uploading");
    try {
      const resp = await apiLoad(slim);
      setCity(resp);
      setPhase("");
      refreshCities();
    } catch (err) {
      setError(String(err));
      setPhase("");
    }
  };

  const onFile = (file: File) => {
    setError("");
    setPhase("parsing");
    const worker = new Worker(new URL("../workers/stripCity.worker.ts", import.meta.url), { type: "module" });
    workerRef.current = worker;
    worker.onmessage = (e: MessageEvent<any>) => {
      const msg = e.data;
      if (msg.phase === "error") { setError(msg.message); setPhase(""); worker.terminate(); return; }
      if (msg.phase === "done") { worker.terminate(); loadSlim(msg.slim); return; }
      setPhase(msg.phase);
    };
    worker.postMessage(file);
  };

  const onCityFile = async (file: File) => {
    setError("");
    try {
      const slim = JSON.parse(await file.text());
      loadSlim(slim);
    } catch (err) {
      setError(String(err));
    }
  };

  const loadCached = async (id: string) => {
    if (!id) return;
    setError("");
    try {
      const city = await apiCity(id);
      loadSlim(city.payload);
    } catch (err) {
      setError(String(err));
    }
  };

  return (
    <div className="panel">
      <h3>Load city</h3>
      <label className="filebtn">
        Choose FoE export (.json)
        <input type="file" accept=".json,application/json" hidden
          onChange={(e) => e.target.files?.[0] && onFile(e.target.files[0])} />
      </label>
      <label className="filebtn">
        Import .city
        <input type="file" accept=".city,.json" hidden
          onChange={(e) => e.target.files?.[0] && onCityFile(e.target.files[0])} />
      </label>
      {cities.length > 0 && (
        <select defaultValue="" onChange={(e) => loadCached(e.target.value)}>
          <option value="">Load cached city…</option>
          {cities.map((c) => (
            <option key={c.id} value={c.id}>{c.id} ({c.region_cells} cells)</option>
          ))}
        </select>
      )}
      {phase && <div className="status">Working… {phase}</div>}
      {error && <div className="error">{error}</div>}
    </div>
  );
}
