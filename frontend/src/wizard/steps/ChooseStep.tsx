import { useEffect } from "react";
import { CityMap } from "../../components/CityMap";
import { useCityStore } from "../../stores/cityStore";
import { StepNav } from "../StepNav";
import { statRows } from "../stats";
import { useT, useWizardStore } from "../wizardStore";

export function ChooseStep() {
  const t = useT();
  const lang = useWizardStore((s) => s.lang);
  const go = useWizardStore((s) => s.go);
  const layouts = useWizardStore((s) => s.layouts);
  const selectedId = useWizardStore((s) => s.selectedId);
  const select = useWizardStore((s) => s.select);
  const city = useCityStore((s) => s.city);
  const applyImprovement = useCityStore((s) => s.applyImprovement);
  const setViewMode = useCityStore((s) => s.setViewMode);

  const selected = typeof selectedId === "number" ? layouts.find((l) => l.id === selectedId) ?? null : null;
  const onPlayer = selectedId === "player";
  const entry = selected;

  useEffect(() => {
    if (entry) {
      applyImprovement({
        k: entry.k ?? 0, achieved: entry.achieved, roads: entry.roads, buildings: entry.buildings,
        to_store: entry.to_store, added: entry.added,
      });
    } else if (onPlayer) {
      setViewMode("current");
    }
    // The entry object is stable per id; re-apply only when the choice changes.
  }, [entry?.id, onPlayer, applyImprovement, setViewMode]); // eslint-disable-line react-hooks/exhaustive-deps

  const labels = {
    current: t("map.current"), optimized: t("map.optimized"), fit: t("map.fit"),
    townhall: t("map.townhall"), needsRoad: t("map.needsRoad"),
    removedClickToKeep: t("map.removedClickToKeep"),
  };
  const before = city?.stats;
  const after = entry?.stats ?? before;
  const rows = before && after ? statRows(before, after, lang) : [];
  const best = layouts.length ? layouts[0].id : null;

  return (
    <section className="step-body">
      <h2>{t("step.choose")}</h2>
      <p>{t("choose.intro")}</p>
      <div className="layout-cards" role="listbox" aria-label={t("step.choose")}>
        {layouts.map((l) => (
          <button
            key={l.id}
            type="button"
            role="option"
            aria-selected={selectedId === l.id}
            className={`layout-card${selectedId === l.id ? " on" : ""}`}
            onClick={() => select(l.id)}
          >
            {t(l.id === best ? "choose.cardBest" : "choose.card", { n: l.stats.roads })}
          </button>
        ))}
        <button
          type="button"
          role="option"
          aria-selected={onPlayer}
          className={`layout-card player${onPlayer ? " on" : ""}`}
          onClick={() => select("player")}
        >
          {t("choose.player", { n: before?.roads ?? "–" })}
        </button>
      </div>
      <div className="buildings-layout">
        <div className="map-box"><CityMap labels={labels} editable={false} /></div>
        <aside className="changes-panel">
          <h3>{t("choose.beforeAfter")}</h3>
          <table className="stats-table">
            <thead>
              <tr><th></th><th>{t("choose.before")}</th><th>{t("choose.after")}</th></tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.key}><th scope="row">{t(r.key)}</th><td>{r.before}</td><td>{r.after}</td></tr>
              ))}
            </tbody>
          </table>
        </aside>
      </div>
      <StepNav canBack={true} canNext={entry !== null} onBack={() => go(3)} onNext={() => go(5)} />
    </section>
  );
}
