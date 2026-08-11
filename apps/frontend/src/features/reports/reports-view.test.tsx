import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ReportContentView } from "./reports-view";

describe("report rendering",()=>{
  it("renders pending and failed report states",()=>{const {rerender}=render(<ReportContentView status="PENDING" content={null} error={null}/>);expect(screen.getByText("Report pending…")).toBeVisible();rerender(<ReportContentView status="FAILED" content={null} error="provider failed"/>);expect(screen.getByText("provider failed")).toBeVisible();});
  it("renders structured content without raw JSON",()=>{render(<ReportContentView status="COMPLETED" error={null} content={{title:"ACME brief",abstained:false,executive_summary:"Grounded summary",summary_claims:[],sections:[{heading:"Ownership",claims:[{text:"Jane directs ACME",confidence:.91,citation_ids:["E1"]}]}],key_entities:[],key_relationships:[],timeline:[],contradictions:[],limitations:["Limited history"],citations:[]}}/>);expect(screen.getByRole("heading",{name:"ACME brief"})).toBeVisible();expect(screen.getByText("Jane directs ACME")).toBeVisible();expect(screen.getByText("Limited history")).toBeVisible();});
});
