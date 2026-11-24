// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as api from "../api";
import { useCityStore } from "../stores/cityStore";
import { runKey } from "./run";
import {
  parseSession, restoreSession, SESSION_VERSION, startDesktopSession, toSession, type Session,
} from "./session";
import type { LayoutEntry } from "./types";
import { useWizardStore } from "./wizardStore";

const edits = { remove: [3], add: [], relink: {} };
const layout = (id: number, roads: number) =>
  ({
    id, k: 1, achieved: 1, stats: { roads } as any, legality: { status: "ok" }, roads: [], buildings: {},
  }) as LayoutEntry;
const city = (id: string) =>
  ({ city_id: id, buildings: [], checks: { unconnected: [7], loose_chain_pieces: [] } }) as any;

const session = (over: Partial<Session> = {}): Session => ({
  version: 1,
  cityId: "c1",
  fileName: "mine.json",
  step: 4,
  edits,
  keepUnconnected: [7],
  layouts: [layout(1, 90), layout(2, 95)],
  selectedId: 2,
  runKey: runKey("c1", edits, [7]),
  ...over,
});

beforeEach(() => {
  useWizardStore.getState().reset();
  useWizardStore.getState().setLang("en");
});
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("parseSession", () => {
  it("accepts a valid session of a stored city", () => {
    expect(SESSION_VERSION).toBe(1);
    expect(parseSession(session(), ["c1"])).toEqual(session());
  });

  it.each([
    ["a wrong version", { ...session(), version: 2 }],
    ["junk", "junk"],
    ["null", null],
    ["a bad step", { ...session(), step: 9 }],
    ["bad layouts", { ...session(), layouts: "x" }],
    ["a bad selection", { ...session(), selectedId: "x" }],
  ])("rejects %s", (_n, raw) => {
    expect(parseSession(raw, ["c1"])).toBeNull();
  });

  it("rejects a city that is no longer stored", () => {
    expect(parseSession(session(), ["other"])).toBeNull();
  });
});

describe("toSession", () => {
  it("is null without a city", () => {
    expect(toSession()).toBeNull();
  });

  it("round-trips through JSON", () => {
    useCityStore.getState().setCity(city("c1"));
    useCityStore.getState().setEdits(edits);
    useWizardStore.setState({
      fileName: "mine.json",
      step: 4,
      keepUnconnected: [7],
      layouts: [layout(1, 90), layout(2, 95)],
      selectedId: 2,
      run: { key: runKey("c1", edits, [7]) } as any,
    });
    const s = toSession()!;
    expect(s).toEqual(session());
    expect(parseSession(JSON.parse(JSON.stringify(s)), ["c1"])).toEqual(s);
  });
});

describe("restoreSession", () => {
  const mockApi = () => {
    vi.spyOn(api, "apiCity").mockResolvedValue({ id: "c1", payload: { p: 1 } });
    return vi.spyOn(api, "apiLoadResult").mockResolvedValue({ ok: true, resp: city("c1") });
  };

  it("reloads the city and lands on the saved step and selection", async () => {
    const load = mockApi();
    expect(await restoreSession(session(), "fr")).toBe(true);
    expect(load).toHaveBeenCalledWith({ p: 1 }, { fileName: "mine.json", lang: "fr" });
    const w = useWizardStore.getState();
    expect(w.step).toBe(4);
    expect(w.selectedId).toBe(2);
    expect(w.layouts.map((l) => l.id)).toEqual([1, 2]);
    expect(w.keepUnconnected).toEqual([7]);
    expect(w.fileName).toBe("mine.json");
    expect(w.run?.state).toBe("done");
    expect(useCityStore.getState().edits).toEqual(edits);
  });

  it("goes back to step 3 when there are no layouts", async () => {
    mockApi();
    expect(await restoreSession(session({ layouts: [], selectedId: null }), "en")).toBe(true);
    expect(useWizardStore.getState().step).toBe(3);
    expect(useWizardStore.getState().run).toBeNull();
  });

  it("makes the restored results current", async () => {
    mockApi();
    await restoreSession(session(), "en");
    expect(useWizardStore.getState().resultsAreCurrent()).toBe(true);
  });

  it("fails cleanly when the city cannot be reloaded", async () => {
    vi.spyOn(api, "apiCity").mockRejectedValue(new Error("gone"));
    expect(await restoreSession(session(), "en")).toBe(false);
    expect(useCityStore.getState().city).toBeNull();
    expect(useWizardStore.getState().step).toBe(1);
  });
});

describe("startDesktopSession", () => {
  const respond = (status: number, body: string, type = "application/json") =>
    new Response(status === 204 ? null : body, { status, headers: { "Content-Type": type } });

  it("developer setup (HTML 404): no ping, no resume offer", async () => {
    const fetchMock = vi.fn().mockResolvedValue(respond(404, "<html>Not Found</html>", "text/html"));
    vi.stubGlobal("fetch", fetchMock);
    const stop = startDesktopSession();
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalled());
    await new Promise((r) => setTimeout(r, 0));
    stop();
    expect(fetchMock.mock.calls.map((c) => c[0])).toEqual(["/api/session"]);
    expect(useWizardStore.getState().resume).toBeNull();
  });

  it("network error: skips silently", async () => {
    const fetchMock = vi.fn().mockRejectedValue(new TypeError("offline"));
    vi.stubGlobal("fetch", fetchMock);
    const stop = startDesktopSession();
    await new Promise((r) => setTimeout(r, 0));
    stop();
    expect(fetchMock.mock.calls.map((c) => c[0])).toEqual(["/api/session"]);
  });

  it("desktop without a session: pings, no offer", async () => {
    const fetchMock = vi.fn().mockImplementation(async (url: string) =>
      url === "/api/session" ? respond(404, '{"error": "no session"}') : respond(204, ""));
    vi.stubGlobal("fetch", fetchMock);
    const stop = startDesktopSession();
    await vi.waitFor(() =>
      expect(fetchMock.mock.calls.map((c) => c[0])).toContain("/api/ping"));
    stop();
    expect(useWizardStore.getState().resume).toBeNull();
  });

  it("desktop with a session of a stored city: offers to continue", async () => {
    const fetchMock = vi.fn().mockImplementation(async (url: string) => {
      if (url === "/api/session") return respond(200, JSON.stringify(session()));
      if (url === "/api/cities") return respond(200, JSON.stringify([{ id: "c1" }]));
      return respond(204, "");
    });
    vi.stubGlobal("fetch", fetchMock);
    const stop = startDesktopSession();
    await vi.waitFor(() => expect(useWizardStore.getState().resume).toEqual(session()));
    stop();
  });

  it("desktop with a session of a city that is gone: no offer", async () => {
    const fetchMock = vi.fn().mockImplementation(async (url: string) => {
      if (url === "/api/session") return respond(200, JSON.stringify(session()));
      if (url === "/api/cities") return respond(200, "[]");
      return respond(204, "");
    });
    vi.stubGlobal("fetch", fetchMock);
    const stop = startDesktopSession();
    await vi.waitFor(() =>
      expect(fetchMock.mock.calls.map((c) => c[0])).toContain("/api/cities"));
    await new Promise((r) => setTimeout(r, 0));
    stop();
    expect(useWizardStore.getState().resume).toBeNull();
  });

  it("saves the session one second after a change, in desktop mode", async () => {
    const fetchMock = vi.fn().mockImplementation(async (url: string) =>
      url === "/api/session" ? respond(404, '{"error": "no session"}') : respond(204, ""));
    vi.stubGlobal("fetch", fetchMock);
    const stop = startDesktopSession();
    await vi.waitFor(() =>
      expect(fetchMock.mock.calls.map((c) => c[0])).toContain("/api/ping"));
    vi.useFakeTimers();
    useWizardStore.getState().go(2); // no city yet: nothing to save
    await vi.advanceTimersByTimeAsync(1500);
    const puts = () => fetchMock.mock.calls.filter((c) => c[1]?.method === "PUT");
    expect(puts()).toHaveLength(0);
    useCityStore.getState().setCity(city("c1"));
    await vi.advanceTimersByTimeAsync(900);
    expect(puts()).toHaveLength(0);
    await vi.advanceTimersByTimeAsync(200);
    expect(puts()).toHaveLength(1);
    expect(puts()[0][0]).toBe("/api/session");
    expect(JSON.parse(puts()[0][1].body).cityId).toBe("c1");
    stop();
  });
});
