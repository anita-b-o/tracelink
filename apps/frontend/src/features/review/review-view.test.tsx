import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { api } from "@/lib/api/client";
import type { EntityCandidate, RelationshipCandidate } from "@/lib/api/types";
import { ReviewView } from "./review-view";

vi.mock("next/navigation",()=>({useRouter:()=>({push:vi.fn()}),useSearchParams:()=>new URLSearchParams()}));

const entityCandidate={id:"ec1",investigation_id:"i1",mention_id:"m1",candidate_entity_id:"target",score:.82,status:"PENDING",signals:{name_similarity:.91},created_at:"2024-01-01",reviewed_at:null,mention:{id:"m1",surface_form:"Acme SA",context_preview:"Acme SA appears in the filing"},provisional_entity:{id:"provisional",type:"COMPANY",canonical_name:"Acme SA",metadata:{resolution_provisional:true}},candidate_entity:{id:"target",type:"COMPANY",canonical_name:"ACME",metadata:{}}} as unknown as EntityCandidate;
const relationshipCandidate={id:"rc1",investigation_id:"i1",document_id:"d1",source_entity_id:"person",target_entity_id:"target",type:"DIRECTOR_OF",claim_kind:"AFFIRMS",confidence:.78,score:.76,extraction_method:"fixture",supporting_text:"Jane directs ACME",evidence_preview:"Jane directs ACME",start_offset:0,end_offset:17,temporal_start:"2020",temporal_end:null,metadata:{},signals:{reason_codes:["EXACT_MENTION"]},reason_codes:["EXACT_MENTION"],status:"PENDING",fingerprint:"fingerprint",created_at:"2024-01-01",updated_at:"2024-01-01",reviewed_at:null,source_entity:{id:"person",type:"PERSON",canonical_name:"Jane",metadata:{}},target_entity:{id:"target",type:"COMPANY",canonical_name:"ACME",metadata:{}},source:null} as RelationshipCandidate;

afterEach(()=>{cleanup();vi.restoreAllMocks();});
function renderReview(){return render(<QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false}}})}><ReviewView id="i1"/></QueryClientProvider>);}

describe("review candidate flows",()=>{
  it("accepts an entity resolution candidate and refreshes the queue",async()=>{let items=[entityCandidate];vi.spyOn(api,"entityCandidates").mockImplementation(async()=>items);vi.spyOn(api,"relationshipCandidates").mockResolvedValue([]);const review=vi.spyOn(api,"reviewEntity").mockImplementation(async()=>{items=[];return {};});renderReview();fireEvent.click(await screen.findByRole("button",{name:"Accept match"}));await waitFor(()=>expect(review).toHaveBeenCalledWith("ec1","accept"));await waitFor(()=>expect(screen.getByText("No entity candidates")).toBeVisible());});
  it("rejects a relationship candidate without deleting its preview",async()=>{let items=[relationshipCandidate];vi.spyOn(api,"entityCandidates").mockResolvedValue([]);vi.spyOn(api,"relationshipCandidates").mockImplementation(async()=>items);const review=vi.spyOn(api,"reviewRelationship").mockImplementation(async()=>{items=[];return {};});renderReview();expect(await screen.findByText("Jane directs ACME")).toBeVisible();fireEvent.click(screen.getByRole("button",{name:"Reject"}));await waitFor(()=>expect(review).toHaveBeenCalledWith("rc1","reject"));await waitFor(()=>expect(screen.getByText("No relationship candidates")).toBeVisible());});
});
