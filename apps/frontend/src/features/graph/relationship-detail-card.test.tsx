import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { RelationshipDetail } from "@/lib/api/types";
import { RelationshipDetailCard } from "./relationship-detail-card";

describe("relationship evidence rendering",()=>{
  it("keeps supporting and contradicting positions visible",()=>{
    const item={id:"r1",type:"DIRECTOR_OF",status:"CONTRADICTED",confidence:.81,temporal_start:"2020",temporal_end:null,first_observed_at:null,last_observed_at:null,metadata:{},created_at:"2024-01-01",updated_at:"2024-01-01",evidence_count:2,source_entity:{id:"e1",type:"PERSON",canonical_name:"Jane",metadata:{}},target_entity:{id:"e2",type:"COMPANY",canonical_name:"ACME",metadata:{}},claims:[],evidence:[{id:"support",investigation_id:"i1",source_id:"s1",document_id:"d1",relationship_id:"r1",entity_id:null,excerpt:"Jane was appointed",locator:null,start_offset:0,end_offset:18,evidence_type:"SUPPORTING",confidence:.9,metadata:{},created_at:"2024-01-01",preview:"Jane was appointed",source:null,document_title:"Filing"},{id:"oppose",investigation_id:"i1",source_id:"s1",document_id:"d1",relationship_id:"r1",entity_id:null,excerpt:"Jane denied the role",locator:null,start_offset:20,end_offset:40,evidence_type:"CONTRADICTING",confidence:.8,metadata:{},created_at:"2024-01-02",preview:"Jane denied the role",source:null,document_title:"Statement"}]} as unknown as RelationshipDetail;
    render(<RelationshipDetailCard item={item}/>);
    expect(screen.getByText(/Opposing evidence is preserved/)).toBeVisible();
    expect(screen.getByText("Jane was appointed")).toBeVisible();
    expect(screen.getByText("Jane denied the role")).toBeVisible();
    expect(screen.getByText("CONTRADICTED")).toBeVisible();
  });
});
