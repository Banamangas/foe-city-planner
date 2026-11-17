export type RoadView = { x: number; y: number; level: number };

export type BuildingView = {
  id?: number | string;
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
  cityentity_id?: string; chain_id?: string | null; is_chain_head?: boolean;
};

/** One addition: a catalog type (`cityentity_id`) or a custom size. */
export type AddSpec = {
  cityentity_id?: string; count: number; link_to?: number;
  width?: number; length?: number; needs_road?: boolean; name?: string;
  /** UI-only labels, ignored by the server. */
  label?: string; size?: string;
};

/** Plan E edit set, per city. `relink`: removed main id -> main its patches move to. */
export type Edits = { remove: number[]; add: AddSpec[]; relink?: Record<string, number> };

export type CatalogEntry = {
  id: string; name: string; type: string; width: number; length: number;
  needs_road: boolean; road_level: number; chain_id: string | null; is_chain_head: boolean;
};

export type StoredBuilding = {
  entity_id: number; cityentity_id: string; name: string; width: number; length: number;
  reason: string; main?: number;
};
export type AddedBuilding = {
  entity_id: number; cityentity_id: string; name: string; width: number; length: number;
  needs_road: boolean; road_level: number; chain_id: string | null; link_to: number | null;
  placed: boolean; x: number; y: number;
};

/** Server report of what an edit set does (foeopt.editing.apply_edits). */
export type EditReport = {
  removed: number[];
  to_store: StoredBuilding[];
  reattached: { removed: number; moved: number[]; to: number | null; to_name: string | null;
                ok: boolean; relinked?: boolean; offset?: [number, number] }[];
  cascades: { main: number; main_name: string; stored: number[];
              relink_candidates: { entity_id: number; name: string }[] }[];
  added: AddedBuilding[];
  warnings: string[];
  not_composable: { members: number[]; names: string[] }[];
  seed: { possible: boolean; reason: string | null };
  space: { region_cells: number; building_cells: number; free_cells: number;
           removed_cells: number; added_cells: number; upload_roads: number;
           fits_without_roads: boolean; fits_with_upload_roads: boolean; overflow: number };
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
  edits?: Edits | null;
};

export type Improvement = {
  k: number; achieved: number;
  roads: [number, number, number?][];   // [x, y, level]; level 2 = two-lane tile
  buildings: Record<string, [number, number, number, number]>;
  /** Present when the run had edits: buildings that leave the map / were added. */
  to_store?: StoredBuilding[];
  added?: AddedBuilding[];
  /** Stored with a saved layout: the edit set it was made for. */
  edits?: Edits;
};

export type CityListItem = {
  id: string; label: string; region_cells: number; road_estimate: number; created_at: string;
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

/** Why a run that found no layout found none, when the cause was filler packing.
 *
 * CP-SAT placed every road-needing building and the remaining "filler" buildings
 * then had nowhere to go. The greedy packer never exits early, so these are real
 * "placed N of M" counts rather than a bare rejection. */
export interface FillerFailures {
  failures: number;
  mean_placed: number;
  mean_total: number;
  worst_placed: number;
  top_unplaced: { name: string; times: number }[];
}
