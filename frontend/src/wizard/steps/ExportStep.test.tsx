// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as api from "../../api";
import { useCityStore } from "../../stores/cityStore";
import { layoutForExport } from "../stats";
import type { LayoutEntry } from "../types";
import * as session from "../session";
import { useWizardStore } from "../wizardStore";
import { ExportStep } from "./ExportStep";

const entry: LayoutEntry = {
  id: 1, k: 1, achieved: 66, legality: { status: "ok" }, roads: [], buildings: {},
  stats: { area: 1, roads: 66, road_efficiency_pct: null, buildings_pct: 1, roads_pct: 1, free_pct: 1, free_cells: 1, with_roads: 1, without_roads: 1, unconnected: [] },
};

beforeEach(() => {
  useWizardStore.getState().reset();
  useWizardStore.getState().setLang("en");
  useCityStore.setState({ city: { city_id: "c1" } as any });
  useWizardStore.getState().addLayouts([entry]);
  useWizardStore.getState().select(1);
  (URL as any).createObjectURL = vi.fn(() => "blob:x");
  (URL as any).revokeObjectURL = vi.fn();
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("ExportStep", () => {
  it("saves, shows the saved line and a translated warning count, never the raw text", async () => {
    const spy = vi.spyOn(api, "apiExportV3").mockResolvedValue({
      blob: new Blob(["x"]), filename: "a.json", warnings: ["RAW SERVER ONE", "RAW SERVER TWO"],
    });
    render(<ExportStep />);
    fireEvent.click(screen.getByText("Save file for Forge Hammer"));
    expect(await screen.findByText("File saved.")).toBeTruthy();
    expect(spy).toHaveBeenCalledWith("c1", layoutForExport(entry));
    expect(screen.getByText(/^2 added building/)).toBeTruthy();
    expect(document.body.textContent).not.toContain("RAW SERVER");
  });

  it("shows a generic message on failure, not the error text", async () => {
    vi.spyOn(api, "apiExportV3").mockRejectedValue(new Error("Traceback secret"));
    render(<ExportStep />);
    fireEvent.click(screen.getByText("Save file for Forge Hammer"));
    await waitFor(() => expect(screen.getByText("The file could not be created.")).toBeTruthy());
    expect(document.body.textContent).not.toContain("Traceback");
    expect(screen.getByText("Copy details for a bug report")).toBeTruthy();
  });

  it("Start again forgets the saved session", () => {
    const forget = vi.spyOn(session, "forgetSession").mockImplementation(() => {});
    render(<ExportStep />);
    fireEvent.click(screen.getByText("Start again with another city"));
    expect(forget).toHaveBeenCalled();
    expect(useWizardStore.getState().step).toBe(1);
  });
});
