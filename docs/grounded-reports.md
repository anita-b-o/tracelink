# Grounded answers y reportes

## Contexto y citas

`GroundedContextBuilder` entrega al LLM chunks, Source/Document, EntityMentions/Entities,
Relationships, Evidence y contradicciones con IDs tipados (`CHUNK:<uuid>`, `EVIDENCE:<uuid>`,
etc.). El contexto se corta antes de 24.000 caracteres.

Cada claim factual requiere citas. `CitationValidator` exige que el ID haya sido entregado al LLM
y vuelve a comprobar en PostgreSQL que Evidence o el artefacto pertenezcan a la Investigation.
Rechaza citas duplicadas, inventadas y cross-investigation. Answer, confidence y citations globales
se derivan de claims ya validados.

Si el mejor score es menor a 0.20 o no hay al menos una Evidence persistida, Q&A no invoca el LLM y
responde: “No hay evidencia suficiente en esta investigación para responder con confianza.”

## Contradicciones, fechas y prompt injection

Relationships `CONTRADICTED`, pares Supporting/Contradicting y claims `AFFIRMS/NEGATES` sobre la
misma relación producen una contradicción con citas de ambos lados; TraceLink no selecciona una
versión usando conocimiento externo. Claims `ENDS` alimentan eventos de cierre. Las timelines
preservan `YYYY`, `YYYY-MM` y `YYYY-MM-DD`, y etiquetan por separado publicación, inicio y fin.
`retrieved_at` sólo puede describir recuperación.

Sources y Documents se serializan como datos no confiables en un bloque separado. El system prompt
ordena ignorar instrucciones contenidas en ellos. Aunque un modelo intente emitir IDs ajenos, el
validador determinista rechaza el output.

## Reportes

Los tipos iniciales son Executive Summary, Corporate Profile, Relationship Summary y Timeline
Summary. Corporate Profile requiere una COMPANY/ORGANIZATION mencionada en el caso. POST persiste
un reporte PENDING y lo encola; GET permite polling. Un fingerprint de datos, subject, provider,
modelo, prompt y configuración evita regeneraciones idénticas. Los estados son PENDING, RUNNING,
COMPLETED y FAILED.

Corporate Profile entrega únicamente campos presentes: aliases y metadata de entidad, más
personas, organizaciones, dominios o direcciones que aparezcan en Relationships/Evidence. La
ausencia de un atributo no se completa por inferencia.
