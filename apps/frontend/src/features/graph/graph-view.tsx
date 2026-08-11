"use client";

import { useQuery } from "@tanstack/react-query";
import { Background, Controls, MiniMap, ReactFlow, type Edge, type Node } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { Building2, CircleUserRound, Globe2, Landmark, MapPin, type LucideIcon } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { useMemo, useState } from "react";

import { ErrorState, LoadingState } from "@/components/ui/async-state";
import { Drawer } from "@/components/ui/drawer";
import { api } from "@/lib/api/client";
import type { EntityType } from "@/lib/api/types";
import { RelationshipDetailCard } from "./relationship-detail-card";

const icons: Partial<Record<EntityType, LucideIcon>> = { PERSON:CircleUserRound, COMPANY:Building2, ORGANIZATION:Landmark, DOMAIN:Globe2, ADDRESS:MapPin };

export function mapGraph(data: Awaited<ReturnType<typeof api.graph>>) {
  const nodes: Node[] = data.nodes.map((item,index)=>{ const Icon=icons[item.type] ?? Landmark; const columns=Math.max(Math.ceil(Math.sqrt(data.nodes.length)),1); return { id:item.id, position:{x:(index%columns)*230,y:Math.floor(index/columns)*150}, data:{label:<div className={`graph-node ${item.type.toLowerCase()}`}><Icon size={18}/><span>{item.label}<small>{item.type} · {item.mention_count}</small></span></div>}, style:{background:"transparent",border:0,padding:0,width:170} }; });
  const edges: Edge[] = data.edges.map(item=>({id:item.id,source:item.source,target:item.target,label:item.type.replaceAll("_"," "),animated:item.status==="CONTRADICTED",style:{stroke:item.status==="CONTRADICTED"?"#f1777f":"#5f7788",strokeWidth:item.status==="CONTRADICTED"?2.5:1.5,strokeDasharray:item.status==="CONTRADICTED"?"7 4":undefined},labelStyle:{fill:item.status==="CONTRADICTED"?"#ffabb0":"#aebbc5",fontSize:9,fontWeight:700}}));
  return {nodes,edges};
}

export function GraphView({id}:{id:string}) {
  const search=useSearchParams(); const router=useRouter(); const [selected,setSelected]=useState<string|null>(null); const entityType=search.get("type")??""; const relationshipType=search.get("relationship_type")??""; const focus=search.get("focus")??""; const maxNodes=Number(process.env.NEXT_PUBLIC_GRAPH_MAX_NODES??"250");
  const query=useQuery({queryKey:["graph",id,entityType,relationshipType,focus],queryFn:()=>api.graph(id,{entity_type:entityType,relationship_type:relationshipType,focus_entity_id:focus,max_nodes:maxNodes})});
  const mapped=useMemo(()=>query.data?mapGraph(query.data):{nodes:[],edges:[]},[query.data]);
  const detail=useQuery({queryKey:["relationship",id,selected],queryFn:()=>api.relationship(id,selected!),enabled:Boolean(selected)});
  if(query.isLoading)return <LoadingState label="Building investigation graph…"/>; if(query.error)return <ErrorState error={query.error} retry={()=>void query.refetch()}/>;
  const setFilter=(key:string,value:string)=>{const next=new URLSearchParams(search);if(value)next.set(key,value);else next.delete(key);router.push(`?${next}`)};
  return <><div className="section-heading"><div><h2>Investigation graph</h2><p>Materialized entities and evidence-backed relationships. Candidates remain in Review.</p></div></div><div className="filter-row"><select aria-label="Graph entity type" value={entityType} onChange={event=>setFilter("type",event.target.value)}><option value="">All entity types</option>{["PERSON","COMPANY","ORGANIZATION","DOMAIN","ADDRESS"].map(value=><option key={value}>{value}</option>)}</select><select aria-label="Graph relationship type" value={relationshipType} onChange={event=>setFilter("relationship_type",event.target.value)}><option value="">All relationship types</option>{["DIRECTOR_OF","OWNER_OF","EMPLOYEE_OF","RELATED_TO","SHARES_ADDRESS_WITH","OWNS_DOMAIN","SUBSIDIARY_OF","PARTNER_OF"].map(value=><option key={value}>{value}</option>)}</select>{focus&&<button className="button secondary small" onClick={()=>setFilter("focus","")}>Clear focus</button>}</div><div className="mobile-graph-note warning-banner">Graph interaction is limited on small screens. Use the entity and relationship tables for full detail.</div>{query.data?.truncated&&<div className="warning-banner">Showing {query.data.nodes.length} of {query.data.total_nodes} entities. Apply filters or focus an entity to inspect a smaller subgraph.</div>}<div className="graph-canvas" data-testid="graph-canvas"><ReactFlow nodes={mapped.nodes} edges={mapped.edges} fitView minZoom={.2} maxZoom={2} onNodeClick={(_,node)=>router.push(`?tab=entities&entity=${node.id}`)} onEdgeClick={(_,edge)=>setSelected(edge.id)} aria-label="Investigation relationship graph"><Background color="#22303b" gap={24}/><Controls/><MiniMap nodeColor="#44c3a1" maskColor="rgb(4 8 12 / 70%)"/></ReactFlow></div>{selected&&<Drawer title="Graph relationship" onClose={()=>setSelected(null)}>{detail.isLoading?<LoadingState/>:detail.error?<ErrorState error={detail.error} retry={()=>void detail.refetch()}/>:detail.data&&<RelationshipDetailCard item={detail.data}/>}</Drawer>}</>;
}
