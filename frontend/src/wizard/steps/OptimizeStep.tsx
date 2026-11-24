import { StepNav } from "../StepNav";
import { useT, useWizardStore } from "../wizardStore";

export function OptimizeStep() {
  const t = useT();
  const go = useWizardStore((s) => s.go);
  return (
    <section className="step-body">
      <h2>{t("step.optimize")}</h2>
      <StepNav
        canBack={true}
        canNext={true}
        onBack={() => go(2)}
        onNext={() => go(4)}
      />
    </section>
  );
}
