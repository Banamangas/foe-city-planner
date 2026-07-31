export type RoadView = { x: number; y: number; level: number };

export type BuildingView = {
  x: number; y: number; w: number; h: number;
  name: string; size: string; needs_road: boolean; townhall: boolean;
};

export type Palette = {
  background: string; region: string;
  current_road: string; optimized_road: string;
  townhall: string; road_building: string; plain_building: string; border: string;
};

export type MapView = {
  cell: number;
  origin: [number, number];
  width: number; height: number;
  region: [number, number][];
  buildings: BuildingView[];
  current_roads: RoadView[];
  optimized_roads: RoadView[] | null;
  palette: Palette;
};

export type BuildingSummary = {
  entity_id: string | number; name: string;
  width: number; length: number; needs_road: boolean; is_townhall: boolean;
};

/** Instance screen from foeopt.bounds.screen_city — advisory, never blocking.
 *  `road_pressure` = roads the city needs / free cells it has. Measured: 0.40
 *  and 0.43 succeeded, 0.89 returned nothing in 135 probes. Note city *fill*
 *  does not discriminate (89.6% succeeded, 90.2% failed) — this ratio does. */
export type CityScreen = {
  verdict: "LIKELY" | "UNCERTAIN" | "UNLIKELY" | "INFEASIBLE";
  reason: string;
  road_pressure: number;
  consumers: number;
  slack: number;
  region_cells: number;
  building_area: number;
};

export type LoadResponse = {
  city_id: string;
  buildings: BuildingSummary[];
  region_cells: number;
  road_estimate: number;
  screen?: CityScreen;
  map_view: MapView;
};

export type Improvement = {
  k: number; achieved: number;
  roads: [number, number][];
  buildings: Record<string, [number, number, number, number]>;
};

export type CityListItem = {
  id: string; region_cells: number; road_estimate: number; created_at: string;
};

/** One run parameter, as declared by webapp/params.py and served by /api/options. */
export type OptionSpec = {
  name: string;
  cli: string;
  label: string;
  help: string;
  group: string;
  type: "int" | "float" | "bool" | "choice" | "int_or_auto" | "int_or_null";
  default: number | string | boolean | null;
  advanced?: boolean;
  min?: number;
  max?: number;
  choices?: string[];
};

export type OptionsResponse = {
  options: OptionSpec[];
  groups: Record<string, string>;
  presets: Record<string, Record<string, number | string | boolean | null>>;
};

/** Form state: text inputs stay strings until submit; the server coerces. */
export type OptionValues = Record<string, string | boolean>;

export type LayoutListItem = {
  id: string; city_id: string; k: number; achieved: number;
  roads_count: number; created_at: string;
};
