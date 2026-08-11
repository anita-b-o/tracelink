import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { AbstentionNotice, CitationList } from "./ask-view";

describe("grounded answer UI",()=>{
  it("treats abstention as an evidence state",()=>{render(<AbstentionNotice/>);expect(screen.getByText("No hay evidencia suficiente en esta investigación para responder con confianza.")).toBeVisible();expect(screen.queryByRole("alert")).not.toBeInTheDocument();});
  it("renders citations as keyboard-accessible buttons",()=>{const open=vi.fn();render(<CitationList citations={[{id:"E1",evidence_id:"evidence"}]} onOpen={open}/>);fireEvent.click(screen.getByRole("button",{name:/E1/}));expect(open).toHaveBeenCalledWith({id:"E1",evidence_id:"evidence"});});
});
