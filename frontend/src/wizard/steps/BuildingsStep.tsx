import { StepNav } from "../StepNav";
import { useT, useWizardStore } from "../wizardStore";

export function BuildingsStep() {
  const t = useT();
  const go = useWizardStore((s) => s.go);
  return (
    <section className="step-body">
      <h2>{t("step.buildings")}</h2>
      <StepNav
        canBack={true}
        canNext={true}
        onBack={() => go(1)}
        onNext={() => go(3)}
      />
    </section>
  );
}
