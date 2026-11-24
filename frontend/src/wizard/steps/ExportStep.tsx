import { StepNav } from "../StepNav";
import { useT, useWizardStore } from "../wizardStore";

export function ExportStep() {
  const t = useT();
  const go = useWizardStore((s) => s.go);
  return (
    <section className="step-body">
      <h2>{t("step.export")}</h2>
      <StepNav
        canBack={true}
        canNext={false}
        onBack={() => go(4)}
        onNext={() => go(5)}
      />
    </section>
  );
}
