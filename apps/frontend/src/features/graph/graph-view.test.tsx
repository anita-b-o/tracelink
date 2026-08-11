import { describe, expect, it } from "vitest";

import { mapGraph } from "./graph-view";
import type { GraphData } from "@/lib/api/types";

const graph:GraphData={nodes:[{id:"person",type:"PERSON",label:"Jane Doe",mention_count:3},{id:"company",type:"COMPANY",label:"ACME",mention_count:2}],edges:[{id:"edge",source:"person",target:"company",type:"DIRECTOR_OF",status:"CONTRADICTED",confidence:.8,evidence_count:2}],total_nodes:320,truncated:true};

describe("graph mapping",()=>{
  it("maps allowed nodes and materialized edges",()=>{const mapped=mapGraph(graph);expect(mapped.nodes.map(item=>item.id)).toEqual(["person","company"]);expect(mapped.edges).toHaveLength(1);expect(mapped.edges[0].label).toBe("DIRECTOR OF");});
  it("marks contradicted edges without hiding them",()=>{const edge=mapGraph(graph).edges[0];expect(edge.animated).toBe(true);expect(edge.style).toMatchObject({strokeDasharray:"7 4"});});
  it("preserves the backend truncation contract",()=>{expect(graph.truncated).toBe(true);expect(graph.total_nodes).toBeGreaterThan(graph.nodes.length);});
});
