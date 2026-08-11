import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Progress } from "./progress";
import { StatusBadge } from "./status-badge";
import { investigationActions } from "@/features/workspace/investigation-workspace";

describe("workspace status UI", () => {
  it("renders semantic status labels", () => {
    render(<StatusBadge status="AUTO_ACCEPTED"/>);
    expect(screen.getByText("AUTO ACCEPTED")).toHaveClass("status-success");
  });

  it("renders exact progress and task failures", () => {
    render(<Progress value={{total:10,pending:1,running:1,completed:7,failed:1,cancelled:0,percent:70}}/>);
    expect(screen.getByLabelText("70% complete")).toHaveTextContent("7/10 tasks · 1 failed");
  });

  it("enforces the investigation action matrix", () => {
    expect(investigationActions("DRAFT")).toEqual({start:true,cancel:true,retryFailedTasks:false});
    expect(investigationActions("RUNNING")).toEqual({start:false,cancel:true,retryFailedTasks:false});
    expect(investigationActions("FAILED")).toEqual({start:false,cancel:false,retryFailedTasks:true});
    expect(investigationActions("COMPLETED").start).toBe(false);
  });
});
