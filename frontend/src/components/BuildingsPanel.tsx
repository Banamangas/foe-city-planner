import { useMemo, useState } from "react";
import { useCityStore } from "../stores/cityStore";

type Filter = "all" | "road" | "plain" | "townhall";

export function BuildingsPanel() {
  const city = useCityStore((s) => s.city);
  const [q, setQ] = useState("");
  const [filter, setFilter] = useState<Filter>("all");

  const rows = useMemo(() => {
    const all = city?.buildings ?? [];
    const ql = q.toLowerCase();
    return all.filter((b) => {
      if (ql && !b.name.toLowerCase().includes(ql)) return false;
      if (filter === "road") return b.needs_road && !b.is_townhall;
      if (filter === "plain") return !b.needs_road && !b.is_townhall;
      if (filter === "townhall") return b.is_townhall;
      return true;
    });
  }, [city, q, filter]);

  if (!city) return null;
  const roadCount = city.buildings.filter((b) => b.needs_road && !b.is_townhall).length;

  return (
    <div className="panel">
      <h3>Buildings ({city.buildings.length} · {roadCount} road-needing)</h3>
      <div className="row">
        <input placeholder="search…" value={q} onChange={(e) => setQ(e.target.value)} />
        <select value={filter} onChange={(e) => setFilter(e.target.value as Filter)}>
          <option value="all">all</option>
          <option value="road">road-needing</option>
          <option value="plain">plain</option>
          <option value="townhall">townhall</option>
        </select>
      </div>
      <div className="btable">
        {rows.map((b, i) => (
          <div className="brow" key={`${b.entity_id}-${i}`}>
            <span className="bname">{b.name}</span>
            <span className="bsize">{b.width}×{b.length}</span>
            <span className="btype">{b.is_townhall ? "townhall" : b.needs_road ? "road" : "plain"}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
