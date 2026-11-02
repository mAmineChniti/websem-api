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
import unicodedata
from typing import Any

# ── NLTK ─────────────────────────────────────────────────────────────────────
import nltk
from nltk.corpus import stopwords
from nltk.stem.snowball import SnowballStemmer
from nltk.tokenize import word_tokenize

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


def _fold(text: str) -> str:
    """Minuscules + suppression des accents (pour matching robuste)."""
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii").lower()


# ── Intentions et requêtes SPARQL ────────────────────────────────────────────
INTENTS: list[dict[str, Any]] = [
    # ── PERSONNES ──────────────────────────────────────────────────────────
    {
        "id": "LIST_ASSURES",
        "keywords": ["assure", "assures", "client", "clients", "souscripteur", "adherent"],
        "stems": ["assur", "client", "souscript", "adhér"],
        "description": "Liste tous les assurés de l'ontologie",
        "sparql": """\
SELECT DISTINCT ?assure ?nom ?prenom ?cin ?telephone ?adresse WHERE {
    ?assure a owl:NamedIndividual ;
            a ?type .
    FILTER(?type != owl:NamedIndividual && contains(str(?type), 'Assure'))
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
        "stems": ["agent", "conseil", "gestion", "commerci"],
        "description": "Liste tous les agents d'assurance",
        "sparql": """\
SELECT DISTINCT ?agent ?nom ?prenom ?telephone ?adresse WHERE {
    ?agent a owl:NamedIndividual ;
           a ?type .
    FILTER(?type != owl:NamedIndividual && contains(str(?type), 'Agent'))
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
        "stems": ["expert", "expert", "evaluat", "technici"],
        "description": "Liste tous les experts assignés aux sinistres",
        "sparql": """\
SELECT DISTINCT ?expert ?nom ?prenom ?telephone ?adresse WHERE {
    ?expert a owl:NamedIndividual ;
            a ?type .
    FILTER(?type != owl:NamedIndividual && contains(str(?type), 'Expert'))
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
        "stems": ["benefici", "ayant", "droit"],
        "description": "Liste tous les bénéficiaires",
        "sparql": """\
SELECT DISTINCT ?beneficiaire ?nom ?prenom ?telephone WHERE {
    ?beneficiaire a owl:NamedIndividual ;
                  a ?type .
    FILTER(?type != owl:NamedIndividual && contains(str(?type), 'Beneficiaire'))
    OPTIONAL { ?beneficiaire as:nom ?nom }
    OPTIONAL { ?beneficiaire as:prenom ?prenom }
    OPTIONAL { ?beneficiaire as:telephone ?telephone }
}
ORDER BY ?nom""",
    },
    {
        "id": "COUNT_PERSONNES",
        "keywords": ["combien", "nombre", "total", "count", "statistique"],
        "stems": ["combi", "nombr", "total", "statist"],
        "description": "Compte le nombre de personnes par rôle",
        "sparql": """\
SELECT ?type (COUNT(?personne) AS ?nb) WHERE {
    ?personne a owl:NamedIndividual ;
              a ?type .
    FILTER(?type != owl:NamedIndividual)
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
        "stems": ["propriét", "proprietair", "proprio"],
        "description": "Liste les contrats de type Propriétaire",
        "sparql": """\
SELECT DISTINCT ?contrat ?numeroContrat ?montantPrime ?assure ?dateDebut ?dateFin WHERE {
    ?contrat a owl:NamedIndividual ;
             a ?typeContrat .
    FILTER(?typeContrat != owl:NamedIndividual && contains(str(?typeContrat), 'ContratProprietaire'))
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
        "stems": ["locatair", "locat", "loyer"],
        "description": "Liste les contrats de type Locataire",
        "sparql": """\
SELECT DISTINCT ?contrat ?numeroContrat ?montantPrime ?assure ?dateDebut ?dateFin WHERE {
    ?contrat a owl:NamedIndividual ;
             a ?typeContrat .
    FILTER(?typeContrat != owl:NamedIndividual && contains(str(?typeContrat), 'ContratLocataire'))
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
        "keywords": [
            "contrat",
            "contrats",
            "police",
            "polices",
            "prime",
            "primes",
            "cotisation",
            "assurance",
        ],
        "stems": ["contrat", "polic", "prim", "cotis", "assuranc"],
        "description": "Liste tous les contrats d'assurance avec leurs primes",
        "sparql": """\
SELECT DISTINCT ?contrat ?typeContrat ?numeroContrat ?dateDebut ?dateFin
       ?montantPrime ?assure WHERE {
    ?contrat a owl:NamedIndividual ;
             a ?typeContrat .
    FILTER(?typeContrat != owl:NamedIndividual && contains(str(?typeContrat), 'Contrat'))
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
        "keywords": [
            "prime",
            "primes",
            "montant",
            "montants",
            "cout",
            "coût",
            "prix",
            "tarif",
            "cher",
            "moyen",
            "moyenne",
        ],
        "stems": ["prim", "mont", "cout", "prix", "tarif", "moy"],
        "description": "Statistiques sur les montants des primes par type de contrat",
        "sparql": """\
SELECT ?typeContrat
       (COUNT(?contrat) AS ?nbContrats)
       (MIN(?montantPrime) AS ?primeMin)
       (MAX(?montantPrime) AS ?primeMax)
WHERE {
    ?contrat a owl:NamedIndividual ;
             a ?typeContrat .
    FILTER(?typeContrat != owl:NamedIndividual && contains(str(?typeContrat), 'Contrat'))
    OPTIONAL { ?contrat as:montantPrime ?montantPrime }
}
GROUP BY ?typeContrat
ORDER BY ?typeContrat""",
    },
    # ── SINISTRES ──────────────────────────────────────────────────────────
    {
        "id": "LIST_SINISTRES",
        "keywords": [
            "sinistre",
            "sinistres",
            "accident",
            "dommage",
            "dommages",
            "incident",
            "evenement",
        ],
        "stems": ["sinistr", "accident", "dommag", "incid", "evénem"],
        "description": "Liste tous les sinistres déclarés",
        "sparql": """\
SELECT DISTINCT ?sinistre ?typeSinistre ?dateSinistre ?lieuSinistre ?description ?assure WHERE {
    ?sinistre a owl:NamedIndividual ;
              a ?typeSinistre .
    FILTER(?typeSinistre != owl:NamedIndividual && contains(str(?typeSinistre), 'Sinistre'))
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
        "stems": ["incendi", "brûl", "flamm"],
        "description": "Liste les sinistres d'incendie",
        "sparql": """\
SELECT DISTINCT ?sinistre ?dateSinistre ?lieuSinistre ?description ?assure WHERE {
    ?sinistre a owl:NamedIndividual ;
              a ?typeSinistre .
    FILTER(?typeSinistre != owl:NamedIndividual && contains(str(?typeSinistre), 'Incendie'))
    OPTIONAL { ?sinistre as:dateSinistre ?dateSinistre }
    OPTIONAL { ?sinistre as:lieuSinistre ?lieuSinistre }
    OPTIONAL { ?sinistre as:descriptionSinistre ?description }
    OPTIONAL { ?sinistre as:estDeclarePar ?assure }
}""",
    },
    {
        "id": "LIST_SINISTRES_VOL",
        "keywords": ["vol", "vols", "cambriolage", "voleur", "cambrioleur", "effraction"],
        "stems": ["vol", "cambriolog", "effract"],
        "description": "Liste les sinistres de vol",
        "sparql": """\
SELECT DISTINCT ?sinistre ?dateSinistre ?lieuSinistre ?description ?assure WHERE {
    ?sinistre a owl:NamedIndividual ;
              a ?typeSinistre .
    FILTER(?typeSinistre != owl:NamedIndividual && contains(str(?typeSinistre), 'Vol'))
    OPTIONAL { ?sinistre as:dateSinistre ?dateSinistre }
    OPTIONAL { ?sinistre as:lieuSinistre ?lieuSinistre }
    OPTIONAL { ?sinistre as:descriptionSinistre ?description }
    OPTIONAL { ?sinistre as:estDeclarePar ?assure }
}""",
    },
    # ── INDEMNISATIONS ─────────────────────────────────────────────────────
    {
        "id": "LIST_INDEMNISATIONS",
        "keywords": [
            "indemnisation",
            "indemnisations",
            "remboursement",
            "compensation",
            "indemnite",
            "indemnité",
        ],
        "stems": ["indemnisa", "rembours", "compensat", "indemnit"],
        "description": "Liste toutes les indemnisations",
        "sparql": """\
SELECT DISTINCT ?indemnisation ?typeIndemnisation ?montant ?taux WHERE {
    ?indemnisation a owl:NamedIndividual ;
                   a ?typeIndemnisation .
    FILTER(?typeIndemnisation != owl:NamedIndividual && contains(str(?typeIndemnisation), 'Indemnisation'))
    OPTIONAL { ?indemnisation as:montantIndemnisation ?montant }
    OPTIONAL { ?indemnisation as:tauxIndemnisation ?taux }
}
ORDER BY DESC(?montant)""",
    },
    # ── HABITATIONS ────────────────────────────────────────────────────────
    {
        "id": "LIST_HABITATIONS",
        "keywords": [
            "habitation",
            "habitations",
            "maison",
            "appartement",
            "villa",
            "studio",
            "logement",
            "bien",
        ],
        "stems": ["habitat", "maison", "appartement", "vill", "studi", "logem", "bien"],
        "description": "Liste toutes les habitations assurées",
        "sparql": """\
SELECT DISTINCT ?habitation ?typeHabitation ?adresse ?superficie ?valeur WHERE {
    ?habitation a owl:NamedIndividual ;
                a ?typeHabitation .
    FILTER(?typeHabitation != owl:NamedIndividual && (
        contains(str(?typeHabitation), 'Maison') ||
        contains(str(?typeHabitation), 'Appartement') ||
        contains(str(?typeHabitation), 'Villa') ||
        contains(str(?typeHabitation), 'Studio')
    ))
    OPTIONAL { ?habitation as:adresseBien ?adresse }
    OPTIONAL { ?habitation as:superficie ?superficie }
    OPTIONAL { ?habitation as:valeurBien ?valeur }
}
ORDER BY ?typeHabitation""",
    },
    # ── GARANTIES ──────────────────────────────────────────────────────────
    {
        "id": "LIST_GARANTIES",
        "keywords": [
            "garantie",
            "garanties",
            "couverture",
            "couvrir",
            "couvre",
            "protege",
            "protection",
        ],
        "stems": ["garanti", "couvertur", "couvr", "protect", "protèg"],
        "description": "Liste toutes les garanties de l'ontologie",
        "sparql": """\
SELECT DISTINCT ?garantie ?typeGarantie ?plafond ?taux WHERE {
    ?garantie a owl:NamedIndividual ;
              a ?typeGarantie .
    FILTER(?typeGarantie != owl:NamedIndividual && contains(str(?typeGarantie), 'Garantie'))
    OPTIONAL { ?garantie as:plafondGarantie ?plafond }
    OPTIONAL { ?garantie as:tauxFranchise ?taux }
}
ORDER BY ?typeGarantie""",
    },
    # ── DECLARATIONS ───────────────────────────────────────────────────────
    {
        "id": "LIST_DECLARATIONS",
        "keywords": [
            "declaration",
            "déclaration",
            "declarations",
            "declarer",
            "declare",
            "signalement",
        ],
        "stems": ["declarat", "déclar", "signalem"],
        "description": "Liste toutes les déclarations de sinistre",
        "sparql": """\
SELECT DISTINCT ?declaration ?typeDeclaration ?dateDeclaration ?statut WHERE {
    ?declaration a owl:NamedIndividual ;
                 a ?typeDeclaration .
    FILTER(?typeDeclaration != owl:NamedIndividual && contains(str(?typeDeclaration), 'Declaration'))
    OPTIONAL { ?declaration as:dateDeclaration ?dateDeclaration }
    OPTIONAL { ?declaration as:statutDeclaration ?statut }
}
ORDER BY DESC(?dateDeclaration)""",
    },
    # ── PERSONNES (générique) ──────────────────────────────────────────────
    {
        "id": "LIST_PERSONNES",
        "keywords": [
            "personne",
            "personnes",
            "individu",
            "individus",
            "tout le monde",
            "utilisateur",
            "utilisateurs",
        ],
        "stems": ["personn", "individ", "utilisat"],
        "description": "Liste toutes les personnes de l'ontologie",
        "sparql": """\
SELECT DISTINCT ?personne ?type ?nom ?prenom ?cin ?telephone ?adresse WHERE {
    ?personne a owl:NamedIndividual ;
              a ?type .
    FILTER(!isBlank(?personne) && ?type != owl:NamedIndividual)
    FILTER(
        contains(str(?type), 'Personne') || contains(str(?type), 'Assure') ||
        contains(str(?type), 'Agent') || contains(str(?type), 'Expert') ||
        contains(str(?type), 'Beneficiaire')
    )
    OPTIONAL { ?personne as:nom ?nom }
    OPTIONAL { ?personne as:prenom ?prenom }
    OPTIONAL { ?personne as:cin ?cin }
    OPTIONAL { ?personne as:telephone ?telephone }
    OPTIONAL { ?personne as:adresse ?adresse }
}
ORDER BY ?type ?nom""",
    },
    # ── ONTOLOGIE ──────────────────────────────────────────────────────────
    {
        "id": "LIST_CLASSES",
        "keywords": [
            "classe",
            "classes",
            "ontologie",
            "concept",
            "concepts",
            "schema",
            "structure",
        ],
        "stems": ["class", "ontolog", "concept", "schem", "structur"],
        "description": "Liste toutes les classes OWL de l'ontologie",
        "sparql": """\
SELECT DISTINCT ?classe ?superClasse WHERE {
    ?classe a owl:Class .
    FILTER(!isBlank(?classe))
    FILTER(STRSTARTS(STR(?classe), STR(as:)) || STRSTARTS(STR(?classe), STR(unt:)))
    OPTIONAL { ?classe rdfs:subClassOf ?superClasse . FILTER(!isBlank(?superClasse)) }
}
ORDER BY ?superClasse ?classe""",
    },
    {
        "id": "LIST_PROPRIETES",
        "keywords": [
            "propriete",
            "proprietes",
            "propriété",
            "relation",
            "relations",
            "attribut",
            "attributs",
        ],
        "stems": ["propriet", "relation", "attribut"],
        "description": "Liste toutes les propriétés (datatype + objet) de l'ontologie",
        "sparql": """\
SELECT DISTINCT ?propriete WHERE {
    { ?propriete a owl:DatatypeProperty } UNION { ?propriete a owl:ObjectProperty }
    FILTER(STRSTARTS(STR(?propriete), STR(as:)))
}
ORDER BY ?propriete""",
    },
    {
        "id": "LIST_INDIVIDUS",
        "keywords": ["individu", "individus", "instance", "instances", "tous les elements"],
        "stems": ["individ", "instanc"],
        "description": "Liste tous les individus de l'ontologie",
        "sparql": """\
SELECT DISTINCT ?individu ?type WHERE {
    ?individu a owl:NamedIndividual .
    ?individu a ?type .
    FILTER(?type != owl:NamedIndividual)
    FILTER(!isBlank(?individu))
}
ORDER BY ?type ?individu""",
    },
]

# ── Fallback (toutes les personnes) ──────────────────────────────────────────
FALLBACK_SPARQL = """\
SELECT DISTINCT ?personne ?type ?nom ?prenom WHERE {
    ?personne a owl:NamedIndividual ;
              a ?type .
    FILTER(?type != owl:NamedIndividual)
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
        # NLTK stopwords (normalisés sans accents)
        try:
            self._stop_words = {_fold(w) for w in stopwords.words("french")}
        except Exception:
            self._stop_words = {
                _fold(w)
                for w in [
                    "le",
                    "la",
                    "les",
                    "un",
                    "une",
                    "des",
                    "du",
                    "de",
                    "d",
                    "a",
                    "au",
                    "en",
                    "pour",
                    "que",
                    "qui",
                    "est",
                    "sont",
                    "dans",
                    "sur",
                    "avec",
                    "par",
                    "se",
                    "ce",
                    "il",
                    "elle",
                    "ils",
                    "elles",
                    "je",
                    "tu",
                    "nous",
                    "vous",
                    "me",
                    "te",
                    "lui",
                    "y",
                    "ou",
                    "et",
                    "mais",
                    "donc",
                    "car",
                    "si",
                    "ne",
                    "pas",
                    "plus",
                    "bien",
                    "tout",
                    "tous",
                    "ma",
                    "mon",
                    "mes",
                    "sa",
                    "son",
                    "ses",
                    "leur",
                    "leurs",
                ]
            }
        self._stemmer = SnowballStemmer("french")

    # ── Étape 1 : NLTK ───────────────────────────────────────────────────────
    def _step1_nltk(self, question: str) -> dict[str, Any]:
        """Tokenisation + stopwords + stemming via NLTK."""
        clean = _fold(question)
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
    def _step2_spacy(self, question: str) -> dict[str, Any]:
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
        pos_tags = [
            {"token": t.text, "pos": t.pos_, "lemma": t.lemma_}
            for t in doc
            if not t.is_stop and not t.is_punct
        ]

        return {
            "library": "spaCy fr_core_news_sm (NER + POS tagging)",
            "available": True,
            "entities": entities,
            "pos_tags": pos_tags[:10],
            "detected_names": [e["text"] for e in entities if e["label"] in ("PER", "PERSON")],
            "detected_dates": [e["text"] for e in entities if e["label"] in ("DATE", "TIME")],
            "detected_amounts": [
                e["text"] for e in entities if e["label"] in ("MONEY", "QUANTITY", "CARDINAL")
            ],
            "noun_chunks": [chunk.text for chunk in doc.noun_chunks][:6],
        }

    # ── Étape 3 : Matching d'intention ───────────────────────────────────────
    def _step3_intent_match(self, tokens: list[str], stems: list[str]) -> dict[str, Any] | None:
        """Cherche la meilleure intention parmi INTENTS (scoring pondéré par IDF)."""
        normalized = _fold(" ".join(tokens))
        stems_joined = _fold(" ".join(stems))

        total = len(INTENTS)

        # Document frequency des mots-clés et des stems
        kw_df: dict[str, int] = {}
        stem_df: dict[str, int] = {}
        for it in INTENTS:
            seen_kw = set()
            for kw in it["keywords"]:
                seen_kw.add(_fold(kw))
            for f in seen_kw:
                kw_df[f] = kw_df.get(f, 0) + 1
            seen_st = set()
            for st in it["stems"]:
                seen_st.add(_fold(st))
            for f in seen_st:
                stem_df[f] = stem_df.get(f, 0) + 1

        best_key = None
        best_intent = None
        best_score = 0

        for idx, intent in enumerate(INTENTS):
            matched_kw = []
            for kw in intent["keywords"]:
                fkw = _fold(kw)
                if " " in fkw:
                    if fkw in normalized:
                        matched_kw.append(fkw)
                else:
                    if fkw in tokens:
                        matched_kw.append(fkw)
            matched_st = [_fold(st) for st in intent["stems"] if _fold(st) in stems_joined]

            score = 0
            for kw in matched_kw:
                score += len(kw) + (total - kw_df.get(kw, 1))
            for st in matched_st:
                score += 1 + (total - stem_df.get(st, 1))

            # Boost des intentions spécifiques / agrégations selon les opérateurs présents
            if any(
                op in normalized.split() or op in normalized
                for op in (
                    "combien",
                    "nombre",
                    "total",
                    "count",
                    "montant",
                    "moyen",
                    "moyenne",
                    "min",
                    "max",
                )
            ):
                if "COUNT" in intent["id"] or "STATS" in intent["id"] or "PRIME" in intent["id"]:
                    score += 40
            type_boost = {
                "PROPRIETAIRE": "proprietaire",
                "LOCATAIRE": "locataire",
                "INCENDIE": "incendie",
                "VOL": "vol",
                "EXPERT": "expert",
                "AGENT": "agent",
                "BENEFICIAIRE": "beneficiaire",
                "GARANTIE": "garantie",
                "SINISTRE": "sinistre",
                "HABITATION": "habitation",
                "DECLARATION": "declaration",
                "INDEMNISATION": "indemnisation",
            }
            for key_id, word in type_boost.items():
                if key_id in intent["id"] and word in normalized:
                    score += 25
            # Boost supplémentaire pour le type mentionné en premier (sujet de la question)
            first_type_token = ""
            for tok in tokens:
                for _key_id, word in type_boost.items():
                    if tok.startswith(word) or tok.rstrip("sx") == word:
                        first_type_token = tok
                        break
                if first_type_token:
                    break
            for key_id, word in type_boost.items():
                if (
                    key_id in intent["id"]
                    and first_type_token
                    and (first_type_token.startswith(word) or first_type_token.rstrip("sx") == word)
                ):
                    score += 40

            max_kw_len = max((len(kw) for kw in matched_kw), default=0)
            key = (score, max_kw_len, len(matched_kw), -idx)

            if best_key is None or key > best_key:
                best_key = key
                best_intent = intent
                best_score = score

        if best_score == 0:
            return None
        return {**best_intent, "match_score": best_score}

    # ── Extraction de paramètres (slots) via spaCy + regex ───────────────────
    def _extract_slots(self, question: str, step2: dict[str, Any]) -> dict[str, Any]:
        return {"amount": None, "location": None, "person": None, "status": None}

    # ── Point d'entrée public ─────────────────────────────────────────────────
    def translate_to_sparql(self, question: str) -> dict[str, Any]:
        """Pipeline complet : NLP → SPARQL → résultats."""
        t0 = time.time()

        # ── Étape 1 : NLTK
        step1 = self._step1_nltk(question)

        # ── Étape 2 : spaCy
        step2 = self._step2_spacy(question)

        # ── Étape 3 : Intent matching (enrichi par les lemmes spaCy)
        match_tokens = list(step1["tokens"])
        if step2.get("available"):
            for pt in step2.get("pos_tags", []):
                lemma = _fold(pt.get("lemma", ""))
                if lemma and lemma.isalpha() and len(lemma) > 1 and lemma not in match_tokens:
                    match_tokens.append(lemma)
        matched = self._step3_intent_match(match_tokens, step1["stems"])

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

    def get_available_intents(self) -> list[dict[str, Any]]:
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
