// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as api from "../../api";
import { useCityStore } from "../../stores/cityStore";
import { useWizardStore } from "../wizardStore";
import { OptimizeStep } from "./OptimizeStep";

type Handlers = Parameters<typeof api.openStream>[1];
let handlers: Handlers;
const close = vi.fn();

beforeEach(() => {
  useWizardStore.getState().reset();
  useWizardStore.getState().setLang("en");
  useCityStore.setState({ city: { city_id: "c1", stats: { roads: 120 } } as any });
  vi.spyOn(api, "apiOptions").mockResolvedValue({
    options: [], groups: {}, presets: { best: { patterns: 1 } },
    machine: { workers: 2, probe_workers: 1, threads: 4, logical_cpus: 8, reduced: true, warn: false },
  });
  vi.spyOn(api, "openStream").mockImplementation((_id, h) => {
    handlers = h;
    return { close } as unknown as EventSource;
  });
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); close.mockClear(); });

describe("OptimizeStep", () => {
  it("shows the machine line and reduced note", async () => {
    render(<OptimizeStep />);
    expect(await screen.findByText(/using 4/)).toBeTruthy();
    expect(screen.getByText(/a little worse/)).toBeTruthy();
  });

  it("maps an overflow refusal to the translated message with Back enabled", async () => {
    vi.spyOn(api, "apiOptimizeResult").mockResolvedValue({
      ok: false, status: 400, body: { error: "py", space: { fits_without_roads: false, overflow: 6 } },
    });
    render(<OptimizeStep />);
    await waitFor(() => expect((screen.getByText("Start") as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(screen.getByText("Start"));
    expect(await screen.findByText("The added buildings don't fit: 6 squares too many.")).toBeTruthy();
    expect((screen.getByText("Back") as HTMLButtonElement).disabled).toBe(false);
  });

  it("stops an old job on 409 and retries once", async () => {
    const opt = vi.spyOn(api, "apiOptimizeResult")
      .mockResolvedValueOnce({ ok: false, status: 409, body: { active_job_id: "old" } })
      .mockResolvedValueOnce({ ok: true, job_id: "new" });
    const stop = vi.spyOn(api, "apiStop").mockResolvedValue({ ok: true, already_done: true });
    render(<OptimizeStep />);
    await waitFor(() => expect((screen.getByText("Start") as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(screen.getByText("Start"));
    await waitFor(() => expect(api.openStream).toHaveBeenCalledWith("new", expect.anything()));
    expect(stop).toHaveBeenCalledWith("old");
    expect(opt).toHaveBeenCalledTimes(2);
  });

  it("runs, disables Back, shows numbers, and reports none_found", async () => {
    vi.spyOn(api, "apiOptimizeResult").mockResolvedValue({ ok: true, job_id: "j" });
    render(<OptimizeStep />);
    await waitFor(() => expect((screen.getByText("Start") as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(screen.getByText("Start"));
    await screen.findByRole("progressbar");
    expect((screen.getByText("Back") as HTMLButtonElement).disabled).toBe(true);
    act(() => handlers.onHeartbeat!({ state: "running", elapsed: 150, phase: "walk", layouts_found: 3 }));
    expect(screen.getByTestId("time-left").textContent).toBe("2:30");
    expect(screen.getByTestId("layouts-found").textContent).toBe("3");
    expect(screen.getByTestId("roads-before").textContent).toBe("120");
    act(() => handlers.onDone!({ state: "done", result: { layouts: [] }, error: null, elapsed: 200, stopped: false }));
    expect(await screen.findByText(/No layout was found this time/)).toBeTruthy();
    expect((screen.getByText("Back") as HTMLButtonElement).disabled).toBe(false);
  });

  it("goes to Choose with the best layout and closes the stream on unmount", async () => {
    vi.spyOn(api, "apiOptimizeResult").mockResolvedValue({ ok: true, job_id: "j" });
    const { unmount } = render(<OptimizeStep />);
    await waitFor(() => expect((screen.getByText("Start") as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(screen.getByText("Start"));
    await screen.findByRole("progressbar");
    act(() => handlers.onLayout!({ id: 2, stats: { roads: 70 } } as any));
    act(() => handlers.onDone!({
      state: "done", result: { layouts: [{ id: 5, stats: { roads: 66 } }] }, elapsed: 10, stopped: true,
    }));
    expect(useWizardStore.getState().step).toBe(4);
    expect(useWizardStore.getState().selectedId).toBe(5);
    unmount();
  });

  it("closes the stream when unmounted mid-run", async () => {
    vi.spyOn(api, "apiOptimizeResult").mockResolvedValue({ ok: true, job_id: "j" });
    const { unmount } = render(<OptimizeStep />);
    await waitFor(() => expect((screen.getByText("Start") as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(screen.getByText("Start"));
    await screen.findByRole("progressbar");
    unmount();
    expect(close).toHaveBeenCalled();
  });

  it("a second run does not inherit the first run's layouts", async () => {
    vi.spyOn(api, "apiOptimizeResult").mockResolvedValue({ ok: true, job_id: "j" });
    render(<OptimizeStep />);
    await waitFor(() => expect((screen.getByText("Start") as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(screen.getByText("Start"));
    await screen.findByRole("progressbar");
    act(() => handlers.onDone!({ state: "done", result: { layouts: [{ id: 0, stats: { roads: 66 } }] }, elapsed: 1 }));
    useWizardStore.getState().go(3);
    await waitFor(() => expect((screen.getByText("Start") as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(screen.getByText("Start"));
    await screen.findByRole("progressbar");
    expect(useWizardStore.getState().layouts).toEqual([]);
    act(() => handlers.onDone!({ state: "done", result: { layouts: [] }, elapsed: 1 }));
    expect(await screen.findByText(/No layout was found this time/)).toBeTruthy();
    expect(useWizardStore.getState().layouts).toEqual([]);
  });

  it("treats a permanently closed stream as a lost run", async () => {
    vi.spyOn(api, "apiOptimizeResult").mockResolvedValue({ ok: true, job_id: "j" });
    render(<OptimizeStep />);
    await waitFor(() => expect((screen.getByText("Start") as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(screen.getByText("Start"));
    await screen.findByRole("progressbar");
    act(() => handlers.onError!({ readyState: 0 } as EventSource));
    expect(screen.queryByText(/connection to the optimizer/)).toBeNull();
    act(() => handlers.onError!({ readyState: 2 } as EventSource));
    expect(await screen.findByText("The connection to the optimizer was lost.")).toBeTruthy();
    expect(close).toHaveBeenCalled();
    expect((screen.getByText("Back") as HTMLButtonElement).disabled).toBe(false);
  });

  it("treats 20 s of silence as a lost run", async () => {
    vi.spyOn(api, "apiOptimizeResult").mockResolvedValue({ ok: true, job_id: "j" });
    render(<OptimizeStep />);
    await waitFor(() => expect((screen.getByText("Start") as HTMLButtonElement).disabled).toBe(false));
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval", "Date"] });
    try {
      fireEvent.click(screen.getByText("Start"));
      await act(async () => { await Promise.resolve(); await Promise.resolve(); });
      expect(screen.getByRole("progressbar")).toBeTruthy();
      act(() => { vi.advanceTimersByTime(15_000); });
      act(() => handlers.onHeartbeat!({ elapsed: 15, phase: "walk", layouts_found: 0 }));
      act(() => { vi.advanceTimersByTime(15_000); });
      expect(screen.queryByText(/connection to the optimizer/)).toBeNull();
      act(() => { vi.advanceTimersByTime(7_000); });
      expect(screen.getByText("The connection to the optimizer was lost.")).toBeTruthy();
    } finally {
      vi.useRealTimers();
    }
  });

  it("disables Stop once pressed", async () => {
    vi.spyOn(api, "apiOptimizeResult").mockResolvedValue({ ok: true, job_id: "j" });
    vi.spyOn(api, "apiStop").mockResolvedValue({ ok: true });
    render(<OptimizeStep />);
    await waitFor(() => expect((screen.getByText("Start") as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(screen.getByText("Start"));
    await screen.findByRole("progressbar");
    fireEvent.click(screen.getByText("Stop now and keep what's found"));
    const b = screen.getByText("Stopping…") as HTMLButtonElement;
    expect(b.disabled).toBe(true);
  });

  it("keeps the results when nothing changed, drops them when the edits changed", async () => {
    vi.spyOn(api, "apiOptimizeResult").mockResolvedValue({ ok: true, job_id: "j" });
    const { unmount } = render(<OptimizeStep />);
    await waitFor(() => expect((screen.getByText("Start") as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(screen.getByText("Start"));
    await screen.findByRole("progressbar");
    act(() => handlers.onDone!({ state: "done", result: { layouts: [{ id: 0, stats: { roads: 66 } }] }, elapsed: 1 }));
    unmount();
    // Back and Next again without a change: the results stay reachable.
    useWizardStore.getState().go(3);
    const again = render(<OptimizeStep />);
    expect(useWizardStore.getState().resultsAreCurrent()).toBe(true);
    expect((screen.getByText("Next") as HTMLButtonElement).disabled).toBe(false);
    again.unmount();
    // A building removed in step 2: the old layouts are gone and Next is off.
    act(() => useCityStore.getState().setEdits({ remove: [7], add: [], relink: {} }));
    expect(useWizardStore.getState().resultsAreCurrent()).toBe(false);
    render(<OptimizeStep />);
    await waitFor(() => expect(useWizardStore.getState().layouts).toEqual([]));
    expect(useWizardStore.getState().run).toBeNull();
    expect(useWizardStore.getState().selectedId).toBeNull();
    expect((screen.getByText("Next") as HTMLButtonElement).disabled).toBe(true);
  });

  it("drops the results when the keep-unconnected choice changed", async () => {
    vi.spyOn(api, "apiOptimizeResult").mockResolvedValue({ ok: true, job_id: "j" });
    const { unmount } = render(<OptimizeStep />);
    await waitFor(() => expect((screen.getByText("Start") as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(screen.getByText("Start"));
    await screen.findByRole("progressbar");
    act(() => handlers.onDone!({ state: "done", result: { layouts: [{ id: 0, stats: { roads: 66 } }] }, elapsed: 1 }));
    unmount();
    useWizardStore.getState().setKeepUnconnected([4]);
    useWizardStore.getState().go(3);
    render(<OptimizeStep />);
    await waitFor(() => expect(useWizardStore.getState().layouts).toEqual([]));
    expect((screen.getByText("Next") as HTMLButtonElement).disabled).toBe(true);
  });

  it("flags a running search to the desktop shell, and clears it on unmount", async () => {
    const set_running = vi.fn();
    (window as any).pywebview = { api: { set_running } };
    try {
      vi.spyOn(api, "apiOptimizeResult").mockResolvedValue({ ok: true, job_id: "j" });
      const { unmount } = render(<OptimizeStep />);
      await waitFor(() => expect((screen.getByText("Start") as HTMLButtonElement).disabled).toBe(false));
      expect(set_running).toHaveBeenLastCalledWith(false, expect.any(String), expect.any(String));
      fireEvent.click(screen.getByText("Start"));
      await screen.findByRole("progressbar");
      expect(set_running).toHaveBeenLastCalledWith(
        true,
        "A search is running",
        "Closing now stops the search and loses what it found since the last saved step. Close anyway?",
      );
      unmount();
      expect(set_running.mock.lastCall?.[0]).toBe(false);
    } finally {
      delete (window as any).pywebview;
    }
  });
});
