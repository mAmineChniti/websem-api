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

## Demo questions for NLP
- "Liste les assurés"
- "Combien de personnes ?"
- "Liste les contrats"
- "Statistiques sur les primes"
- "Liste les sinistres"
- "Déclarations acceptées"
- "Classes de l'ontologie"
- "Propriétés de l'ontologie"