import { useCityStore } from "../../stores/cityStore";
import type { LoadChecks } from "../types";
import { useT } from "../wizardStore";

export function ChecksPanel({
  checks,
  chosen,
  onKeep,
}: {
  checks: LoadChecks;
  /** null until the player picks; then whether the unconnected buildings stay off the road. */
  chosen: boolean | null;
  onKeep: (keep: boolean) => void;
}) {
  const t = useT();
  const summaryById = useCityStore((s) => s.summaryById);
  const names = (ids: number[]) => ids.map((id) => summaryById.get(String(id))?.name ?? String(id));

  return (
    <div className="checks-panel">
      {checks.unconnected.length > 0 && (
        <div className="check">
          <p>{t("checks.unconnected")}</p>
          <ul>{names(checks.unconnected).map((n, i) => <li key={i}>{n}</li>)}</ul>
          <div className="check-actions">
            <button type="button" className={`btn${chosen === false ? " primary" : ""}`}
              onClick={() => onKeep(false)}>
              {t("checks.connect")}
            </button>
            <button type="button" className={`btn${chosen === true ? " primary" : ""}`}
              onClick={() => onKeep(true)}>
              {t("checks.leave")}
            </button>
          </div>
          {chosen !== null && (
            <p className="check-chosen">{t(chosen ? "checks.chosenLeave" : "checks.chosenConnect")}</p>
          )}
        </div>
      )}
      {checks.loose_chain_pieces.length > 0 && (
        <div className="check">
          <p>{t("checks.loose")}</p>
          <ul>{names(checks.loose_chain_pieces).map((n, i) => <li key={i}>{n}</li>)}</ul>
        </div>
      )}
    </div>
  );
}
