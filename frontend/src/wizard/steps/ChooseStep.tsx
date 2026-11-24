import { StepNav } from "../StepNav";
import { useT, useWizardStore } from "../wizardStore";

export function ChooseStep() {
  const t = useT();
  const go = useWizardStore((s) => s.go);
  return (
    <section className="step-body">
      <h2>{t("step.choose")}</h2>
      <StepNav
        canBack={true}
        canNext={true}
        onBack={() => go(3)}
        onNext={() => go(5)}
      />
    </section>
  );
}
