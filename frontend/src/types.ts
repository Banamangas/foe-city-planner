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

export type LoadResponse = {
  city_id: string;
  buildings: BuildingSummary[];
  region_cells: number;
  road_estimate: number;
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

export type LayoutListItem = {
  id: string; city_id: string; k: number; achieved: number;
  roads_count: number; created_at: string;
};
