import { Sidebar } from "./components/Sidebar";
import { CityMap } from "./components/CityMap";
import { useCityStore } from "./stores/cityStore";

export function App() {
  const city = useCityStore((s) => s.city);
  return (
    <div className="app">
      <Sidebar />
      <main className="main">
        {city ? <CityMap /> : <div className="empty">Load a city to begin.</div>}
      </main>
    </div>
  );
}
