import { describe, expect, it } from "vitest";

import { buildTimeline, sortTimeline, type TimelineEvent } from "./timeline-view";
import type { Relationship, Source } from "@/lib/api/types";

describe("timeline partial dates",()=>{
  it("preserves year, month, and day precision with stable ordering",()=>{const events:TimelineEvent[]=[{id:"day",date:"2024-03-02",kind:"CLAIM",title:"",detail:""},{id:"year",date:"2024",kind:"CLAIM",title:"",detail:""},{id:"month",date:"2024-03",kind:"CLAIM",title:"",detail:""}];expect(sortTimeline(events).map(item=>item.date)).toEqual(["2024","2024-03","2024-03-02"]);});
  it("creates starts, ends, contradictions, and publications",()=>{const relationship={id:"r",source_entity:{canonical_name:"Jane"},target_entity:{canonical_name:"ACME"},type:"DIRECTOR_OF",status:"CONTRADICTED",temporal_start:"2020",temporal_end:"2024-06"} as Relationship;const source={id:"s",url:"https://example.test/a",title:"Filing",published_at:"2024-06-02T00:00:00Z"} as Source;const events=buildTimeline([relationship],[],[source]);expect(events.map(item=>item.kind)).toEqual(expect.arrayContaining(["RELATIONSHIP_START","RELATIONSHIP_END","CONTRADICTION","SOURCE_PUBLISHED"]));expect(events.find(item=>item.kind==="RELATIONSHIP_END")?.date).toBe("2024-06");});
});
