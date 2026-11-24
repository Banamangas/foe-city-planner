import { useState } from "react";
import { validateCustom, type CustomBuildings } from "../loadCity";
import { useT } from "../wizardStore";

type Item = { cityentity_id: string; count: number };
type Row = { width: string; length: string; road: string };

export function UnknownBuildingsForm({
  items,
  onSubmit,
}: {
  items: Item[];
  onSubmit: (custom: CustomBuildings) => void;
}) {
  const t = useT();
  const [rows, setRows] = useState<Record<string, Row>>(() =>
    Object.fromEntries(items.map((i) => [i.cityentity_id, { width: "1", length: "1", road: "0" }])),
  );
  const [invalid, setInvalid] = useState(false);
  const set = (id: string, patch: Partial<Row>) =>
    setRows((r) => ({ ...r, [id]: { ...r[id], ...patch } }));

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const custom = Object.fromEntries(
      Object.entries(rows).map(([id, r]) => [
        id,
        { width: Number(r.width), length: Number(r.length), road: Number(r.road) as 0 | 1 | 2 },
      ]),
    ) as CustomBuildings;
    if (validateCustom(custom).length > 0) {
      setInvalid(true);
      return;
    }
    setInvalid(false);
    onSubmit(custom);
  };

  return (
    <form className="unknown-form" onSubmit={submit}>
      <h3>{t("unknown.title")}</h3>
      <p>{t("unknown.intro")}</p>
      {items.map((i) => {
        const id = i.cityentity_id;
        return (
          <div className="unknown-row" key={id} data-testid="unknown-row">
            <span className="unknown-name">
              {t("unknown.building")} {id} × {i.count}
            </span>
            <label>
              {t("unknown.width")}
              <input type="number" min={1} max={20} value={rows[id].width}
                onChange={(e) => set(id, { width: e.target.value })} />
            </label>
            <label>
              {t("unknown.length")}
              <input type="number" min={1} max={20} value={rows[id].length}
                onChange={(e) => set(id, { length: e.target.value })} />
            </label>
            <label>
              {t("unknown.road")}
              <select value={rows[id].road} onChange={(e) => set(id, { road: e.target.value })}>
                <option value="0">{t("unknown.road0")}</option>
                <option value="1">{t("unknown.road1")}</option>
                <option value="2">{t("unknown.road2")}</option>
              </select>
            </label>
          </div>
        );
      })}
      {invalid && <p className="field-error">{t("unknown.invalid")}</p>}
      <button type="submit" className="btn primary">
        {t("unknown.submit")}
      </button>
    </form>
  );
}
