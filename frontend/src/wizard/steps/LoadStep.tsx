import { useRef, useState } from "react";
import { apiLoadResult } from "../../api";
import { useCityStore } from "../../stores/cityStore";
import { Guide } from "../Guide";
import { classifyLoadProblem, type CustomBuildings, type LoadProblem } from "../loadCity";
import { StepNav } from "../StepNav";
import { useT, useWizardStore } from "../wizardStore";
import { ChecksPanel } from "./ChecksPanel";
import { UnknownBuildingsForm } from "./UnknownBuildingsForm";

export function ProblemView({
  problem,
  onSubmitCustom,
  onGuide,
}: {
  problem: LoadProblem;
  onSubmitCustom: (c: CustomBuildings) => void;
  onGuide: () => void;
}) {
  const t = useT();
  const [copied, setCopied] = useState(false);
  const copy = async (details: string) => {
    try {
      await navigator.clipboard?.writeText(details);
      setCopied(true);
    } catch {
      /* clipboard blocked: nothing to confirm */
    }
  };
  const guideLink = (
    <button type="button" className="link" onClick={onGuide}>
      {t("load.guideLink")}
    </button>
  );
  switch (problem.kind) {
    case "unknown_buildings":
      return <UnknownBuildingsForm items={problem.items} onSubmit={onSubmitCustom} />;
    case "not_forge_hammer":
      return (
        <div className="problem">
          <p>{t("problem.notForgeHammer")}</p>
          {guideLink}
        </div>
      );
    case "app_not_running":
      return (
        <div className="problem">
          <p>{t("problem.appNotRunning")}</p>
        </div>
      );
    case "unreadable":
      return (
        <div className="problem">
          <p>{t("problem.unreadable")}</p>
          <button type="button" className="btn" onClick={() => copy(problem.details)}>
            {t("error.copyDetails")}
          </button>
          {copied && <span className="copied"> {t("error.copied")}</span>}
          <div>{guideLink}</div>
        </div>
      );
  }
}

export function LoadStep() {
  const t = useT();
  const lang = useWizardStore((s) => s.lang);
  const go = useWizardStore((s) => s.go);
  const keepUnconnected = useWizardStore((s) => s.keepUnconnected);
  const setKeepUnconnected = useWizardStore((s) => s.setKeepUnconnected);
  const city = useCityStore((s) => s.city);
  const setCity = useCityStore((s) => s.setCity);

  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<LoadProblem | null>(null);
  const [guide, setGuide] = useState(false);
  const slimRef = useRef<{ slim: unknown; name: string } | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const finish = (resp: NonNullable<typeof city>) => {
    setCity(resp);
    const unconnected = resp.checks?.unconnected ?? [];
    // Nothing to ask when everything is connected; otherwise wait for the player's choice.
    if (unconnected.length === 0) setKeepUnconnected([]);
    else useWizardStore.setState({ keepUnconnected: null });
  };

  const load = async (custom?: CustomBuildings) => {
    const src = slimRef.current;
    if (!src) return;
    setBusy(true);
    const r = await apiLoadResult(src.slim, { fileName: src.name, lang, custom });
    setBusy(false);
    const p = classifyLoadProblem(r.ok ? { resp: r.resp } : r);
    setProblem(p);
    if (r.ok && !p) finish(r.resp);
  };

  const onFile = (file: File) => {
    setProblem(null);
    setBusy(true);
    useCityStore.getState().reset();
    useWizardStore.setState({ keepUnconnected: null });
    const worker = new Worker(new URL("../../workers/stripCity.worker.ts", import.meta.url), {
      type: "module",
    });
    worker.onmessage = (e: MessageEvent<any>) => {
      const msg = e.data;
      if (msg.phase === "error") {
        worker.terminate();
        setBusy(false);
        setProblem({ kind: "unreadable", details: String(msg.message) });
      } else if (msg.phase === "done") {
        worker.terminate();
        slimRef.current = { slim: msg.slim, name: file.name };
        load();
      }
    };
    worker.onerror = () => {
      worker.terminate();
      setBusy(false);
      setProblem({ kind: "unreadable", details: "reader failed" });
    };
    worker.postMessage(file);
  };

  const checks = city?.checks;
  const hasUnconnected = (checks?.unconnected.length ?? 0) > 0;
  const chosen = keepUnconnected === null ? null : keepUnconnected.length > 0;
  const canNext = !!city && !busy && (!hasUnconnected || keepUnconnected !== null);

  return (
    <section className="step-body">
      <h2>{t("load.title")}</h2>
      <div
        className="drop-zone"
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => {
          e.preventDefault();
          const f = e.dataTransfer?.files?.[0];
          if (f) onFile(f);
        }}
      >
        <p>{t("load.drop")}</p>
        <button type="button" className="btn" onClick={() => inputRef.current?.click()}>
          {t("load.choose")}
        </button>
        <input ref={inputRef} type="file" hidden
          onChange={(e) => e.target.files?.[0] && onFile(e.target.files[0])} />
      </div>
      <p className="private-note">{t("load.private")}</p>
      <button type="button" className="link" onClick={() => setGuide(true)}>
        {t("load.guideLink")}
      </button>
      {busy && <p className="busy">{t("load.busy")}</p>}
      {problem && (
        <ProblemView problem={problem} onSubmitCustom={load} onGuide={() => setGuide(true)} />
      )}
      {city && !problem && !busy && (
        <>
          <p className="loaded">{t("load.loaded", { n: city.buildings.length })}</p>
          {checks && (
            <ChecksPanel
              checks={checks}
              chosen={chosen}
              onKeep={(keep) => setKeepUnconnected(keep ? checks.unconnected : [])}
            />
          )}
        </>
      )}
      {guide && <Guide kind="export" onClose={() => setGuide(false)} />}
      <StepNav canBack={false} canNext={canNext} onBack={() => {}} onNext={() => go(2)} />
    </section>
  );
}
