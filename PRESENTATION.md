# Presentation notes — Web Semantique mini-project

## Theme
Assurance habitation et gestion des sinistres.

## Tools used (to mention explicitly)
- Ontology editing: Protégé (OWL/RDF XML).
- Backend: Python 3.11+, FastAPI, Pydantic settings.
- RDF/SPARQL: rdflib 7.x (`Graph`, `Namespace`, SPARQL `SELECT`/`ASK`/Update).
- NLP/TALN (no LLM API):
  - NLTK: `word_tokenize`, French stopwords, `SnowballStemmer`.
  - spaCy: `fr_core_news_sm` (POS tagging, NER).
  - In-house intent matcher (keyword + stem scoring, slot injection).

## Validation checklist (backend side)
- Ontology created with classes, ObjectProperty, DataProperty, individuals and axioms: yes (`assurance.rdf`).
- SPARQL CRUD/filtering/search: yes (REST endpoints + direct `/sparql` + examples).
- Front/back communication: REST JSON + CORS; frontend is a separate project.
- NLP translator NL → SPARQL: yes (`/api/ontology/nlp/ask`).
- Coverage: 33 intents, including generic + subtype queries for the
  **sinistre** module (incendie, vol, dégât des eaux, bris de glace,
  catastrophe naturelle) and the **garantie** module (same subtypes +
  responsabilité civile, clauses), with dynamic amount/location/person/
  status/date filters.

## Demo questions for NLP
- "Liste les assurés"
- "Combien de personnes ?"
- "Liste les contrats"
- "Statistiques sur les primes"
- "Liste les sinistres"
- "Liste les sinistres incendie"
- "Liste les sinistres de vol"
- "Liste les sinistres dégât des eaux"
- "Liste les garanties"
- "Liste les garanties incendie"
- "Liste les garanties responsabilité civile"
- "Liste les clauses"
- "Déclarations acceptées"
- "Déclarations rejetées"
- "Contrats dont la prime dépasse 700 dinars"
- "Qui est l'assuré BenAli ?"
- "Classes de l'ontologie"
- "Propriétés de l'ontologie"