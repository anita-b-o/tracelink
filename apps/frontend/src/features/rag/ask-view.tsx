"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { BookOpen, Search, Send } from "lucide-react";
import { useState, type FormEvent } from "react";

import { ErrorState, LoadingState } from "@/components/ui/async-state";
import { Drawer } from "@/components/ui/drawer";
import { StatusBadge } from "@/components/ui/status-badge";
import { api } from "@/lib/api/client";

type CitationLink = {id:string;evidence_id?:string|null;document_id?:string|null;source_url?:string|null};

export function AbstentionNotice(){return <div className="warning-banner"><strong>No hay evidencia suficiente en esta investigación para responder con confianza.</strong><p>This is an evidence threshold decision, not an application error.</p></div>}
export function CitationList({citations,onOpen}:{citations:CitationLink[];onOpen:(citation:CitationLink)=>void}){return <section className="detail-section"><h3>Citations</h3>{citations.map(citation=><button className="citation-link" key={citation.id} onClick={()=>onOpen(citation)}><BookOpen size={13}/>{citation.id}</button>)}</section>}

export function AskView({id}:{id:string}) {
  const[question,setQuestion]=useState("");
  const[searchText,setSearchText]=useState("");
  const[evidenceId,setEvidenceId]=useState<string|null>(null);
  const[documentId,setDocumentId]=useState<string|null>(null);
  const ask=useMutation({mutationFn:(value:string)=>api.ask(id,value)});
  const search=useMutation({mutationFn:(value:string)=>api.search(id,value)});
  const evidence=useQuery({queryKey:["evidence",evidenceId],queryFn:()=>api.evidence(evidenceId!),enabled:Boolean(evidenceId)});
  const document=useQuery({queryKey:["document",documentId],queryFn:()=>api.document(documentId!),enabled:Boolean(documentId)});
  const submit=(event:FormEvent)=>{event.preventDefault();if(question.trim())ask.mutate(question.trim())};
  const openCitation=(citation:CitationLink)=>{if(citation.evidence_id)setEvidenceId(citation.evidence_id);else if(citation.document_id)setDocumentId(citation.document_id);else if(citation.source_url)window.open(citation.source_url,"_blank","noopener,noreferrer")};
  return <>
    <div className="section-heading"><div><h2>Ask this investigation</h2><p>Answers are limited to persisted evidence and show every citation.</p></div></div>
    <div className="panel"><form className="ask-form" onSubmit={submit}><input className="field" aria-label="Question" value={question} onChange={e=>setQuestion(e.target.value)} maxLength={2000} placeholder="Ask this investigation…"/><button className="button" disabled={ask.isPending||!question.trim()}><Send size={15}/> Ask</button></form>
      {ask.isPending&&<LoadingState label="Retrieving grounded evidence…"/>}{ask.error&&<ErrorState error={ask.error} retry={()=>ask.mutate(question)}/>} {ask.data&&<div className="answer">{ask.data.abstained?<AbstentionNotice/>:<><div className="panel-header"><h3>Grounded answer</h3><StatusBadge status={`${Math.round(ask.data.confidence*100)}% CONFIDENCE`}/></div><p>{ask.data.answer}</p><section className="detail-section"><h3>Claims</h3>{ask.data.claims.map((claim,index)=><article className="claim" key={`${index}-${claim.text}`}><p>{claim.text}</p><span className="subtle">Confidence {Math.round(claim.confidence*100)}%</span>{claim.citation_ids.map(citation=><span className="status-badge status-neutral" key={citation}>{citation}</span>)}</article>)}</section><CitationList citations={ask.data.citations} onOpen={openCitation}/></>}{ask.data.contradictions.length>0&&<section className="detail-section"><h3>Contradictions</h3>{ask.data.contradictions.map((item,index)=><div className="danger-banner" key={index}>{typeof item.summary==="string"?item.summary:"Opposing evidence is present."}</div>)}</section>}{ask.data.limitations.length>0&&<section className="detail-section"><h3>Limitations</h3><ul>{ask.data.limitations.map(item=><li key={item}>{item}</li>)}</ul></section>}</div>}
    </div>
    <details className="panel"><summary>Hybrid evidence search</summary><form className="ask-form" onSubmit={event=>{event.preventDefault();if(searchText.trim())search.mutate(searchText.trim())}}><input className="field" value={searchText} onChange={e=>setSearchText(e.target.value)} placeholder="Search chunks semantically and lexically…"/><button className="button secondary"><Search size={15}/> Search</button></form>{search.isPending&&<LoadingState/>}{search.data?.map(hit=><article className="evidence-card" key={hit.chunk_id}><strong>{hit.source_title??new URL(hit.source_url).host}</strong><p>{hit.chunk_text}</p><span className="subtle">Combined {hit.combined_score.toFixed(3)} · semantic {hit.semantic_score.toFixed(3)} · lexical {hit.lexical_score.toFixed(3)}</span></article>)}</details>
    {evidenceId&&<Drawer title="Citation evidence" onClose={()=>setEvidenceId(null)}>{evidence.isLoading?<LoadingState/>:evidence.error?<ErrorState error={evidence.error} retry={()=>void evidence.refetch()}/>:evidence.data&&<article className={`evidence-card ${evidence.data.evidence_type==="CONTRADICTING"?"contradicting":""}`}><StatusBadge status={evidence.data.evidence_type}/><p>{evidence.data.preview??"No text preview available."}</p><span className="subtle">Confidence {Math.round(evidence.data.confidence*100)}%</span>{evidence.data.source&&<a className="external-link" href={evidence.data.source.url} target="_blank" rel="noopener noreferrer">Open source</a>}</article>}</Drawer>}
    {documentId&&<Drawer title="Citation document" onClose={()=>setDocumentId(null)}>{document.isLoading?<LoadingState/>:document.error?<ErrorState error={document.error} retry={()=>void document.refetch()}/>:document.data&&<><a className="external-link" href={document.data.source.url} target="_blank" rel="noopener noreferrer">{document.data.source.title??"Open source"}</a><div className="document-content">{document.data.content}</div>{document.data.has_more&&<p className="muted">Document preview truncated at 5,000 characters.</p>}</>}</Drawer>}
  </>;
}
