# Graph UI

The Graph tab uses React Flow for zoom, pan, fit view, node selection, edge selection, and a
minimap. The backend returns a bounded investigation subgraph so the browser never discovers a
large dataset by downloading every row.

Nodes are PERSON, COMPANY, ORGANIZATION, DOMAIN, or ADDRESS. Each type combines label, icon, color,
and shape treatment; DOCUMENT is excluded. Nodes include entities mentioned in the investigation
and endpoints required by materialized, evidenced relationships, even when an endpoint has no
direct mention. Clicking a node opens its entity view.

Edges are materialized Relationships with evidence. MENTIONED_IN and review-only candidates are
excluded. Edge labels show relationship type; CONTRADICTED edges remain present with a dashed,
animated danger treatment. Clicking an edge opens relationship detail and its supporting and
contradicting Evidence.

`NEXT_PUBLIC_GRAPH_MAX_NODES` defaults to 250 and the API enforces the same ceiling. The payload
includes `total_nodes` and `truncated`; the UI warns when filters or entity focus are needed.
Entity-type and relationship-type filters are represented by query parameters; the API also
supports focused subgraphs. A basic deterministic grid layout avoids a heavyweight layout engine.

Graph tests assert semantic mapping, exclusions, truncation, contradiction treatment, visible
nodes/edges, edge detail, and filter reduction; they do not assert pixel coordinates.
