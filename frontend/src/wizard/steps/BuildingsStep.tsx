import { useEffect, useState } from "react";
import { apiPreviewEdits } from "../../api";
import { CityMap } from "../../components/CityMap";
import { forServer, normalizeEdits } from "../../edits";
import { useCityStore } from "../../stores/cityStore";
import { StepNav } from "../StepNav";
import { addOne, changesSummary, removeAdded } from "../edits";
import { useT, useWizardStore } from "../wizardStore";
import { AddBuildingDialog } from "./AddBuildingDialog";

export function BuildingsStep() {
  const t = useT();
  const go = useWizardStore((s) => s.go);
  const city = useCityStore((s) => s.city);
  const edits = useCityStore((s) => s.edits);
  const setEdits = useCityStore((s) => s.setEdits);
  const editReport = useCityStore((s) => s.editReport);
  const setEditReport = useCityStore((s) => s.setEditReport);
  const [adding, setAdding] = useState(false);
  const [previewFailed, setPreviewFailed] = useState(false);
  const setViewMode = useCityStore((s) => s.setViewMode);

  // Back from Choose leaves the optimized layout on the map; clicks remove buildings only on the current one.
  useEffect(() => { setViewMode("current"); }, [setViewMode]);

  const cityId = city?.city_id;
  useEffect(() => {
    if (!cityId) return;
    if (edits.remove.length === 0 && edits.add.length === 0) {
      setEditReport(null);
      setPreviewFailed(false);
      return;
    }
    let stale = false;
    const timer = setTimeout(() => {
      apiPreviewEdits(cityId, forServer(normalizeEdits(edits)))
        .then((r) => { if (!stale) { setEditReport(r.report); setPreviewFailed(false); } })
        .catch(() => { if (!stale) setPreviewFailed(true); });
    }, 400);
    return () => { stale = true; clearTimeout(timer); };
  }, [cityId, edits, setEditReport]);

  const labels = {
    current: t("map.current"), optimized: t("map.optimized"), fit: t("map.fit"),
    townhall: t("map.townhall"), needsRoad: t("map.needsRoad"),
    removedClickToKeep: t("map.removedClickToKeep"),
  };
  const { removed, added } = changesSummary(edits);
  const overflow = editReport && !editReport.space.fits_without_roads ? editReport.space.overflow : 0;
  const tooBig = editReport !== null && !editReport.space.fits_without_roads;

  return (
    <section className="step-body">
      <h2>{t("step.buildings")}</h2>
      <p>{t("buildings.intro")}</p>
      <div className="buildings-layout">
        <div className="map-box"><CityMap labels={labels} editable /></div>
        <aside className="changes-panel">
          <h3>{t("buildings.changes")}</h3>
          <p>{t("buildings.removed", { n: removed })}</p>
          <p>{t("buildings.added", { n: added })}</p>
          <ul className="added-list">
            {edits.add.map((a) => (
              <li key={a.cityentity_id ?? a.label}>
                <span>{a.label ?? a.cityentity_id} ({a.size}) x{a.count}</span>
                <button type="button" className="link" aria-label={t("buildings.removeAdded")}
                  onClick={() => a.cityentity_id && setEdits(removeAdded(edits, a.cityentity_id))}>
                  ✕
                </button>
              </li>
            ))}
          </ul>
          <button type="button" className="btn" onClick={() => setAdding(true)}>
            {t("buildings.add")}
          </button>
          {removed === 0 && added === 0 && <p className="private-note">{t("buildings.nothing")}</p>}
          {tooBig && <p className="field-error">{t("buildings.overflow", { n: overflow })}</p>}
          {editReport?.cascades.map((c) => (
            <p key={c.main} className="cascade-note">{t("buildings.cascade", { main: c.main_name })}</p>
          ))}
          {previewFailed && <p className="field-error">{t("buildings.previewError")}</p>}
        </aside>
      </div>
      {adding && cityId && (
        <AddBuildingDialog
          cityId={cityId}
          onPick={(entry) => setEdits(addOne(edits, entry))}
          onClose={() => setAdding(false)}
        />
      )}
      <StepNav canBack={true} canNext={!tooBig} onBack={() => go(1)} onNext={() => go(3)} />
    </section>
  );
}
