import { useT } from "./wizardStore";

type Props = {
  canBack: boolean;
  canNext: boolean;
  onBack: () => void;
  onNext: () => void;
  nextLabel?: string;
};

export function StepNav({ canBack, canNext, onBack, onNext, nextLabel }: Props) {
  const t = useT();
  return (
    <div className="step-nav">
      <button type="button" className="btn" disabled={!canBack} onClick={onBack}>
        {t("nav.back")}
      </button>
      <button type="button" className="btn primary" disabled={!canNext} onClick={onNext}>
        {nextLabel ?? t("nav.next")}
      </button>
    </div>
  );
}
