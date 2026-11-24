// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { PING_INTERVAL_MS, setRunningFlag, startPinging } from "./desktop";

const fireUnload = () => {
  const e = new Event("beforeunload", { cancelable: true });
  window.dispatchEvent(e);
  return e;
};

afterEach(() => {
  setRunningFlag(false, "", "");
  delete (window as any).pywebview;
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("setRunningFlag", () => {
  it("tells the desktop shell", () => {
    const set_running = vi.fn();
    (window as any).pywebview = { api: { set_running } };
    setRunningFlag(true, "T", "M");
    expect(set_running).toHaveBeenCalledWith(true, "T", "M");
  });

  it("works without the desktop shell", () => {
    expect(() => setRunningFlag(true, "T", "M")).not.toThrow();
  });

  it("asks before the page closes only while running", () => {
    setRunningFlag(true, "T", "M");
    expect(fireUnload().defaultPrevented).toBe(true);
    setRunningFlag(false, "T", "M");
    expect(fireUnload().defaultPrevented).toBe(false);
  });
});

describe("startPinging", () => {
  it("pings at once, every 30 s, and stops", () => {
    vi.useFakeTimers();
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);
    expect(PING_INTERVAL_MS).toBe(30_000);
    const stop = startPinging();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledWith("/api/ping", { method: "POST" });
    vi.advanceTimersByTime(30_000);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    stop();
    vi.advanceTimersByTime(90_000);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});
