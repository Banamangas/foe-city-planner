import { useEffect, useMemo, useRef, useState } from "react";
import { useCityStore } from "../stores/cityStore";
import { apiCatalog, apiPreviewEdits, apiSaveEdits } from "../api";
import {
  addAt, catalogAdd, chainMains, chainNotices, customAdd, dropAddAt, forServer, isEmptyEdits,
  isPatch, setRelink, setRemoved,
} from "../edits";
import type { CatalogEntry } from "../types";

/** Plan E: the city's edit set -- summary bar, chain notices, additions.
 *  Removals are toggled in the Buildings list or by clicking the map. Every
 *  change is saved with the city and previewed by the server, which owns the
 *  chain rules (reattach, store, end-of-chain slots) and the space pre-check. */
export function EditsPanel() {
  const city = useCityStore((s) => s.city);
  const edits = useCityStore((s) => s.edits);
  const setEdits = useCityStore((s) => s.setEdits);
  const report = useCityStore((s) => s.editReport);
  const editError = useCityStore((s) => s.editError);
  const setEditReport = useCityStore((s) => s.setEditReport);
  const summaryById = useCityStore((s) => s.summaryById);
  const savedFor = useRef<string | null>(null);

  // Save + preview, debounced. The first run after a city load only previews
  // (the edits came from the server).
  useEffect(() => {
    if (!city) return;
    const cityId = city.city_id;
    const skipSave = savedFor.current !== cityId;
    savedFor.current = cityId;
    const t = setTimeout(() => {
      const body = forServer(edits);
      if (!skipSave) apiSaveEdits(cityId, body).catch(() => {});
      if (isEmptyEdits(edits)) { setEditReport(null); return; }
      apiPreviewEdits(cityId, body)
        .then((r) => { if (useCityStore.getState().city?.city_id === cityId) setEditReport(r.report); })
        .catch((err) => {
          if (useCityStore.getState().city?.city_id === cityId) {
            setEditReport(null, err instanceof Error ? err.message : String(err));
          }
        });
    }, 250);
    return () => clearTimeout(t);
  }, [city?.city_id, edits]);

  if (!city) return null;
  const nameOf = (id: number) => summaryById.get(String(id))?.name ?? String(id);
  const notices = report ? chainNotices(report, nameOf) : [];
  const sp = report?.space;

  return (
    <div className="panel">
      <h3>City edits</h3>
      <div className="edit-summary">
        <span>removed {edits.remove.length}{sp ? ` (${sp.removed_cells} cells)` : ""}</span>
        <span>added {edits.add.reduce((n, a) => n + a.count, 0)}{sp ? ` (${sp.added_cells} cells)` : ""}</span>
        {sp && <span>free after edits {sp.free_cells}</span>}
      </div>
      {isEmptyEdits(edits) && (
        <div className="sub">Click buildings on the map or use "remove" in the list; add new ones below.</div>
      )}
      {sp && !sp.fits_without_roads && (
        <div className="screen-bad">
          <strong>Does not fit</strong>
          <div className="screen-reason">
            The new buildings need {sp.overflow} more cells than the city has free, even with zero roads.
          </div>
        </div>
      )}
      {sp && sp.fits_without_roads && !sp.fits_with_upload_roads && (
        <div className="screen-warn">
          Tight: {sp.free_cells} free cells for roads, the upload uses {sp.upload_roads}.
        </div>
      )}
      {report && !isEmptyEdits(edits) && (
        <div className="sub">
          {report.seed.possible
            ? "The edited upload is legal: it is the instant first result."
            : `No instant first result: ${report.seed.reason}.`}
        </div>
      )}
      {editError && <div className="error">{editError}</div>}

      {notices.map((n, i) => (
        <div key={i} className={n.kind === "warn" ? "edit-notice warn" : "edit-notice"}>
          <div>{n.text}</div>
          {n.kind === "reattach" && n.ids && !report?.reattached.find((r) => r.relinked && r.moved === n.ids) && (
            <button onClick={() => setEdits(setRemoved(edits, n.ids!, true, city.buildings))}>
              remove them too
            </button>
          )}
          {n.kind === "store" && n.candidates && n.candidates.length > 0 && (
            <label className="row">
              <span className="sub">attach them to</span>
              <select value={String(edits.relink?.[String(n.main)] ?? "")}
                onChange={(e) => setEdits(setRelink(edits, n.main!,
                  e.target.value ? Number(e.target.value) : null))}>
                <option value="">— store them —</option>
                {n.candidates.map((c) => (
                  <option key={c.entity_id} value={c.entity_id}>{c.name} (#{c.entity_id})</option>
                ))}
              </select>
            </label>
          )}
        </div>
      ))}
      {Object.entries(edits.relink ?? {}).map(([main, target]) => {
        const r = report?.reattached.find((x) => x.relinked && x.removed === Number(main));
        return r ? (
          <div key={main} className="edit-notice">
            Patches of {nameOf(Number(main))} will be attached to {r.to_name ?? target}
            <button onClick={() => setEdits(setRelink(edits, Number(main), null))}>store them instead</button>
          </div>
        ) : null;
      })}

      {edits.remove.length > 0 && (
        <div className="row">
          <button onClick={() => setEdits({ ...edits, remove: [], relink: {} })}>
            Restore all removed
          </button>
        </div>
      )}

      <AddBuildings />

      {edits.add.length > 0 && (
        <div className="btable">
          {edits.add.map((a, i) => (
            <div className="brow" key={i}>
              <span className="bname">
                {a.count} × {a.label ?? a.cityentity_id ?? a.name}
                {a.link_to !== undefined ? ` → ${nameOf(a.link_to)}` : ""}
              </span>
              <span className="bsize">{a.size}</span>
              <button className="mini" onClick={() => setEdits(dropAddAt(edits, i))}>✕</button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function AddBuildings() {
  const city = useCityStore((s) => s.city)!;
  const edits = useCityStore((s) => s.edits);
  const setEdits = useCityStore((s) => s.setEdits);
  const [q, setQ] = useState("");
  const [results, setResults] = useState<CatalogEntry[]>([]);
  const [picked, setPicked] = useState<CatalogEntry | null>(null);
  const [count, setCount] = useState("1");
  const [linkTo, setLinkTo] = useState("");
  const [custom, setCustom] = useState({ w: "2", l: "2", road: false, name: "" });
  const [err, setErr] = useState("");

  useEffect(() => {
    if (q.trim().length < 2) { setResults([]); return; }
    const t = setTimeout(() => {
      apiCatalog(q, city.city_id).then((r) => setResults(r.results)).catch((e) => setErr(String(e)));
    }, 250);
    return () => clearTimeout(t);
  }, [q, city.city_id]);

  const mains = useMemo(
    () => (picked && isPatch(picked) ? chainMains(city.buildings, picked.chain_id!, edits) : []),
    [picked, city, edits]);

  const addPicked = () => {
    if (!picked) return;
    setErr("");
    if (isPatch(picked) && mains.length > 1 && !linkTo) {
      setErr("This is a chain patch and the city has several main buildings of that chain: choose one.");
      return;
    }
    const target = isPatch(picked) && mains.length > 1 ? Number(linkTo) : undefined;
    setEdits(addAt(edits, catalogAdd(picked, Number(count), target)));
    setPicked(null); setQ(""); setCount("1"); setLinkTo("");
  };

  const addCustom = () => {
    const w = Number(custom.w), l = Number(custom.l);
    if (!(w >= 1 && l >= 1 && w <= 20 && l <= 20)) { setErr("Size must be 1..20 x 1..20"); return; }
    setErr("");
    setEdits(addAt(edits, customAdd(w, l, custom.road, custom.name, Number(count))));
  };

  return (
    <details className="advanced add-buildings">
      <summary>Add buildings</summary>
      <input placeholder="search the catalog (name or id)…" value={q}
        onChange={(e) => { setQ(e.target.value); setPicked(null); }} />
      {!picked && results.length > 0 && (
        <div className="btable">
          {results.map((r) => (
            <div className="brow clickable" key={r.id} onClick={() => setPicked(r)} title={r.id}>
              <span className="bname">{r.name}</span>
              <span className="bsize">{r.width}×{r.length}</span>
              <span className="btype">
                {r.needs_road ? (r.road_level >= 2 ? "2-lane" : "road") : "plain"}
                {r.chain_id ? (r.is_chain_head ? " · chain" : " · patch") : ""}
              </span>
            </div>
          ))}
        </div>
      )}
      {picked && (
        <div className="edit-notice">
          <div><strong>{picked.name}</strong> {picked.width}×{picked.length}
            {picked.needs_road ? " · needs road" : ""}</div>
          {isPatch(picked) && mains.length === 0 && (
            <div className="error">No main building of this chain in the city; add the main building too.</div>
          )}
          {isPatch(picked) && mains.length === 1 && (
            <div className="sub">links to {mains[0].name}, at the end of its chain</div>
          )}
          {isPatch(picked) && mains.length > 1 && (
            <label className="row">
              <span className="sub">link to</span>
              <select value={linkTo} onChange={(e) => setLinkTo(e.target.value)}>
                <option value="">— choose a main building —</option>
                {mains.map((m) => (
                  <option key={String(m.entity_id)} value={String(m.entity_id)}>
                    {m.name} (#{m.entity_id})
                  </option>
                ))}
              </select>
            </label>
          )}
          <div className="row">
            <span className="sub">count</span>
            <input type="number" min={1} max={50} value={count} onChange={(e) => setCount(e.target.value)} />
            <button onClick={addPicked}>Add</button>
            <button onClick={() => setPicked(null)}>Cancel</button>
          </div>
        </div>
      )}
      <h4>Custom size (not in the catalog)</h4>
      <div className="row">
        <input type="number" min={1} max={20} value={custom.w} title="width"
          onChange={(e) => setCustom({ ...custom, w: e.target.value })} />
        ×
        <input type="number" min={1} max={20} value={custom.l} title="length"
          onChange={(e) => setCustom({ ...custom, l: e.target.value })} />
        <label className="row"><input type="checkbox" checked={custom.road}
          onChange={(e) => setCustom({ ...custom, road: e.target.checked })} />road</label>
      </div>
      <div className="row">
        <input placeholder="name (optional)" value={custom.name}
          onChange={(e) => setCustom({ ...custom, name: e.target.value })} />
        <button onClick={addCustom}>Add</button>
      </div>
      {err && <div className="error">{err}</div>}
    </details>
  );
}
