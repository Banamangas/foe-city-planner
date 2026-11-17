import { useMemo, useState } from "react";
import { useCityStore } from "../stores/cityStore";
import { sameTypeIds, setRemoved, toggleRemove } from "../edits";

type Filter = "all" | "road" | "plain" | "townhall" | "removed";

export function BuildingsPanel() {
  const city = useCityStore((s) => s.city);
  const edits = useCityStore((s) => s.edits);
  const setEdits = useCityStore((s) => s.setEdits);
  const [q, setQ] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const removed = useMemo(() => new Set(edits.remove), [edits]);

  const rows = useMemo(() => {
    const all = city?.buildings ?? [];
    const ql = q.toLowerCase();
    return all.filter((b) => {
      if (ql && !b.name.toLowerCase().includes(ql)) return false;
      if (filter === "road") return b.needs_road && !b.is_townhall;
      if (filter === "plain") return !b.needs_road && !b.is_townhall;
      if (filter === "townhall") return b.is_townhall;
      if (filter === "removed") return removed.has(Number(b.entity_id));
      return true;
    });
  }, [city, q, filter, removed]);

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
          <option value="removed">removed</option>
        </select>
      </div>
      <div className="btable">
        {rows.map((b, i) => {
          const id = Number(b.entity_id);
          const off = removed.has(id);
          const same = b.is_townhall ? [] : sameTypeIds(city.buildings, b);
          const allOff = same.length > 0 && same.every((x) => removed.has(x));
          return (
            <div className={off ? "brow removed" : "brow"} key={`${b.entity_id}-${i}`}>
              <span className="bname" title={b.cityentity_id}>
                {b.name}{b.chain_id ? (b.is_chain_head ? " ⛓" : " ·⛓") : ""}
              </span>
              <span className="bsize">{b.width}×{b.length}</span>
              <span className="btype">{b.is_townhall ? "townhall" : b.needs_road ? "road" : "plain"}</span>
              {!b.is_townhall && (
                <>
                  <button className="mini" title={off ? "keep this building" : "remove this building"}
                    onClick={() => setEdits(toggleRemove(edits, id, city.buildings))}>
                    {off ? "keep" : "remove"}
                  </button>
                  {same.length > 1 && (
                    <button className="mini" title={`${allOff ? "keep" : "remove"} all ${same.length} of this type`}
                      onClick={() => setEdits(setRemoved(edits, same, !allOff, city.buildings))}>
                      {allOff ? "keep" : "remove"} all {same.length}
                    </button>
                  )}
                </>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
