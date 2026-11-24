import { useEffect } from "react";
import { LANGS, languageName, translate } from "./i18n";
import { BuildingsStep } from "./steps/BuildingsStep";
import { ChooseStep } from "./steps/ChooseStep";
import { ExportStep } from "./steps/ExportStep";
import { LoadStep } from "./steps/LoadStep";
import { OptimizeStep } from "./steps/OptimizeStep";
import { useT, useWizardStore, type Step } from "./wizardStore";
import "./wizard.css";

const STEP_KEYS = ["load", "buildings", "optimize", "choose", "export"] as const;
const STEP_COMPONENTS = [LoadStep, BuildingsStep, OptimizeStep, ChooseStep, ExportStep];

export function Wizard() {
  const t = useT();
  const step = useWizardStore((s) => s.step);
  const lang = useWizardStore((s) => s.lang);
  const setLang = useWizardStore((s) => s.setLang);

  useEffect(() => {
    document.title = translate(lang, "app.title");
  }, [lang]);

  const Current = STEP_COMPONENTS[step - 1];
  return (
    <div className="wizard">
      <header className="wizard-header">
        <h1>{t("app.title")}</h1>
        <label className="lang-switch">
          <span>{t("lang.label")}</span>
          <select value={lang} onChange={(e) => setLang(e.target.value)} aria-label={t("lang.label")}>
            {LANGS.map((code) => (
              <option key={code} value={code}>
                {languageName(code)}
              </option>
            ))}
          </select>
        </label>
      </header>
      <ol className="step-bar">
        {STEP_KEYS.map((key, i) => {
          const n = (i + 1) as Step;
          const status = n < step ? "done" : n === step ? "current" : "upcoming";
          return (
            <li key={key} className={`step-item ${status}`} aria-current={n === step ? "step" : undefined}>
              <span className="step-num">{n}</span>
              <span className="step-label">{t(`step.${key}`)}</span>
            </li>
          );
        })}
      </ol>
      <main>
        <Current />
      </main>
    </div>
  );
}
