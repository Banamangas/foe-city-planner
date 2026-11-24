// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useWizardStore } from "../wizardStore";
import { useCityStore } from "../../stores/cityStore";
import { LoadStep, ProblemView } from "./LoadStep";
import * as api from "../../api";
import { UnknownBuildingsForm } from "./UnknownBuildingsForm";
import type { Session } from "../session";

beforeEach(() => useWizardStore.getState().setLang("en"));
afterEach(cleanup);

describe("UnknownBuildingsForm", () => {
  it("collects a size and road need per building", () => {
    const onSubmit = vi.fn();
    render(
      <UnknownBuildingsForm
        items={[{ cityentity_id: "W_X", count: 2 }, { cityentity_id: "W_Y", count: 1 }]}
        onSubmit={onSubmit}
      />,
    );
    expect(screen.getAllByTestId("unknown-row")).toHaveLength(2);
    const w = screen.getAllByLabelText("Width");
    const l = screen.getAllByLabelText("Length");
    const r = screen.getAllByLabelText("Road need");
    fireEvent.change(w[0], { target: { value: "3" } });
    fireEvent.change(l[0], { target: { value: "2" } });
    fireEvent.change(r[0], { target: { value: "2" } });
    fireEvent.change(w[1], { target: { value: "1" } });
    fireEvent.change(l[1], { target: { value: "1" } });
    fireEvent.change(r[1], { target: { value: "0" } });
    fireEvent.click(screen.getByText("Continue"));
    expect(onSubmit).toHaveBeenCalledWith({
      W_X: { width: 3, length: 2, road: 2 },
      W_Y: { width: 1, length: 1, road: 0 },
    });
  });

  it("refuses invalid sizes", () => {
    const onSubmit = vi.fn();
    render(<UnknownBuildingsForm items={[{ cityentity_id: "W_X", count: 1 }]} onSubmit={onSubmit} />);
    fireEvent.change(screen.getByLabelText("Width"), { target: { value: "0" } });
    fireEvent.click(screen.getByText("Continue"));
    expect(onSubmit).not.toHaveBeenCalled();
  });
});

describe("ProblemView", () => {
  it("never renders the raw error text of an unreadable file", () => {
    const { container } = render(
      <ProblemView
        problem={{ kind: "unreadable", details: "Traceback KeyError" }}
        onSubmitCustom={() => {}}
        onGuide={() => {}}
      />,
    );
    expect(container.textContent).not.toContain("Traceback KeyError");
    expect(screen.getByText("Copy details for a bug report")).toBeTruthy();
  });
});

describe("LoadStep orchestration", () => {
  class FakeWorker {
    onmessage: ((e: any) => void) | null = null;
    onerror: (() => void) | null = null;
    terminated = false;
    postMessage(f: File) {
      queueMicrotask(() => !this.terminated && this.onmessage?.({ data: { phase: "done", slim: { n: f.name } } }));
    }
    terminate() { this.terminated = true; }
  }
  const city = (id: string, extra: any = {}) =>
    ({ city_id: id, buildings: [{ entity_id: 1, name: "Mill" }], ...extra }) as any;
  const pick = (name: string) => {
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    Object.defineProperty(input, "files", { value: [new File(["x"], name)], configurable: true });
    fireEvent.change(input);
  };
  const deferred = () => {
    let resolve!: (v: any) => void;
    const promise = new Promise<any>((r) => (resolve = r));
    return { promise, resolve };
  };

  beforeEach(() => {
    vi.stubGlobal("Worker", FakeWorker);
    useWizardStore.getState().reset();
    useWizardStore.getState().setLang("en");
  });
  afterEach(() => vi.restoreAllMocks());

  it.each([
    ["B then A", ["B", "A"]],
    ["A then B", ["A", "B"]],
  ])("keeps the newest file's city when results arrive %s", async (_n, order) => {
    const d: Record<string, ReturnType<typeof deferred>> = { A: deferred(), B: deferred() };
    vi.spyOn(api, "apiLoadResult").mockImplementation((slim: any) => d[slim.n[0]].promise);
    render(<LoadStep />);
    pick("A.city");
    await act(async () => {});
    pick("B.city");
    await act(async () => {});
    for (const k of order) await act(async () => d[k].resolve({ ok: true, resp: city(k) }));
    expect(useCityStore.getState().city?.city_id).toBe("B");
  });

  it("exportable:false leaves no city and Next disabled", async () => {
    vi.spyOn(api, "apiLoadResult").mockResolvedValue({ ok: true, resp: city("X", { exportable: false }) });
    render(<LoadStep />);
    pick("a.city");
    await screen.findByText(/export your city from Forge Hammer/i);
    expect(useCityStore.getState().city).toBeNull();
    expect((screen.getByText("Next") as HTMLButtonElement).disabled).toBe(true);
  });

  it("no unconnected buildings: keepUnconnected [] and Next enabled", async () => {
    vi.spyOn(api, "apiLoadResult").mockResolvedValue({
      ok: true,
      resp: city("X", { checks: { unconnected: [], loose_chain_pieces: [] } }),
    });
    render(<LoadStep />);
    pick("a.city");
    await waitFor(() => expect((screen.getByText("Next") as HTMLButtonElement).disabled).toBe(false));
    expect(useWizardStore.getState().keepUnconnected).toEqual([]);
  });

  it("unconnected buildings: Next waits for a choice", async () => {
    vi.spyOn(api, "apiLoadResult").mockResolvedValue({
      ok: true,
      resp: city("X", { checks: { unconnected: [1], loose_chain_pieces: [] } }),
    });
    render(<LoadStep />);
    pick("a.city");
    await screen.findByText("No, connect them (recommended)");
    expect((screen.getByText("Next") as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByText("Yes, leave them off the road"));
    expect((screen.getByText("Next") as HTMLButtonElement).disabled).toBe(false);
    expect(useWizardStore.getState().keepUnconnected).toEqual([1]);
  });

  it("loading another city drops the previous city's results", async () => {
    useWizardStore.setState({
      run: { key: "old" } as any, layouts: [{ id: 1, stats: { roads: 5 } } as any], selectedId: 1,
    });
    vi.spyOn(api, "apiLoadResult").mockResolvedValue({
      ok: true, resp: city("Y", { checks: { unconnected: [], loose_chain_pieces: [] } }),
    });
    render(<LoadStep />);
    pick("other.city");
    await waitFor(() => expect(useCityStore.getState().city?.city_id).toBe("Y"));
    expect(useWizardStore.getState().layouts).toEqual([]);
    expect(useWizardStore.getState().run).toBeNull();
    expect(useWizardStore.getState().selectedId).toBeNull();
  });
});

describe("LoadStep continue card", () => {
  const saved: Session = {
    version: 1, cityId: "c1", fileName: "mine.json", step: 3, edits: { remove: [], add: [], relink: {} },
    keepUnconnected: [], layouts: [], selectedId: null, runKey: null,
  };

  beforeEach(() => {
    useWizardStore.getState().reset();
    useWizardStore.getState().setLang("en");
  });
  afterEach(() => vi.restoreAllMocks());

  it("is not shown without a saved session", () => {
    render(<LoadStep />);
    expect(screen.queryByText("Continue where you left off")).toBeNull();
    expect(screen.getByText("Drop your city file here")).toBeTruthy();
  });

  it("continues the saved session", async () => {
    vi.spyOn(api, "apiCity").mockResolvedValue({ id: "c1", payload: { p: 1 } });
    vi.spyOn(api, "apiLoadResult").mockResolvedValue({
      ok: true, resp: { city_id: "c1", buildings: [], checks: { unconnected: [], loose_chain_pieces: [] } } as any,
    });
    useWizardStore.getState().setResume({ ...saved });
    render(<LoadStep />);
    expect(screen.getByText("Continue where you left off")).toBeTruthy();
    expect(screen.getByText(/mine\.json/)).toBeTruthy();
    expect(screen.queryByText("Drop your city file here")).toBeNull();
    fireEvent.click(screen.getByText("Continue"));
    await waitFor(() => expect(useWizardStore.getState().step).toBe(3));
    expect(useCityStore.getState().city?.city_id).toBe("c1");
    expect(useWizardStore.getState().resume).toBeNull();
  });

  it("starts over with another city", async () => {
    const del = vi.spyOn(api, "apiSessionDelete").mockResolvedValue();
    useWizardStore.getState().setResume({ ...saved });
    render(<LoadStep />);
    fireEvent.click(screen.getByText("Start with another city"));
    expect(del).toHaveBeenCalled();
    expect(await screen.findByText("Drop your city file here")).toBeTruthy();
    expect(useWizardStore.getState().resume).toBeNull();
  });

  it("falls back to the drop zone when the city can't be reopened", async () => {
    vi.spyOn(api, "apiCity").mockRejectedValue(new Error("gone"));
    vi.spyOn(api, "apiSessionDelete").mockResolvedValue();
    useWizardStore.getState().setResume({ ...saved });
    render(<LoadStep />);
    fireEvent.click(screen.getByText("Continue"));
    expect(await screen.findByText(/couldn't reopen your last city/)).toBeTruthy();
    expect(screen.getByText("Drop your city file here")).toBeTruthy();
  });

  it("remembers the loaded file's name", async () => {
    vi.stubGlobal("Worker", class {
      onmessage: ((e: any) => void) | null = null;
      postMessage() { queueMicrotask(() => this.onmessage?.({ data: { phase: "done", slim: {} } })); }
      terminate() {}
    });
    vi.spyOn(api, "apiLoadResult").mockResolvedValue({
      ok: true, resp: { city_id: "c9", buildings: [], checks: { unconnected: [], loose_chain_pieces: [] } } as any,
    });
    render(<LoadStep />);
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    Object.defineProperty(input, "files", { value: [new File(["x"], "town.json")], configurable: true });
    fireEvent.change(input);
    await waitFor(() => expect(useCityStore.getState().city?.city_id).toBe("c9"));
    expect(useWizardStore.getState().fileName).toBe("town.json");
  });

  it("is hidden while a dropped file is being read", async () => {
    vi.stubGlobal("Worker", class {
      onmessage: ((e: any) => void) | null = null;
      postMessage() { queueMicrotask(() => this.onmessage?.({ data: { phase: "done", slim: {} } })); }
      terminate() {}
    });
    vi.spyOn(api, "apiLoadResult").mockReturnValue(new Promise(() => {}));
    render(<LoadStep />);
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    Object.defineProperty(input, "files", { value: [new File(["x"], "town.json")], configurable: true });
    fireEvent.change(input);
    await screen.findByText("Reading your city…");
    act(() => useWizardStore.getState().setResume({ ...saved }));
    expect(screen.queryByText("Continue where you left off")).toBeNull();
    expect(screen.getByText("Drop your city file here")).toBeTruthy();
  });

  it("is hidden once a city is loaded", () => {
    useCityStore.setState({ city: { city_id: "c2", buildings: [] } as any });
    useWizardStore.getState().setResume({ ...saved });
    render(<LoadStep />);
    expect(screen.queryByText("Continue where you left off")).toBeNull();
  });
});
