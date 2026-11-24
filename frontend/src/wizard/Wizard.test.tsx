// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { act } from "react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { translate } from "./i18n";
import { pickRoot } from "./route";
import { Wizard } from "./Wizard";
import { useWizardStore } from "./wizardStore";

beforeEach(() => {
  useWizardStore.getState().reset();
  useWizardStore.getState().setLang("en");
});
afterEach(cleanup);

describe("pickRoot", () => {
  it("routes /advanced and below to the old UI", () => {
    expect(pickRoot("/")).toBe("wizard");
    expect(pickRoot("/advanced")).toBe("advanced");
    expect(pickRoot("/advanced/x")).toBe("advanced");
    expect(pickRoot("/whatever")).toBe("wizard");
  });
});

describe("Wizard shell", () => {
  it("renders five translated steps", () => {
    render(<Wizard />);
    for (const label of ["Load city", "Buildings", "Optimize", "Choose", "Export"]) {
      expect(screen.getAllByText(label).length).toBeGreaterThan(0);
    }
    const items = screen.getAllByRole("listitem");
    expect(items).toHaveLength(5);
    expect(items[0].getAttribute("aria-current")).toBe("step");
    expect(items[1].getAttribute("aria-current")).toBeNull();
  });

  it("language switch", () => {
    render(<Wizard />);
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "fr" } });
    expect(screen.getAllByText(translate("fr", "step.load")).length).toBeGreaterThan(0);
    expect(screen.getAllByText(translate("fr", "step.export")).length).toBeGreaterThan(0);
    expect(document.title).toBe(translate("fr", "app.title"));
  });

  it("reset keeps language", () => {
    act(() => {
      useWizardStore.getState().setLang("fr");
      useWizardStore.getState().go(3);
    });
    act(() => useWizardStore.getState().reset());
    const s = useWizardStore.getState();
    expect(s.step).toBe(1);
    expect(s.lang).toBe("fr");
  });
});
