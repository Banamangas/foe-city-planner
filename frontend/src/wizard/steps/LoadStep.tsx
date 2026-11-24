import { StepNav } from "../StepNav";
import { useT, useWizardStore } from "../wizardStore";

export function LoadStep() {
  const t = useT();
  const go = useWizardStore((s) => s.go);
  return (
    <section className="step-body">
      <h2>{t("step.load")}</h2>
      <StepNav
        canBack={false}
        canNext={true}
        onBack={() => go(1)}
        onNext={() => go(2)}
      />
    </section>
  );
}
