import { useState } from "react";
import { useT, useWizardStore } from "./wizardStore";

function GuideStep({ kind, n }: { kind: string; n: number }) {
  const t = useT();
  const lang = useWizardStore((s) => s.lang);
  const [hidden, setHidden] = useState(false);
  return (
    <li className="guide-step">
      <p>{t(`guide.${kind}.${n}`)}</p>
      {!hidden && (
        <img src={`/guides/${lang}/${kind}-${n}.png`} alt="" onError={() => setHidden(true)} />
      )}
    </li>
  );
}

export function Guide({ kind, onClose }: { kind: "export" | "import"; onClose: () => void }) {
  const t = useT();
  return (
    <div className="guide-backdrop" role="dialog" aria-modal="true" aria-label={t(`guide.${kind}.title`)}>
      <div className="guide-modal">
        <h3>{t(`guide.${kind}.title`)}</h3>
        <ol className="guide-steps">
          {[1, 2, 3].map((n) => (
            <GuideStep key={n} kind={kind} n={n} />
          ))}
        </ol>
        <button type="button" className="btn" onClick={onClose}>
          {t("guide.close")}
        </button>
      </div>
    </div>
  );
}
