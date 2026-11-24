// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as api from "../../api";
import { useWizardStore } from "../wizardStore";
import { AddBuildingDialog } from "./AddBuildingDialog";

const deferred = () => {
  let resolve!: (v: any) => void;
  const promise = new Promise<any>((r) => (resolve = r));
  return { promise, resolve };
};

beforeEach(() => useWizardStore.getState().setLang("en"));
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("AddBuildingDialog", () => {
  it("shows Searching while pending, then a hint for an empty query with nothing listed", async () => {
    const d = deferred();
    vi.spyOn(api, "apiCatalog").mockReturnValue(d.promise);
    render(<AddBuildingDialog cityId="c1" onPick={() => {}} onClose={() => {}} />);
    expect(screen.getByText("Searching…")).toBeTruthy();
    d.resolve({ results: [] });
    expect(await screen.findByText("Type a building name to search.")).toBeTruthy();
    expect(screen.queryByText("Searching…")).toBeNull();
  });

  it("says no building was found for a query with no result", async () => {
    vi.spyOn(api, "apiCatalog").mockResolvedValue({ results: [] });
    render(<AddBuildingDialog cityId="c1" onPick={() => {}} onClose={() => {}} />);
    fireEvent.change(screen.getByLabelText("Search for a building"), { target: { value: "zzz" } });
    expect(await screen.findByText("No building found.", {}, { timeout: 2000 })).toBeTruthy();
  });

  it("closes on Escape", () => {
    vi.spyOn(api, "apiCatalog").mockResolvedValue({ results: [] });
    const onClose = vi.fn();
    render(<AddBuildingDialog cityId="c1" onPick={() => {}} onClose={onClose} />);
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).toHaveBeenCalled();
  });
});
