"""
Module NLP/TALN — Traducteur Question Naturelle → Requête SPARQL
================================================================
Pipeline en 3 étapes :
  1. NLTK  : tokenisation, suppression des stopwords, stemming (SnowballStemmer)
  2. spaCy : reconnaissance d'entités (NER) — noms, dates, montants
  3. Intent Matcher : correspondance d'intention étendue → génération de requête SPARQL

Bibliothèques utilisées : NLTK, spaCy (fr_core_news_sm), re
"""

import re
import time
from typing import Any, Dict, List, Optional

# ── NLTK ─────────────────────────────────────────────────────────────────────
import nltk
from nltk.tokenize import word_tokenize
from nltk.corpus import stopwords
from nltk.stem.snowball import SnowballStemmer

# ── spaCy ────────────────────────────────────────────────────────────────────
try:
    import spacy
    _nlp_model = spacy.load("fr_core_news_sm")
    SPACY_AVAILABLE = True
except Exception:
    _nlp_model = None
    SPACY_AVAILABLE = False

from app.services.ontology_service import ontology_service

# ── NLTK data téléchargement silencieux ──────────────────────────────────────
for _corpus in ("punkt", "stopwords", "punkt_tab"):
    try:
        nltk.download(_corpus, quiet=True)
    except Exception:
        pass

# ── Stemmer français ─────────────────────────────────────────────────────────
_stemmer = SnowballStemmer("french")

# ── Intentions et requêtes SPARQL ────────────────────────────────────────────
INTENTS: List[Dict[str, Any]] = [
    # ── PERSONNES ──────────────────────────────────────────────────────────
    {
        "id": "LIST_ASSURES",
        "keywords": ["assure", "assures", "client", "clients", "souscripteur", "adherent"],
        "stems":    ["assur", "client", "souscript", "adhér"],
        "description": "Liste tous les assurés de l'ontologie",
        "sparql": """\
SELECT DISTINCT ?assure ?nom ?prenom ?cin ?telephone ?adresse WHERE {
    ?assure a ?type .
    FILTER(contains(str(?type), 'Assure') || contains(str(?assure), 'Assure'))
    OPTIONAL { ?assure as:nom ?nom }
    OPTIONAL { ?assure as:prenom ?prenom }
    OPTIONAL { ?assure as:cin ?cin }
    OPTIONAL { ?assure as:telephone ?telephone }
    OPTIONAL { ?assure as:adresse ?adresse }
}
ORDER BY ?nom""",
    },
    {
        "id": "LIST_AGENTS",
        "keywords": ["agent", "agents", "conseiller", "gestionnaire", "commercial"],
        "stems":    ["agent", "conseil", "gestion", "commerci"],
        "description": "Liste tous les agents d'assurance",
        "sparql": """\
SELECT DISTINCT ?agent ?nom ?prenom ?telephone ?adresse WHERE {
    ?agent a ?type .
    FILTER(contains(str(?type), 'Agent') || contains(str(?agent), 'Agent'))
    OPTIONAL { ?agent as:nom ?nom }
    OPTIONAL { ?agent as:prenom ?prenom }
    OPTIONAL { ?agent as:telephone ?telephone }
    OPTIONAL { ?agent as:adresse ?adresse }
}
ORDER BY ?nom""",
    },
    {
        "id": "LIST_EXPERTS",
        "keywords": ["expert", "experts", "expertise", "evaluateur", "technicien"],
        "stems":    ["expert", "expert", "evaluat", "technici"],
        "description": "Liste tous les experts assignés aux sinistres",
        "sparql": """\
SELECT DISTINCT ?expert ?nom ?prenom ?telephone ?adresse WHERE {
    ?expert a ?type .
    FILTER(contains(str(?type), 'Expert') || contains(str(?expert), 'Expert'))
    OPTIONAL { ?expert as:nom ?nom }
    OPTIONAL { ?expert as:prenom ?prenom }
    OPTIONAL { ?expert as:telephone ?telephone }
    OPTIONAL { ?expert as:adresse ?adresse }
}
ORDER BY ?nom""",
    },
    {
        "id": "LIST_BENEFICIAIRES",
        "keywords": ["beneficiaire", "beneficiaires", "ayant", "droit", "ayantdroit"],
        "stems":    ["benefici", "ayant", "droit"],
        "description": "Liste tous les bénéficiaires",
        "sparql": """\
SELECT DISTINCT ?beneficiaire ?nom ?prenom ?telephone WHERE {
    ?beneficiaire a ?type .
    FILTER(contains(str(?type), 'Beneficiaire') || contains(str(?beneficiaire), 'Beneficiaire'))
    OPTIONAL { ?beneficiaire as:nom ?nom }
    OPTIONAL { ?beneficiaire as:prenom ?prenom }
    OPTIONAL { ?beneficiaire as:telephone ?telephone }
}
ORDER BY ?nom""",
    },
    {
        "id": "COUNT_PERSONNES",
        "keywords": ["combien", "nombre", "total", "count", "statistique"],
        "stems":    ["combi", "nombr", "total", "statist"],
        "description": "Compte le nombre de personnes par rôle",
        "sparql": """\
SELECT ?type (COUNT(?personne) AS ?nb) WHERE {
    ?personne a ?type .
    FILTER(
        contains(str(?type), 'Assure') ||
        contains(str(?type), 'Agent') ||
        contains(str(?type), 'Expert') ||
        contains(str(?type), 'Beneficiaire')
    )
}
GROUP BY ?type
ORDER BY DESC(?nb)""",
    },
    # ── CONTRATS ───────────────────────────────────────────────────────────
    {
        "id": "LIST_CONTRATS_PROPRIETAIRE",
        "keywords": ["proprietaire", "propriétaire", "propriétaires", "proprio"],
        "stems":    ["propriét", "proprietair", "proprio"],
        "description": "Liste les contrats de type Propriétaire",
        "sparql": """\
SELECT DISTINCT ?contrat ?numeroContrat ?montantPrime ?assure ?dateDebut ?dateFin WHERE {
    ?contrat a ?typeContrat .
    FILTER(contains(str(?typeContrat), 'ContratProprietaire'))
    OPTIONAL { ?contrat as:numeroContrat ?numeroContrat }
    OPTIONAL { ?contrat as:montantPrime ?montantPrime }
    OPTIONAL { ?contrat as:aPourAssure ?assure }
    OPTIONAL { ?contrat as:dateDebut ?dateDebut }
    OPTIONAL { ?contrat as:dateFin ?dateFin }
}
ORDER BY ?numeroContrat""",
    },
    {
        "id": "LIST_CONTRATS_LOCATAIRE",
        "keywords": ["locataire", "locataires", "location", "loyer", "loueur"],
        "stems":    ["locatair", "locat", "loyer"],
        "description": "Liste les contrats de type Locataire",
        "sparql": """\
SELECT DISTINCT ?contrat ?numeroContrat ?montantPrime ?assure ?dateDebut ?dateFin WHERE {
    ?contrat a ?typeContrat .
    FILTER(contains(str(?typeContrat), 'ContratLocataire'))
    OPTIONAL { ?contrat as:numeroContrat ?numeroContrat }
    OPTIONAL { ?contrat as:montantPrime ?montantPrime }
    OPTIONAL { ?contrat as:aPourAssure ?assure }
    OPTIONAL { ?contrat as:dateDebut ?dateDebut }
    OPTIONAL { ?contrat as:dateFin ?dateFin }
}
ORDER BY ?numeroContrat""",
    },
    {
        "id": "LIST_ALL_CONTRATS",
        "keywords": ["contrat", "contrats", "police", "polices", "prime", "primes", "cotisation", "assurance"],
        "stems":    ["contrat", "polic", "prim", "cotis", "assuranc"],
        "description": "Liste tous les contrats d'assurance avec leurs primes",
        "sparql": """\
SELECT DISTINCT ?contrat ?typeContrat ?numeroContrat ?dateDebut ?dateFin ?montantPrime ?assure WHERE {
    ?contrat a ?typeContrat .
    FILTER(contains(str(?typeContrat), 'Contrat') || contains(str(?contrat), 'Contrat'))
    OPTIONAL { ?contrat as:numeroContrat ?numeroContrat }
    OPTIONAL { ?contrat as:dateDebut ?dateDebut }
    OPTIONAL { ?contrat as:dateFin ?dateFin }
    OPTIONAL { ?contrat as:montantPrime ?montantPrime }
    OPTIONAL { ?contrat as:aPourAssure ?assure }
}
ORDER BY ?typeContrat ?numeroContrat""",
    },
    {
        "id": "PRIME_STATS",
        "keywords": ["prime", "montant", "cout", "coût", "prix", "tarif", "cher", "moyen", "moyenne"],
        "stems":    ["prim", "montant", "cout", "prix", "tarif", "moy"],
        "description": "Statistiques sur les montants des primes par type de contrat",
        "sparql": """\
SELECT ?typeContrat
       (COUNT(?contrat) AS ?nbContrats)
       (MIN(?montantPrime) AS ?primeMin)
       (MAX(?montantPrime) AS ?primeMax)
WHERE {
    ?contrat a ?typeContrat .
    FILTER(contains(str(?typeContrat), 'Contrat') || contains(str(?contrat), 'Contrat'))
    OPTIONAL { ?contrat as:montantPrime ?montantPrime }
}
GROUP BY ?typeContrat
ORDER BY ?typeContrat""",
    },
    # ── SINISTRES ──────────────────────────────────────────────────────────
    {
        "id": "LIST_SINISTRES",
        "keywords": ["sinistre", "sinistres", "accident", "dommage", "dommages", "incident", "evenement"],
        "stems":    ["sinistr", "accident", "dommag", "incid", "evénem"],
        "description": "Liste tous les sinistres déclarés",
        "sparql": """\
SELECT DISTINCT ?sinistre ?typeSinistre ?dateSinistre ?lieuSinistre ?description ?assure WHERE {
    ?sinistre a ?typeSinistre .
    FILTER(contains(str(?typeSinistre), 'Sinistre') || contains(str(?sinistre), 'Sinistre'))
    OPTIONAL { ?sinistre as:dateSinistre ?dateSinistre }
    OPTIONAL { ?sinistre as:lieuSinistre ?lieuSinistre }
    OPTIONAL { ?sinistre as:descriptionSinistre ?description }
    OPTIONAL { ?sinistre as:estDeclarePar ?assure }
}
ORDER BY DESC(?dateSinistre)""",
    },
    {
        "id": "LIST_SINISTRES_INCENDIE",
        "keywords": ["incendie", "feu", "brulure", "brûlure", "flamme"],
        "stems":    ["incendi", "brûl", "flamm"],
        "description": "Liste les sinistres d'incendie",
        "sparql": """\
SELECT DISTINCT ?sinistre ?dateSinistre ?lieuSinistre ?description ?assure WHERE {
    ?sinistre a ?typeSinistre .
    FILTER(contains(str(?typeSinistre), 'Incendie') || contains(str(?sinistre), 'Incendie'))
    OPTIONAL { ?sinistre as:dateSinistre ?dateSinistre }
    OPTIONAL { ?sinistre as:lieuSinistre ?lieuSinistre }
    OPTIONAL { ?sinistre as:descriptionSinistre ?description }
    OPTIONAL { ?sinistre as:estDeclarePar ?assure }
}""",
    },
    {
        "id": "LIST_SINISTRES_VOL",
        "keywords": ["vol", "vols", "cambriolage", "voleur", "cambrioleur", "effraction"],
        "stems":    ["vol", "cambriolog", "effract"],
        "description": "Liste les sinistres de vol",
        "sparql": """\
SELECT DISTINCT ?sinistre ?dateSinistre ?lieuSinistre ?description ?assure WHERE {
    ?sinistre a ?typeSinistre .
    FILTER(contains(str(?typeSinistre), 'Vol') || contains(str(?sinistre), 'Vol'))
    OPTIONAL { ?sinistre as:dateSinistre ?dateSinistre }
    OPTIONAL { ?sinistre as:lieuSinistre ?lieuSinistre }
    OPTIONAL { ?sinistre as:descriptionSinistre ?description }
    OPTIONAL { ?sinistre as:estDeclarePar ?assure }
}""",
    },
    # ── INDEMNISATIONS ─────────────────────────────────────────────────────
    {
        "id": "LIST_INDEMNISATIONS",
        "keywords": ["indemnisation", "indemnisations", "remboursement", "compensation", "indemnite", "indemnité"],
        "stems":    ["indemnisa", "rembours", "compensat", "indemnit"],
        "description": "Liste toutes les indemnisations",
        "sparql": """\
SELECT DISTINCT ?indemnisation ?typeIndemnisation ?montant ?taux WHERE {
    ?indemnisation a ?typeIndemnisation .
    FILTER(contains(str(?typeIndemnisation), 'Indemnisation') || contains(str(?indemnisation), 'Indemnisation'))
    OPTIONAL { ?indemnisation as:montantIndemnisation ?montant }
    OPTIONAL { ?indemnisation as:tauxIndemnisation ?taux }
}
ORDER BY DESC(?montant)""",
    },
    # ── HABITATIONS ────────────────────────────────────────────────────────
    {
        "id": "LIST_HABITATIONS",
        "keywords": ["habitation", "habitations", "maison", "appartement", "villa", "studio", "logement", "bien"],
        "stems":    ["habitat", "maison", "appartement", "vill", "studi", "logem", "bien"],
        "description": "Liste toutes les habitations assurées",
        "sparql": """\
SELECT DISTINCT ?habitation ?typeHabitation ?adresse ?superficie ?valeur WHERE {
    ?habitation a ?typeHabitation .
    FILTER(
        contains(str(?typeHabitation), 'Maison') ||
        contains(str(?typeHabitation), 'Appartement') ||
        contains(str(?typeHabitation), 'Villa') ||
        contains(str(?typeHabitation), 'Studio') ||
        contains(str(?habitation), 'Maison') ||
        contains(str(?habitation), 'Appartement') ||
        contains(str(?habitation), 'Villa') ||
        contains(str(?habitation), 'Studio')
    )
    OPTIONAL { ?habitation as:adresseBien ?adresse }
    OPTIONAL { ?habitation as:superficie ?superficie }
    OPTIONAL { ?habitation as:valeurBien ?valeur }
}
ORDER BY ?typeHabitation""",
    },
    # ── GARANTIES ──────────────────────────────────────────────────────────
    {
        "id": "LIST_GARANTIES",
        "keywords": ["garantie", "garanties", "couverture", "couvrir", "couvre", "protege", "protection"],
        "stems":    ["garanti", "couvertur", "couvr", "protect", "protèg"],
        "description": "Liste toutes les garanties de l'ontologie",
        "sparql": """\
SELECT DISTINCT ?garantie ?typeGarantie ?plafond ?taux WHERE {
    ?garantie a ?typeGarantie .
    FILTER(contains(str(?typeGarantie), 'Garantie') || contains(str(?garantie), 'Garantie'))
    OPTIONAL { ?garantie as:plafondGarantie ?plafond }
    OPTIONAL { ?garantie as:tauxFranchise ?taux }
}
ORDER BY ?typeGarantie""",
    },
    # ── DECLARATIONS ───────────────────────────────────────────────────────
    {
        "id": "LIST_DECLARATIONS",
        "keywords": ["declaration", "déclaration", "declarations", "declarer", "declare", "signalement"],
        "stems":    ["declarat", "déclar", "signalem"],
        "description": "Liste toutes les déclarations de sinistre",
        "sparql": """\
SELECT DISTINCT ?declaration ?typeDeclaration ?dateDeclaration ?statut WHERE {
    ?declaration a ?typeDeclaration .
    FILTER(contains(str(?typeDeclaration), 'Declaration') || contains(str(?declaration), 'Declaration'))
    OPTIONAL { ?declaration as:dateDeclaration ?dateDeclaration }
    OPTIONAL { ?declaration as:statutDeclaration ?statut }
}
ORDER BY DESC(?dateDeclaration)""",
    },
]

# ── Fallback (toutes les personnes) ──────────────────────────────────────────
FALLBACK_SPARQL = """\
SELECT DISTINCT ?personne ?type ?nom ?prenom WHERE {
    ?personne a ?type .
    FILTER(?type != owl:NamedIndividual)
    FILTER(?type != owl:Class)
    FILTER(
        contains(str(?type), 'Personne') || contains(str(?type), 'Assure') ||
        contains(str(?type), 'Agent') || contains(str(?type), 'Expert') ||
        contains(str(?type), 'Beneficiaire')
    )
    OPTIONAL { ?personne as:nom ?nom }
    OPTIONAL { ?personne as:prenom ?prenom }
}
ORDER BY ?type ?nom
LIMIT 20"""


class NLPSPARQLTranslator:
    """
    Traducteur NLP → SPARQL en 3 étapes :
      1. NLTK  : tokenisation + stopwords français + stemming (SnowballStemmer)
      2. spaCy : NER (reconnaissance d'entités nommées)
      3. Matching d'intention → requête SPARQL ciblée
    """

    def __init__(self):
        # NLTK stopwords
        try:
            self._stop_words = set(stopwords.words("french"))
        except Exception:
            self._stop_words = {
                "le", "la", "les", "un", "une", "des", "du", "de", "d", "a",
                "au", "en", "pour", "que", "qui", "est", "sont", "dans", "sur",
                "avec", "par", "se", "ce", "il", "elle", "ils", "elles",
                "je", "tu", "nous", "vous", "me", "te", "lui", "y", "ou", "et",
                "mais", "donc", "car", "si", "ne", "pas", "plus", "bien", "tout",
                "tous", "ma", "mon", "mes", "sa", "son", "ses", "leur", "leurs",
            }
        self._stemmer = SnowballStemmer("french")

    # ── Étape 1 : NLTK ───────────────────────────────────────────────────────
    def _step1_nltk(self, question: str) -> Dict[str, Any]:
        """Tokenisation + stopwords + stemming via NLTK."""
        clean = question.lower()
        clean = re.sub(r"[?''!,;.:«»\-]", " ", clean)

        try:
            tokens = word_tokenize(clean, language="french")
        except Exception:
            tokens = clean.split()

        filtered = [w for w in tokens if w not in self._stop_words and len(w) > 1 and w.isalpha()]
        stems = [self._stemmer.stem(w) for w in filtered]

        return {
            "library": "NLTK (word_tokenize + SnowballStemmer fr)",
            "tokens": filtered,
            "stems": stems,
            "normalized": " ".join(filtered),
        }

    # ── Étape 2 : spaCy NER ──────────────────────────────────────────────────
    def _step2_spacy(self, question: str) -> Dict[str, Any]:
        """Reconnaissance d'entités nommées (NER) avec spaCy fr_core_news_sm."""
        if not SPACY_AVAILABLE or _nlp_model is None:
            return {
                "library": "spaCy (non disponible — fallback désactivé)",
                "available": False,
                "entities": [],
                "pos_tags": [],
                "detected_names": [],
                "detected_dates": [],
                "detected_amounts": [],
            }

        doc = _nlp_model(question)
        entities = [{"text": ent.text, "label": ent.label_} for ent in doc.ents]
        pos_tags = [{"token": t.text, "pos": t.pos_, "lemma": t.lemma_} for t in doc if not t.is_stop and not t.is_punct]

        return {
            "library": "spaCy fr_core_news_sm (NER + POS tagging)",
            "available": True,
            "entities": entities,
            "pos_tags": pos_tags[:10],
            "detected_names":   [e["text"] for e in entities if e["label"] in ("PER", "PERSON")],
            "detected_dates":   [e["text"] for e in entities if e["label"] in ("DATE", "TIME")],
            "detected_amounts": [e["text"] for e in entities if e["label"] in ("MONEY", "QUANTITY", "CARDINAL")],
            "noun_chunks": [chunk.text for chunk in doc.noun_chunks][:6],
        }

    # ── Étape 3 : Matching d'intention ───────────────────────────────────────
    def _step3_intent_match(self, tokens: List[str], stems: List[str]) -> Optional[Dict[str, Any]]:
        """Cherche la meilleure intention parmi INTENTS."""
        normalized = " ".join(tokens)
        stems_joined = " ".join(stems)

        best_intent = None
        best_score = 0

        for intent in INTENTS:
            score = 0
            # Correspondance sur les mots-clés bruts
            for kw in intent["keywords"]:
                if kw in normalized:
                    score += 2
            # Correspondance sur les stems
            for s in intent["stems"]:
                if s in stems_joined:
                    score += 1

            if score > best_score:
                best_score = score
                best_intent = intent

        if best_score == 0:
            return None
        return {**best_intent, "match_score": best_score}

    # ── Point d'entrée public ─────────────────────────────────────────────────
    def translate_to_sparql(self, question: str) -> Dict[str, Any]:
        """Pipeline complet : NLP → SPARQL → résultats."""
        t0 = time.time()

        # ── Étape 1 : NLTK
        step1 = self._step1_nltk(question)

        # ── Étape 2 : spaCy
        step2 = self._step2_spacy(question)

        # ── Étape 3 : Intent matching
        matched = self._step3_intent_match(step1["tokens"], step1["stems"])

        if matched:
            intent_id = matched["id"]
            description = matched["description"]
            sparql_query = matched["sparql"]
            match_score = matched["match_score"]
        else:
            intent_id = "FALLBACK_ALL_PERSONNES"
            description = "Aucune intention précise détectée — affichage général des personnes"
            sparql_query = FALLBACK_SPARQL
            match_score = 0

        # ── Exécution SPARQL
        results = ontology_service.execute_sparql(sparql_query)

        elapsed = round((time.time() - t0) * 1000, 1)

        return {
            "question": question,
            "intent": intent_id,
            "intent_description": description,
            "match_score": match_score,
            "sparql_query": sparql_query,
            "results": results["results"],
            "count": results["count"],
            "vars": results["vars"],
            "elapsed_ms": elapsed,
            # Détails pédagogiques du pipeline NLP
            "pipeline": {
                "step1_nltk": step1,
                "step2_spacy": step2,
                "step3_intent": {
                    "library": "Intent Matcher (correspondance mots-clés + stems)",
                    "matched_intent": intent_id,
                    "match_score": match_score,
                    "total_intents_available": len(INTENTS),
                },
            },
        }

    def get_available_intents(self) -> List[Dict[str, Any]]:
        """Retourne la liste des intentions disponibles (pour la doc)."""
        return [
            {
                "id": i["id"],
                "description": i["description"],
                "example_keywords": i["keywords"][:4],
            }
            for i in INTENTS
        ]


nlp_translator = NLPSPARQLTranslator()
