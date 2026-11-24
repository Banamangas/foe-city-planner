// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useWizardStore } from "../wizardStore";
import { ProblemView } from "./LoadStep";
import { UnknownBuildingsForm } from "./UnknownBuildingsForm";

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
