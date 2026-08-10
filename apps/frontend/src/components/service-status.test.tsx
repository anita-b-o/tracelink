import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ServiceStatus } from "./service-status";

describe("ServiceStatus", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("shows the loading state while checking dependencies", () => {
    vi.stubGlobal("fetch", vi.fn(() => new Promise(() => undefined)));

    render(<ServiceStatus />);

    expect(screen.getByRole("status")).toHaveTextContent("Comprobando servicios");
  });

  it("shows the available state when readiness succeeds", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true }));

    render(<ServiceStatus />);

    await waitFor(() =>
      expect(screen.getByRole("status")).toHaveTextContent(
        "API, PostgreSQL y Redis disponibles",
      ),
    );
  });

  it("shows the unavailable state when readiness fails", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false }));

    render(<ServiceStatus />);

    await waitFor(() =>
      expect(screen.getByRole("status")).toHaveTextContent("Servicios aún no disponibles"),
    );
  });
});
