import { LoadPanel } from "./LoadPanel";
import { OptimizePanel } from "./OptimizePanel";
import { ResultPanel } from "./ResultPanel";
import { BuildingsPanel } from "./BuildingsPanel";

export function Sidebar() {
  return (
    <aside className="sidebar">
      <h2>FoE City Planner</h2>
      <LoadPanel />
      <OptimizePanel />
      <ResultPanel />
      <BuildingsPanel />
    </aside>
  );
}
