# websem-api

FastAPI backend for the **Web Semantique** mini-project: an insurance
ontology (assurance habitation / gestion des sinistres) exposed through a
REST API, with a rule-based NLP-to-SPARQL translator.

The front-end is a separate project; this repository contains the backend
and the ontology only.

## Ontology

- Theme: home-insurance claims management.
- File: `assurance.rdf` (OWL/RDF XML, Protégé-compatible).
- Namespace classes: `http://www.semanticweb.org/asus/ontologies/2026/8/untitled-ontology-5#`
- Properties/individuals: `http://www.semanticweb.org/asus/ontologies/2026/8/Assuarnce_et_Gestion_des_Sinistres#`
- 47 named classes plus 2 anonymous OWL class expressions, 13 object properties,
  25 data properties, 20 named individuals,
  plus disjoint/equivalent-class and restriction axioms.

## NLP / TALN module

`app/services/nlp_sparql.py` translates a French natural-language question
into an executable SPARQL query without any LLM API (no Gemini/OpenAI/etc.).
It uses:

- **NLTK** (`nltk.tokenize.word_tokenize`, `nltk.corpus.stopwords`,
  `nltk.stem.snowball.SnowballStemmer`) for tokenisation, stop-word removal
  and French stemming.
- **spaCy** (`fr_core_news_sm`) for POS tagging and named-entity recognition
  (persons, locations, amounts, dates).
- **rdflib** for parsing the ontology and executing the generated SPARQL.
- An in-house intent matcher (keyword + stem scoring) that selects one of
  33 predefined SPARQL templates and injects detected slots as `FILTER`s.
  Class filters are grounded in the ontology with `rdfs:subClassOf*` (so
  `SinistreIncendie`, `GarantieVol`, etc. are matched without fragile string
  comparisons), and slots cover amounts, locations, persons, declaration
  status and dates.
- Coverage includes the **garantie** module (generic + incendie, vol, dégât
  des eaux, bris de glace, catastrophe naturelle, responsabilité civile,
  clauses) and the **sinistre** module (generic + incendie, vol, dégât des
  eaux, bris de glace, catastrophe naturelle), plus declarations, documents,
  dommages and indemnisations.

Endpoint: `POST /api/ontology/nlp/ask` with body `{"question": "..."}`.
Available intents: `GET /api/ontology/nlp/intents`.

## API

Run with:

```bash
cp .env.example .env
uv sync
uv run fastapi dev app/main.py
```

Main endpoints (prefix `/api`):

- `/health`
- `/ontology/stats`, `/ontology/classes`
- `/ontology/properties/object`, `/ontology/properties/datatype`
- `/ontology/personnes`, `/ontology/contrats`, `/ontology/sinistres`,
  `/ontology/garanties`, `/ontology/documents`, `/ontology/dommages`
- `/ontology/sparql`, `/ontology/sparql/examples`
- `/ontology/nlp/ask`, `/ontology/nlp/intents`
- `/ontology/search?q=...`

Interactive docs: `/docs`.

## Tests

```bash
uv run pytest
uv run ruff check .
```