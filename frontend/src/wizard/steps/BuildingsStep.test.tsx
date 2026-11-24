// @vitest-environment jsdom
import { cleanup, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useCityStore } from "../../stores/cityStore";
import { useWizardStore } from "../wizardStore";
import { BuildingsStep } from "./BuildingsStep";

vi.mock("../../components/CityMap", () => ({ CityMap: () => null }));

beforeEach(() => {
  useWizardStore.getState().reset();
  useWizardStore.getState().setLang("en");
});
afterEach(cleanup);

describe("BuildingsStep", () => {
  it("shows the current map, where clicks remove buildings, even after Choose showed a layout", () => {
    useCityStore.setState({ city: { city_id: "c1", buildings: [] } as any, viewMode: "optimized" });
    render(<BuildingsStep />);
    expect(useCityStore.getState().viewMode).toBe("current");
  });
});
