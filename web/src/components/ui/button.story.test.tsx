import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import axe from "axe-core";
import { Button } from "@/components/ui/button";

afterEach(cleanup);

describe("Button foundation story smoke", () => {
  it("renders an operable, axe-clean primary action", async () => {
    const { container } = render(<Button>Capture note</Button>);

    expect(screen.getByRole("button", { name: "Capture note" })).toBeEnabled();
    expect((await axe.run(container)).violations).toEqual([]);
  });
});
