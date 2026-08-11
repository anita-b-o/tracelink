import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { api } from "@/lib/api/client";
import type { Entity, Mention, Task } from "@/lib/api/types";
import { EntitiesView, TasksView } from "./views";

vi.mock("next/navigation",()=>({useRouter:()=>({push:vi.fn()}),useSearchParams:()=>new URLSearchParams("entity=e1")}));

afterEach(()=>{cleanup();vi.restoreAllMocks();});

describe("entity exploration",()=>{
  it("renders canonical identity, aliases, counts, and mention context",async()=>{
    const entity={id:"e1",type:"COMPANY",canonical_name:"ACME",aliases:[{id:"a1",alias:"ACME S.A.",normalized_alias:"acme sa",created_at:"2024-01-01"}],metadata:{},mention_count:2,created_at:"2024-01-01",updated_at:"2024-01-01"} as Entity;
    const mention={id:"m1",investigation_id:"i1",document_id:"d1",entity_id:"e1",entity_type:"COMPANY",surface_form:"ACME S.A.",normalized_form:"acme sa",start_offset:5,end_offset:14,chunk_index:0,extraction_method:"fixture",confidence:.97,metadata:{},created_at:"2024-01-01",document_title:"Registry filing",context_preview:"Jane directs ACME S.A. since 2020.",source:{id:"s1",type:"fixture",publisher:"Registry",url:"https://example.test/file",title:"Registry filing",published_at:null,retrieved_at:"2024-01-01",document_count:1}} as Mention;
    vi.spyOn(api,"entities").mockResolvedValue([entity]);vi.spyOn(api,"mentions").mockResolvedValue([mention]);
    render(<QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false}}})}><EntitiesView id="i1"/></QueryClientProvider>);
    expect(await screen.findAllByText("ACME")).not.toHaveLength(0);
    expect(screen.getAllByText("ACME S.A.")).toHaveLength(2);
    expect(await screen.findByText("Jane directs ACME S.A. since 2020.")).toBeVisible();
    expect(screen.getByText(/Confidence 97%/)).toBeVisible();
  });
  it("offers retry only for a failed research task",async()=>{const task={id:"t1",investigation_id:"i1",type:"WEB_SEARCH",status:"FAILED",query:"ACME",source_type:null,attempts:1,max_attempts:3,active_celery_task_id:null,started_at:"2024-01-01",completed_at:"2024-01-01",last_error_code:"PROVIDER",last_error_message:"provider failed",result:null,created_at:"2024-01-01",updated_at:"2024-01-01"} as unknown as Task;vi.spyOn(api,"tasks").mockResolvedValue([task]);const retry=vi.spyOn(api,"retryTask").mockResolvedValue({...task,status:"PENDING"});render(<QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false}}})}><TasksView id="i1" active={false}/></QueryClientProvider>);fireEvent.click(await screen.findByRole("button",{name:"Retry"}));await waitFor(()=>expect(retry).toHaveBeenCalled());expect(retry.mock.calls[0]?.[0]).toBe("t1");});
});
