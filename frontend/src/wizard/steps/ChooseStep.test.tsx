// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useCityStore } from "../../stores/cityStore";
import type { LayoutEntry } from "../types";
import { useWizardStore } from "../wizardStore";
import { ChooseStep } from "./ChooseStep";

vi.mock("../../components/CityMap", () => ({ CityMap: () => null }));

const stats = (roads: number) => ({
  area: 100, roads, road_efficiency_pct: 100, buildings_pct: 60, roads_pct: 10,
  free_pct: 5, free_cells: 5, with_roads: 1, without_roads: 1, unconnected: [],
});
const mk = (id: number, roads: number): LayoutEntry => ({
  id, k: 1, achieved: roads, stats: stats(roads), legality: { status: "ok" }, roads: [], buildings: {},
});

beforeEach(() => {
  useWizardStore.getState().reset();
  useWizardStore.getState().setLang("en");
  useCityStore.setState({ city: { city_id: "c1", stats: stats(92), map_view: { origin: [0, 0], cell: 1, palette: {} } } as any });
  useWizardStore.getState().addLayouts([mk(1, 68), mk(2, 66), mk(3, 67)]);
  useWizardStore.getState().select(2);
});
afterEach(cleanup);

describe("ChooseStep", () => {
  it("orders the cards best first with the player's city last", () => {
    render(<ChooseStep />);
    const cards = screen.getAllByRole("option").map((c) => c.textContent);
    expect(cards).toEqual(["66 roads (best)", "67 roads", "68 roads", "Your city: 92"]);
  });

  it("selects a card on click, and keeps it when new layouts stream in", () => {
    render(<ChooseStep />);
    fireEvent.click(screen.getByText("67 roads"));
    expect(useWizardStore.getState().selectedId).toBe(3);
    act(() => useWizardStore.getState().addLayouts([mk(4, 65)]));
    expect(useWizardStore.getState().selectedId).toBe(3);
    expect(screen.getByText("67 roads").getAttribute("aria-selected")).toBe("true");
    expect(screen.getByText("65 roads (best)")).toBeTruthy();
  });

  it("disables Next on the player's card", () => {
    render(<ChooseStep />);
    expect((screen.getByText("Next") as HTMLButtonElement).disabled).toBe(false);
    fireEvent.click(screen.getByText("Your city: 92"));
    expect((screen.getByText("Next") as HTMLButtonElement).disabled).toBe(true);
  });

  it("names added buildings with the translated suffix on the map", () => {
    useWizardStore.getState().setLang("fr");
    const added = [{
      entity_id: 99, cityentity_id: "HOUSE", name: "Maison", width: 2, length: 2,
      needs_road: true, road_level: 1, chain_id: null, link_to: null, placed: true, x: 0, y: 0,
    }];
    act(() => useWizardStore.getState().addLayouts([{
      ...mk(5, 60), buildings: { "99": [0, 0, 2, 2] }, added,
    } as LayoutEntry]));
    useWizardStore.getState().select(5);
    render(<ChooseStep />);
    const b = useCityStore.getState().optimized?.buildings.find((x: any) => String(x.id) === "99");
    expect(b?.name).toBe("Maison (nouveau)");
  });
});
