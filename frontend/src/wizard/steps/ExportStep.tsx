import { useState } from "react";
import { apiExportV3 } from "../../api";
import { useCityStore } from "../../stores/cityStore";
import { Guide } from "../Guide";
import { StepNav } from "../StepNav";
import { layoutForExport } from "../stats";
import { useT, useWizardStore } from "../wizardStore";

function download(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function ExportStep() {
  const t = useT();
  const go = useWizardStore((s) => s.go);
  const reset = useWizardStore((s) => s.reset);
  const layouts = useWizardStore((s) => s.layouts);
  const selectedId = useWizardStore((s) => s.selectedId);
  const cityId = useCityStore((s) => s.city?.city_id);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  const [warnings, setWarnings] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [guide, setGuide] = useState(false);

  const entry = typeof selectedId === "number" ? layouts.find((l) => l.id === selectedId) ?? null : null;

  const save = async () => {
    if (!cityId || !entry || busy) return;
    setBusy(true);
    setError(null);
    setCopied(false);
    setSaved(false);
    setWarnings(0);
    try {
      const r = await apiExportV3(cityId, layoutForExport(entry));
      download(r.blob, r.filename);
      // export.warnings counts every warning as "added by size only", the only kind the export
      // emits today; a new warning kind needs its own message.
      setWarnings(r.warnings.length);
      setSaved(true);
    } catch (err) {
      setError(String(err instanceof Error ? err.message : err));
    } finally {
      setBusy(false);
    }
  };

  const copy = async () => {
    try {
      await navigator.clipboard?.writeText(error ?? "");
      setCopied(true);
    } catch {
      /* clipboard blocked: nothing to confirm */
    }
  };

  return (
    <section className="step-body">
      <h2>{t("step.export")}</h2>
      <p>{t("export.intro")}</p>
      <button type="button" className="btn primary" disabled={!cityId || !entry || busy} onClick={save}>
        {t("export.save")}
      </button>
      {saved && <p className="copied">{t("export.saved")}</p>}
      {error !== null && (
        <div className="problem">
          <p className="field-error">{t("export.failed")}</p>
          <button type="button" className="btn" onClick={copy}>{t("error.copyDetails")}</button>
          {copied && <span className="copied"> {t("error.copied")}</span>}
        </div>
      )}
      {warnings > 0 && <p className="cascade-note">{t("export.warnings", { n: warnings })}</p>}
      <p>
        <button type="button" className="link" onClick={() => setGuide(true)}>{t("export.howImport")}</button>
      </p>
      <p>
        <button type="button" className="btn" onClick={reset}>{t("export.again")}</button>
      </p>
      {guide && <Guide kind="import" onClose={() => setGuide(false)} />}
      <StepNav canBack={true} canNext={false} onBack={() => go(4)} onNext={() => go(5)} />
    </section>
  );
}
