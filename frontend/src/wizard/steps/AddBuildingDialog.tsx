import { useEffect, useState } from "react";
import { apiCatalog } from "../../api";
import type { CatalogEntry } from "../../types";
import { useT, useWizardStore } from "../wizardStore";

type Props = {
  cityId: string;
  onPick: (entry: CatalogEntry) => void;
  onClose: () => void;
};

export function AddBuildingDialog({ cityId, onPick, onClose }: Props) {
  const t = useT();
  const lang = useWizardStore((s) => s.lang);
  const [q, setQ] = useState("");
  const [rows, setRows] = useState<CatalogEntry[]>([]);
  const [failed, setFailed] = useState(false);
  const [pending, setPending] = useState(true);

  useEffect(() => {
    let stale = false;
    setPending(true);
    const timer = setTimeout(() => {
      apiCatalog(q.trim(), cityId, lang)
        .then((r) => { if (!stale) { setRows(r.results); setFailed(false); setPending(false); } })
        .catch(() => { if (!stale) { setFailed(true); setPending(false); } });
    }, 300);
    return () => { stale = true; clearTimeout(timer); };
  }, [q, cityId, lang]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  const empty = !pending && !failed && rows.length === 0;

  return (
    <div className="guide-backdrop" role="dialog" aria-modal="true" aria-label={t("buildings.addTitle")}>
      <div className="guide-modal add-dialog">
        <h3>{t("buildings.addTitle")}</h3>
        <input
          type="search" autoFocus value={q} placeholder={t("buildings.search")}
          aria-label={t("buildings.search")} onChange={(e) => setQ(e.target.value)}
        />
        {failed && <p className="field-error">{t("buildings.catalogError")}</p>}
        {pending && <p className="private-note">{t("buildings.searching")}</p>}
        {empty && (
          <p className="private-note">{t(q.trim() === "" ? "buildings.searchHint" : "buildings.noneFound")}</p>
        )}
        <ul className="catalog-list">
          {rows.map((r) => (
            <li key={r.id}>
              <button type="button" className="catalog-row" onClick={() => onPick(r)}>
                <span className="catalog-name">{r.name}</span>
                <span className="catalog-size">{r.width}x{r.length}</span>
                {(r.stored ?? 0) > 0 && (
                  <span className="catalog-stored">{t("buildings.stored", { n: r.stored ?? 0 })}</span>
                )}
              </button>
            </li>
          ))}
        </ul>
        <button type="button" className="btn" onClick={onClose}>{t("buildings.done")}</button>
      </div>
    </div>
  );
}
