"""
Module NLP/TALN — Traducteur Question Naturelle → Requête SPARQL
================================================================
Pipeline en 4 étapes :
  1. NLTK  : tokenisation, suppression des stopwords, stemming (SnowballStemmer)
  2. spaCy : reconnaissance d'entités (NER) — noms, dates, montants
  3. Intent Matcher : correspondance d'intention étendue → génération de requête SPARQL
  4. Slots : extraction de paramètres (montant, lieu, personne, statut, date) → FILTER SPARQL

Bibliothèques utilisées : NLTK, spaCy (fr_core_news_sm), rdflib, re
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


def _sparql_literal(value: str) -> str:
    """Échappe une chaîne pour un littéral SPARQL entre guillemets."""
    return str(value).replace("\\", "\\\\").replace('"', '\\"')


def _inject_filters(query: str, filters: list[str]) -> str:
    """Insère des FILTER juste avant la fermeture du WHERE principal."""
    if not filters:
        return query
    idx = query.rfind("}")
    if idx == -1:
        return query
    block = "\n    " + "\n    ".join(filters)
    return query[:idx] + block + "\n" + query[idx:]


_NUMBER_RE = r"\d+(?:[ \u00a0]\d{3})*(?:[.,]\d+)?"


def _to_amount(raw: str) -> str | None:
    """Normalise un nombre français (« 1 200,50 ») en littéral numérique SPARQL."""
    cleaned = raw.replace(" ", "").replace("\u00a0", "").replace(",", ".")
    try:
        value = float(cleaned)
    except ValueError:
        return None
    if value.is_integer():
        return str(int(value))
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _has_var(query: str, var: str) -> bool:
    """Vérifie qu'une variable SPARQL est bien présente dans la requête."""
    return re.search(rf"\?{re.escape(var)}\b", query) is not None


_KNOWN_LOCATIONS: set[str] | None = None
_QUESTION_WORDS = {
    "combien",
    "liste",
    "quels",
    "quelles",
    "qui",
    "quel",
    "quelle",
    "est",
    "sont",
    "total",
    "nombre",
}
_PERSON_STOPWORDS = {
    "assure",
    "assures",
    "agent",
    "agents",
    "beneficiaire",
    "beneficiaires",
    "classe",
    "classes",
    "clause",
    "clauses",
    "contrat",
    "contrats",
    "declaration",
    "declarations",
    "document",
    "documents",
    "dommage",
    "dommages",
    "expert",
    "experts",
    "garantie",
    "garanties",
    "habitation",
    "habitations",
    "indemnisation",
    "indemnisations",
    "individu",
    "individus",
    "ontologie",
    "personne",
    "personnes",
    "propriete",
    "proprietes",
    "sinistre",
    "sinistres",
}


def _known_locations() -> set[str]:
    """Valeurs d'adresses/lieux réellement présentes dans l'ontologie."""
    global _KNOWN_LOCATIONS
    if _KNOWN_LOCATIONS is None:
        query = """\
SELECT DISTINCT ?v WHERE {
    { ?x as:adresse ?v }
    UNION { ?x as:lieuSinistre ?v }
    UNION { ?x as:adresseBien ?v }
}"""
        try:
            result = ontology_service.execute_sparql(query)
            _KNOWN_LOCATIONS = {_fold(str(row["v"])) for row in result["results"] if row.get("v")}
        except Exception:
            _KNOWN_LOCATIONS = set()
    return _KNOWN_LOCATIONS


def _is_location_mention(question: str, text: str) -> bool:
    """Valide une entité LOC spaCy (évite les faux positifs type « Combien »)."""
    folded = _fold(text)
    if not folded or folded in _QUESTION_WORDS:
        return False
    preceded_by_preposition = re.search(
        rf"(?:^|\s)(?:à|a|dans|sur|au|aux)\s+{re.escape(text)}",
        question,
        re.IGNORECASE,
    )
    if preceded_by_preposition:
        return True
    return any(folded in known or known in folded for known in _known_locations())


def _build_filters(intent: dict[str, Any], slots: dict[str, Any]) -> list[str]:
    """
    Construit les FILTER SPARQL correspondant aux slots extraits.
    Les variables sont choisies selon l'intention et vérifiées dans la requête
    pour ne jamais injecter un filtre sur une variable absente.
    """
    query = intent.get("sparql", "")
    intent_id = intent.get("id", "")
    filters: list[str] = []

    # ── Montant
    amount = slots.get("amount")
    if amount:
        op = slots.get("amount_op") or "="
        candidates: list[str] = []
        target = slots.get("amount_target")
        if target == "montantFranchise" and intent_id.startswith("LIST_GARANTIES"):
            candidates.append("tauxFranchise")
        if target == "montantFranchise" and "CONTRATS" in intent_id:
            candidates.append("franchise")
        if target:
            candidates.append(target)
        if "CONTRATS" in intent_id or intent_id.startswith("PRIME_STATS"):
            candidates.append("montantPrime")
        if intent_id.startswith("LIST_INDEMNISATIONS"):
            candidates.append("montantIndemnise")
        if intent_id.startswith("LIST_GARANTIES"):
            candidates.extend(["plafondGarantie", "tauxFranchise"])
        if intent_id.startswith("LIST_HABITATIONS"):
            candidates.append("valeurBien")
        if intent_id.startswith("LIST_SINISTRES"):
            candidates.append("montantIndemnise")
        if intent_id.startswith("LIST_DOMMAGES"):
            candidates.append("valeurBien")

        for var in dict.fromkeys(candidates):
            if _has_var(query, var):
                filters.append(f"FILTER(?{var} {op} {amount})")
                break

    # ── Lieu
    location = slots.get("location")
    if location:
        loc_candidates: list[str] = []
        if intent_id.startswith("LIST_SINISTRES"):
            loc_candidates = ["lieuSinistre"]
        elif intent_id.startswith("LIST_HABITATIONS"):
            loc_candidates = ["adresseBien"]
        elif intent_id.startswith(
            (
                "LIST_ASSURES",
                "LIST_AGENTS",
                "LIST_EXPERTS",
                "LIST_BENEFICIAIRES",
                "LIST_PERSONNES",
                "FALLBACK",
            )
        ):
            loc_candidates = ["adresse"]
        elif intent_id.startswith("LIST_CONTRATS") or "CONTRATS" in intent_id:
            loc_candidates = ["adresseAssure"]

        for var in loc_candidates:
            if _has_var(query, var):
                literal = _sparql_literal(location)
                filters.append(f'FILTER(CONTAINS(LCASE(STR(?{var})), LCASE("{literal}")))')
                break

    # ── Personne
    person = slots.get("person")
    if person:
        person_candidates: list[str] = []
        if intent_id.startswith("LIST_SINISTRES"):
            person_candidates = ["nomAssure", "prenomAssure"]
        elif (
            intent_id.startswith(
                (
                    "LIST_CONTRATS",
                    "LIST_ASSURES",
                    "LIST_AGENTS",
                    "LIST_EXPERTS",
                    "LIST_BENEFICIAIRES",
                    "LIST_PERSONNES",
                    "FALLBACK",
                )
            )
            or "CONTRATS" in intent_id
        ):
            person_candidates = ["nom", "prenom"]

        parts: list[str] = []
        for token in person.split():
            literal = _sparql_literal(token)
            for var in person_candidates:
                if _has_var(query, var):
                    parts.append(f'CONTAINS(LCASE(STR(?{var})), LCASE("{literal}"))')
        if parts:
            filters.append("FILTER(" + " || ".join(dict.fromkeys(parts)) + ")")

    # ── Statut de déclaration
    status = slots.get("status")
    if status:
        status_candidates: list[str] = []
        if intent_id.startswith(("LIST_SINISTRES", "LIST_DECLARATIONS")):
            status_candidates = ["statut"]
        needle = {
            "DeclarationAcceptee": "accept",
            "DeclarationRejetee": "rejet",
            "DeclarationEnCours": "cours",
        }.get(status, status)
        for var in status_candidates:
            if _has_var(query, var):
                filters.append(f'FILTER(CONTAINS(LCASE(STR(?{var})), "{needle}"))')
                break

    # ── Date
    date = slots.get("date")
    if date:
        date_candidates: list[str] = []
        if intent_id.startswith("LIST_SINISTRES"):
            date_candidates = ["dateSinistre"]
        elif intent_id.startswith("LIST_DECLARATIONS"):
            date_candidates = ["dateDeclaration"]
        elif intent_id.startswith("LIST_CONTRATS") or "CONTRATS" in intent_id:
            date_candidates = ["dateDebut", "dateFin"]
        elif intent_id.startswith("LIST_DOCUMENTS"):
            date_candidates = ["dateUpload"]

        for var in date_candidates:
            if _has_var(query, var):
                filters.append(f'FILTER(STRSTARTS(STR(?{var}), "{date}"))')
                break

    return filters


# ── Constructeurs de requêtes ancrés dans l'ontologie ────────────────────────
def _sinistre_select(type_name: str | None = None) -> str:
    type_filter = (
        f"?typeSinistre rdfs:subClassOf* unt:{type_name} ."
        if type_name
        else "?typeSinistre rdfs:subClassOf* unt:Sinistre ."
    )
    return f"""\
SELECT ?sinistre ?typeSinistre ?dateSinistre ?lieuSinistre ?description ?assure
       ?nomAssure ?prenomAssure ?statut ?montantIndemnise
       (GROUP_CONCAT(DISTINCT STRAFTER(STR(?garantie), "#"); separator=", ") AS ?garanties)
       (GROUP_CONCAT(DISTINCT STRAFTER(STR(?expert), "#"); separator=", ") AS ?experts)
       (GROUP_CONCAT(DISTINCT STRAFTER(STR(?dommage), "#"); separator=", ") AS ?dommages)
       (GROUP_CONCAT(DISTINCT STRAFTER(STR(?indemnisation), "#");
                     separator=", ") AS ?indemnisations)
WHERE {{
    ?sinistre a owl:NamedIndividual ;
              a ?typeSinistre .
    {type_filter}
    OPTIONAL {{ ?sinistre as:dateSinistre ?dateSinistre }}
    OPTIONAL {{ ?sinistre as:lieuSinistre ?lieuSinistre }}
    OPTIONAL {{ ?sinistre as:descriptionSinistre ?description }}
    OPTIONAL {{ ?sinistre as:estDeclarePar ?assure }}
    OPTIONAL {{ ?assure as:nom ?nomAssure }}
    OPTIONAL {{ ?assure as:prenom ?prenomAssure }}
    OPTIONAL {{ ?sinistre as:faitObjetDe ?declaration }}
    OPTIONAL {{ ?declaration as:statutDeclaration ?statut }}
    OPTIONAL {{ ?sinistre as:estCouvertPar ?garantie }}
    OPTIONAL {{ ?sinistre as:expertisePar ?expert }}
    OPTIONAL {{ ?sinistre as:provoqueDommage ?dommage }}
    OPTIONAL {{ ?sinistre as:donneLieuA ?indemnisation }}
    OPTIONAL {{ ?indemnisation as:montantIndemnise ?montantIndemnise }}
}}
GROUP BY ?sinistre ?typeSinistre ?dateSinistre ?lieuSinistre ?description ?assure
         ?nomAssure ?prenomAssure ?statut ?montantIndemnise
ORDER BY DESC(?dateSinistre)"""


def _garantie_select(type_name: str | None = None) -> str:
    type_filter = (
        f"?typeGarantie rdfs:subClassOf* unt:{type_name} ."
        if type_name
        else "?typeGarantie rdfs:subClassOf* unt:Garantie ."
    )
    return f"""\
SELECT ?garantie ?typeGarantie
       (?plafondGarantie AS ?plafond)
       (?tauxFranchise AS ?taux)
       ?texteClause
       (GROUP_CONCAT(DISTINCT STRAFTER(STR(?contrat), "#"); separator=", ") AS ?contrats)
       (GROUP_CONCAT(DISTINCT STRAFTER(STR(?sinistre), "#"); separator=", ") AS ?sinistres)
WHERE {{
    ?garantie a owl:NamedIndividual ;
              a ?typeGarantie .
    {type_filter}
    OPTIONAL {{ ?garantie as:plafondGarantie ?plafondGarantie }}
    OPTIONAL {{ ?garantie as:tauxFranchise ?tauxFranchise }}
    OPTIONAL {{ ?garantie as:aPourClause ?clause }}
    OPTIONAL {{ ?clause as:texteClause ?texteClause }}
    OPTIONAL {{ ?contrat as:couvre ?garantie }}
    OPTIONAL {{ ?sinistre as:estCouvertPar ?garantie }}
}}
GROUP BY ?garantie ?typeGarantie ?plafondGarantie ?tauxFranchise ?texteClause
ORDER BY ?typeGarantie"""


def _contrat_select(type_name: str | None = None) -> str:
    type_filter = (
        f"?typeContrat rdfs:subClassOf* unt:{type_name} ."
        if type_name
        else "?typeContrat rdfs:subClassOf* unt:Contrat ."
    )
    return f"""\
SELECT ?contrat ?typeContrat ?numeroContrat ?dateDebut ?dateFin ?montantPrime
       ?franchise ?assure ?nom ?prenom ?adresseAssure ?habitation ?garanties
       (GROUP_CONCAT(DISTINCT STRAFTER(STR(?garantieObjet), "#");
                     separator=", ") AS ?garantiesObjets)
       (GROUP_CONCAT(DISTINCT STRAFTER(STR(?beneficiaire), "#"); separator=", ") AS ?beneficiaires)
WHERE {{
    ?contrat a owl:NamedIndividual ;
             a ?typeContrat .
    {type_filter}
    OPTIONAL {{ ?contrat as:numeroContrat ?numeroContrat }}
    OPTIONAL {{ ?contrat as:montantPrime ?montantPrime }}
    OPTIONAL {{ ?contrat as:montantFranchise ?franchise }}
    OPTIONAL {{ ?contrat as:aPourAssure ?assure }}
    OPTIONAL {{ ?assure as:nom ?nom }}
    OPTIONAL {{ ?assure as:prenom ?prenom }}
    OPTIONAL {{ ?assure as:adresse ?adresseAssure }}
    OPTIONAL {{ ?contrat as:dateDebut ?dateDebut }}
    OPTIONAL {{ ?contrat as:dateFin ?dateFin }}
    OPTIONAL {{ ?contrat as:typeHabitation ?habitation }}
    OPTIONAL {{ ?contrat as:garanties ?garanties }}
    OPTIONAL {{ ?contrat as:couvre ?garantieObjet }}
    OPTIONAL {{ ?contrat as:aPourBeneficiaire ?beneficiaire }}
}}
GROUP BY ?contrat ?typeContrat ?numeroContrat ?dateDebut ?dateFin ?montantPrime
         ?franchise ?assure ?nom ?prenom ?adresseAssure ?habitation ?garanties
ORDER BY ?numeroContrat"""


# ── Intentions et requêtes SPARQL ────────────────────────────────────────────
INTENTS: list[dict[str, Any]] = [
    # ── PERSONNES ──────────────────────────────────────────────────────────
    {
        "id": "LIST_ASSURES",
        "priority": 20,
        "keywords": ["assure", "assures", "client", "clients", "souscripteur", "adherent"],
        "stems": ["assur", "client", "souscript", "adhér"],
        "description": "Liste tous les assurés de l'ontologie",
        "sparql": """\
SELECT DISTINCT ?assure ?type ?nom ?prenom ?cin ?telephone ?adresse WHERE {
    {
        ?assure a owl:NamedIndividual ;
                a ?type .
        ?type rdfs:subClassOf* unt:Assure .
    }
    UNION
    {
        ?assure as:souscritContrat ?contrat .
        FILTER NOT EXISTS { ?assure a ?t . ?t rdfs:subClassOf* unt:Personne }
        BIND(unt:Assure AS ?type)
    }
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
        "priority": 20,
        "keywords": ["agent", "agents", "conseiller", "gestionnaire", "commercial"],
        "stems": ["agent", "conseil", "gestion", "commerci"],
        "description": "Liste tous les agents d'assurance",
        "sparql": """\
SELECT DISTINCT ?agent ?nom ?prenom ?telephone ?adresse WHERE {
    ?agent a owl:NamedIndividual ;
           a ?type .
    ?type rdfs:subClassOf* unt:Agent .
    OPTIONAL { ?agent as:nom ?nom }
    OPTIONAL { ?agent as:prenom ?prenom }
    OPTIONAL { ?agent as:telephone ?telephone }
    OPTIONAL { ?agent as:adresse ?adresse }
}
ORDER BY ?nom""",
    },
    {
        "id": "LIST_EXPERTS",
        "priority": 20,
        "keywords": ["expert", "experts", "expertise", "evaluateur", "technicien"],
        "stems": ["expert", "expert", "evaluat", "technici"],
        "description": "Liste tous les experts assignés aux sinistres",
        "sparql": """\
SELECT DISTINCT ?expert ?nom ?prenom ?telephone ?adresse WHERE {
    ?expert a owl:NamedIndividual ;
            a ?type .
    ?type rdfs:subClassOf* unt:Expert .
    OPTIONAL { ?expert as:nom ?nom }
    OPTIONAL { ?expert as:prenom ?prenom }
    OPTIONAL { ?expert as:telephone ?telephone }
    OPTIONAL { ?expert as:adresse ?adresse }
}
ORDER BY ?nom""",
    },
    {
        "id": "LIST_BENEFICIAIRES",
        "priority": 20,
        "keywords": ["beneficiaire", "beneficiaires", "ayant", "droit", "ayantdroit"],
        "stems": ["benefici", "ayant", "droit"],
        "description": "Liste tous les bénéficiaires",
        "sparql": """\
SELECT DISTINCT ?beneficiaire ?nom ?prenom ?telephone WHERE {
    ?beneficiaire a owl:NamedIndividual ;
                  a ?type .
    ?type rdfs:subClassOf* unt:Beneficiaire .
    OPTIONAL { ?beneficiaire as:nom ?nom }
    OPTIONAL { ?beneficiaire as:prenom ?prenom }
    OPTIONAL { ?beneficiaire as:telephone ?telephone }
}
ORDER BY ?nom""",
    },
    {
        "id": "COUNT_PERSONNES",
        "priority": 20,
        "keywords": ["combien", "nombre", "total", "count", "statistique"],
        "stems": ["combi", "nombr", "total", "statist"],
        "description": "Compte le nombre de personnes par rôle",
        "sparql": """\
SELECT ?type (COUNT(DISTINCT ?personne) AS ?nb) WHERE {
    {
        ?personne a ?type .
        ?type rdfs:subClassOf* unt:Personne .
        FILTER(?type != unt:Personne)
    }
    UNION
    {
        ?personne as:souscritContrat ?contrat .
        FILTER NOT EXISTS { ?personne a ?t . ?t rdfs:subClassOf* unt:Personne }
        BIND(unt:Assure AS ?type)
    }
}
GROUP BY ?type
ORDER BY DESC(?nb)""",
    },
    # ── CONTRATS ───────────────────────────────────────────────────────────
    {
        "id": "LIST_CONTRATS_PROPRIETAIRE",
        "priority": 40,
        "keywords": ["proprietaire", "propriétaire", "propriétaires", "proprio"],
        "stems": ["propriét", "proprietair", "proprio"],
        "description": "Liste les contrats de type Propriétaire",
        "sparql": _contrat_select("ContratProprietaire"),
    },
    {
        "id": "LIST_CONTRATS_LOCATAIRE",
        "priority": 40,
        "keywords": ["locataire", "locataires", "location", "loyer", "loueur"],
        "stems": ["locatair", "locat", "loyer"],
        "description": "Liste les contrats de type Locataire",
        "sparql": _contrat_select("ContratLocataire"),
    },
    {
        "id": "LIST_CONTRATS_COPROPRIETE",
        "priority": 40,
        "keywords": ["copropriete", "copropriété", "coproprietaires", "syndic"],
        "stems": ["copropriet", "syndic"],
        "description": "Liste les contrats de copropriété",
        "sparql": _contrat_select("ContratCopropriete"),
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
        "sparql": _contrat_select(),
    },
    {
        "id": "PRIME_STATS",
        "priority": 30,
        "keywords": [
            "statistique",
            "statistiques",
            "moyenne",
            "moyennes",
            "repartition",
            "répartition",
            "analyse",
            "minimum",
            "maximum",
        ],
        "stems": ["statist", "moy", "repart", "analys"],
        "description": "Statistiques sur les montants des primes par type de contrat",
        "sparql": """\
SELECT ?typeContrat
       (COUNT(DISTINCT ?contrat) AS ?nbContrats)
       (MIN(?montantPrime) AS ?primeMin)
       (MAX(?montantPrime) AS ?primeMax)
       (AVG(?montantPrime) AS ?primeMoyenne)
WHERE {
    ?contrat a owl:NamedIndividual ;
             a ?typeContrat .
    ?typeContrat rdfs:subClassOf* unt:Contrat .
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
            "accidents",
            "incident",
            "incidents",
            "evenement",
            "événement",
        ],
        "stems": ["sinistr", "accident", "incid", "evénem"],
        "description": "Liste tous les sinistres déclarés",
        "sparql": _sinistre_select(),
    },
    {
        "id": "LIST_SINISTRES_INCENDIE",
        "priority": 50,
        "keywords": ["incendie", "incendies", "feu", "flammes", "brulure", "brûlure"],
        "stems": ["incendi", "feu", "flam", "brul"],
        "description": "Liste les sinistres d'incendie",
        "sparql": _sinistre_select("SinistreIncendie"),
    },
    {
        "id": "LIST_SINISTRES_VOL",
        "priority": 50,
        "keywords": ["vol", "vols", "cambriolage", "voleur", "cambrioleur", "effraction"],
        "stems": ["vol", "cambriol", "effract"],
        "description": "Liste les sinistres de vol",
        "sparql": _sinistre_select("SinistreVol"),
    },
    {
        "id": "LIST_SINISTRES_DEGAT_EAUX",
        "priority": 50,
        "keywords": [
            "degat des eaux",
            "dégât des eaux",
            "degats des eaux",
            "dégâts des eaux",
            "fuite",
            "inondation",
            "eau",
        ],
        "stems": ["degat", "fuite", "inond", "eau"],
        "description": "Liste les sinistres de dégât des eaux",
        "sparql": _sinistre_select("SinistreDegatDesEaux"),
    },
    {
        "id": "LIST_SINISTRES_BRIS_DE_GLACE",
        "priority": 50,
        "keywords": ["bris de glace", "vitre", "vitrage", "glace"],
        "stems": ["bris", "glace", "vitr"],
        "description": "Liste les sinistres de bris de glace",
        "sparql": _sinistre_select("SinistreBrisDeGlace"),
    },
    {
        "id": "LIST_SINISTRES_CATASTROPHE_NATURELLE",
        "priority": 50,
        "keywords": [
            "catastrophe naturelle",
            "catastrophes naturelles",
            "catastrophe",
            "seisme",
            "séisme",
            "tempete",
            "tempête",
        ],
        "stems": ["catastroph", "seism", "tempet"],
        "description": "Liste les sinistres de catastrophe naturelle",
        "sparql": _sinistre_select("SinistreCatastropheNaturelle"),
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
SELECT ?indemnisation ?typeIndemnisation
       (?montantIndemnise AS ?montant)
       (?tauxIndemnisation AS ?taux)
       (GROUP_CONCAT(DISTINCT STRAFTER(STR(?sinistre), "#"); separator=", ") AS ?sinistres)
WHERE {
    ?indemnisation a owl:NamedIndividual ;
                   a ?typeIndemnisation .
    ?typeIndemnisation rdfs:subClassOf* unt:Indemnisation .
    OPTIONAL { ?indemnisation as:montantIndemnise ?montantIndemnise }
    OPTIONAL { ?indemnisation as:tauxIndemnisation ?tauxIndemnisation }
    OPTIONAL { ?sinistre as:donneLieuA ?indemnisation }
}
GROUP BY ?indemnisation ?typeIndemnisation ?montantIndemnise ?tauxIndemnisation
ORDER BY DESC(?montantIndemnise)""",
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
SELECT DISTINCT ?habitation ?typeHabitation ?adresse ?superficie ?valeur ?contrat WHERE {
    ?habitation a owl:NamedIndividual ;
                a ?typeHabitation .
    ?typeHabitation rdfs:subClassOf* unt:habitation .
    OPTIONAL { ?habitation as:adresseBien ?adresse }
    OPTIONAL { ?habitation as:superficie ?superficie }
    OPTIONAL { ?habitation as:valeurBien ?valeur }
    OPTIONAL { ?contrat as:aPourBien ?habitation }
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
        "sparql": _garantie_select(),
    },
    {
        "id": "LIST_GARANTIES_INCENDIE",
        "priority": 50,
        "keywords": ["garantie incendie", "garanties incendie", "incendie", "feu"],
        "stems": ["garanti", "incendi", "feu"],
        "description": "Liste les garanties incendie",
        "sparql": _garantie_select("GarantieIncendie"),
    },
    {
        "id": "LIST_GARANTIES_VOL",
        "priority": 50,
        "keywords": ["garantie vol", "garanties vol", "vol", "vols"],
        "stems": ["garanti", "vol"],
        "description": "Liste les garanties vol",
        "sparql": _garantie_select("GarantieVol"),
    },
    {
        "id": "LIST_GARANTIES_DEGAT_EAUX",
        "priority": 50,
        "keywords": [
            "garantie degat des eaux",
            "garanties degats des eaux",
            "degat des eaux",
            "fuite",
        ],
        "stems": ["garanti", "degat", "fuite"],
        "description": "Liste les garanties dégât des eaux",
        "sparql": _garantie_select("GarantieDegatDesEaux"),
    },
    {
        "id": "LIST_GARANTIES_BRIS_DE_GLACE",
        "priority": 50,
        "keywords": ["garantie bris de glace", "bris de glace", "vitre"],
        "stems": ["garanti", "bris", "glace", "vitr"],
        "description": "Liste les garanties bris de glace",
        "sparql": _garantie_select("GarantieBrisDeGlace"),
    },
    {
        "id": "LIST_GARANTIES_CATASTROPHE_NATURELLE",
        "priority": 50,
        "keywords": ["garantie catastrophe naturelle", "catastrophe naturelle", "seisme"],
        "stems": ["garanti", "catastroph", "seism"],
        "description": "Liste les garanties catastrophe naturelle",
        "sparql": _garantie_select("GarantieCatastropheNaturelle"),
    },
    {
        "id": "LIST_GARANTIES_RESPONSABILITE_CIVILE",
        "priority": 50,
        "keywords": [
            "garantie responsabilite civile",
            "responsabilite civile",
            "responsabilité civile",
        ],
        "stems": ["garanti", "responsabil", "civile"],
        "description": "Liste les garanties responsabilité civile",
        "sparql": _garantie_select("GarantieResponsabiliteCivile"),
    },
    {
        "id": "LIST_CLAUSES",
        "priority": 30,
        "keywords": [
            "clause",
            "clauses",
            "condition",
            "conditions",
            "exclusion",
            "exclusions",
            "franchise",
        ],
        "stems": ["claus", "condit", "exclus", "franchis"],
        "description": "Liste les clauses des garanties",
        "sparql": """\
SELECT DISTINCT ?clause ?typeClause ?texteClause ?garantie WHERE {
    ?clause a owl:NamedIndividual ;
            a ?typeClause .
    ?typeClause rdfs:subClassOf* unt:Clause .
    OPTIONAL { ?clause as:texteClause ?texteClause }
    OPTIONAL { ?garantie as:aPourClause ?clause }
}
ORDER BY ?typeClause""",
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
SELECT DISTINCT ?declaration ?typeDeclaration ?dateDeclaration ?statut ?sinistre ?document WHERE {
    ?declaration a owl:NamedIndividual ;
                 a ?typeDeclaration .
    ?typeDeclaration rdfs:subClassOf* unt:Declaration .
    OPTIONAL { ?declaration as:dateDeclaration ?dateDeclaration }
    OPTIONAL { ?declaration as:statutDeclaration ?statut }
    OPTIONAL { ?sinistre as:faitObjetDe ?declaration }
    OPTIONAL { ?declaration as:estJustifiePar ?document }
}
ORDER BY DESC(?dateDeclaration)""",
    },
    # ── DOCUMENTS ──────────────────────────────────────────────────────────
    {
        "id": "LIST_DOCUMENTS",
        "priority": 30,
        "keywords": [
            "document",
            "documents",
            "fichier",
            "fichiers",
            "rapport",
            "rapports",
            "facture",
            "factures",
            "photo",
            "photos",
        ],
        "stems": ["document", "fich", "rapport", "factur", "photo"],
        "description": "Liste les documents liés aux déclarations",
        "sparql": """\
SELECT DISTINCT ?document ?typeDocument ?nomFichier ?dateUpload ?declaration ?sinistre WHERE {
    ?document a owl:NamedIndividual ;
              a ?typeDocument .
    ?typeDocument rdfs:subClassOf* unt:Document .
    OPTIONAL { ?document as:nomFichier ?nomFichier }
    OPTIONAL { ?document as:dateUpload ?dateUpload }
    OPTIONAL { ?declaration as:estJustifiePar ?document }
    OPTIONAL { ?sinistre as:faitObjetDe ?declaration }
}
ORDER BY ?document""",
    },
    # ── DOMMAGES ───────────────────────────────────────────────────────────
    {
        "id": "LIST_DOMMAGES",
        "priority": 30,
        "keywords": [
            "dommage",
            "dommages",
            "prejudice",
            "préjudice",
            "corporel",
            "materiel",
            "matériel",
            "immateriel",
            "immatériel",
        ],
        "stems": ["dommag", "prejud", "corpor", "materi", "immateri"],
        "description": "Liste les dommages liés aux sinistres",
        "sparql": """\
SELECT DISTINCT ?dommage ?typeDommage ?description ?niveauGravite ?valeurBien ?sinistre WHERE {
    ?dommage a owl:NamedIndividual ;
             a ?typeDommage .
    ?typeDommage rdfs:subClassOf* unt:Dommage .
    OPTIONAL { ?dommage rdfs:comment ?description }
    OPTIONAL { ?dommage as:niveauGravite ?niveauGravite }
    OPTIONAL { ?dommage as:valeurBien ?valeurBien }
    OPTIONAL { ?sinistre as:provoqueDommage ?dommage }
}
ORDER BY ?dommage""",
    },
    # ── PERSONNES (générique) ──────────────────────────────────────────────
    {
        "id": "LIST_PERSONNES",
        "keywords": [
            "personne",
            "personnes",
            "tout le monde",
            "utilisateur",
            "utilisateurs",
        ],
        "stems": ["personn", "utilisat"],
        "description": "Liste toutes les personnes de l'ontologie",
        "sparql": """\
SELECT DISTINCT ?personne ?type ?nom ?prenom ?cin ?telephone ?adresse WHERE {
    {
        ?personne a owl:NamedIndividual ;
                  a ?type .
        ?type rdfs:subClassOf* unt:Personne .
    }
    UNION
    {
        ?personne as:souscritContrat ?contrat .
        FILTER NOT EXISTS { ?personne a ?t . ?t rdfs:subClassOf* unt:Personne }
        BIND(unt:Assure AS ?type)
    }
    FILTER(!isBlank(?personne))
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
    {
        ?personne a owl:NamedIndividual ;
                  a ?type .
        ?type rdfs:subClassOf* unt:Personne .
    }
    UNION
    {
        ?personne as:souscritContrat ?contrat .
        FILTER NOT EXISTS { ?personne a ?t . ?t rdfs:subClassOf* unt:Personne }
        BIND(unt:Assure AS ?type)
    }
    FILTER(!isBlank(?personne))
    OPTIONAL { ?personne as:nom ?nom }
    OPTIONAL { ?personne as:prenom ?prenom }
}
ORDER BY ?type ?nom
LIMIT 20"""


class NLPSPARQLTranslator:
    """
    Traducteur NLP → SPARQL en 4 étapes :
      1. NLTK  : tokenisation + stopwords français + stemming (SnowballStemmer)
      2. spaCy : NER (reconnaissance d'entités nommées)
      3. Matching d'intention → requête SPARQL ciblée
      4. Extraction de slots → filtres SPARQL dynamiques
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
        """Cherche la meilleure intention parmi INTENTS (scoring mots-clés + stems)."""
        normalized = _fold(" ".join(tokens))
        padded = f" {normalized} "
        token_set = set(tokens)
        stem_set = set(stems)
        total = len(INTENTS)

        # Stems dérivés des mots-clés + stems déclarés, pour un matching exact.
        intent_stems: list[set[str]] = []
        for it in INTENTS:
            derived = {self._stemmer.stem(_fold(kw)) for kw in it["keywords"] if " " not in kw}
            derived.update(_fold(st) for st in it["stems"])
            intent_stems.append(derived)

        kw_df: dict[str, int] = {}
        stem_df: dict[str, int] = {}
        for it, stem_values in zip(INTENTS, intent_stems, strict=True):
            for kw in {_fold(k) for k in it["keywords"]}:
                kw_df[kw] = kw_df.get(kw, 0) + 1
            for st in stem_values:
                stem_df[st] = stem_df.get(st, 0) + 1

        type_boost: dict[str, tuple[str, ...]] = {
            "ASSURES": ("assure", "assures", "client", "clients"),
            "AGENTS": ("agent", "agents"),
            "EXPERTS": ("expert", "experts"),
            "BENEFICIAIRES": ("beneficiaire", "beneficiaires"),
            "CONTRATS": ("contrat", "contrats"),
            "PROPRIETAIRE": ("proprietaire", "proprietaires", "proprio"),
            "LOCATAIRE": ("locataire", "locataires"),
            "COPROPRIETE": ("copropriete", "coproprietaires", "syndic"),
            "SINISTRES": ("sinistre", "sinistres"),
            "INCENDIE": ("incendie", "incendies"),
            "VOL": ("vol", "vols"),
            "DEGAT": ("degat", "degats", "fuite", "inondation"),
            "BRIS": ("bris", "vitre", "vitrage"),
            "CATASTROPHE": ("catastrophe", "catastrophes", "seisme", "tempete"),
            "GARANTIES": ("garantie", "garanties"),
            "RESPONSABILITE": ("responsabilite", "responsabilite civile"),
            "HABITATIONS": ("habitation", "habitations"),
            "DECLARATIONS": ("declaration", "declarations"),
            "INDEMNISATIONS": ("indemnisation", "indemnisations"),
            "DOCUMENTS": ("document", "documents"),
            "DOMMAGES": ("dommage", "dommages"),
            "CLAUSES": ("clause", "clauses"),
        }
        aggregation_terms = {
            "combien",
            "nombre",
            "total",
            "count",
            "statistique",
            "statistiques",
            "moyen",
            "moyenne",
            "minimum",
            "maximum",
        }
        has_aggregation = bool(token_set & aggregation_terms)

        # Module explicitement nommé en premier dans la question : le sujet
        # (« garanties » vs « sinistres ») doit primer sur les mots communs
        # comme « dégât des eaux » ou « incendie ».
        first_module = None
        for tok in tokens:
            if tok.startswith(("garanti", "couvertur", "couvr")):
                first_module = "GARANTIE"
                break
            if tok.startswith(("sinistr", "accident", "incident")):
                first_module = "SINISTRE"
                break

        best_key = None
        best_intent = None
        best_score = 0
        best_matched_kw: list[str] = []
        best_matched_st: list[str] = []

        for idx, (intent, stem_values) in enumerate(zip(INTENTS, intent_stems, strict=True)):
            id_parts = set(intent["id"].split("_"))
            matched_kw = []
            seen_kw: set[str] = set()
            for kw in intent["keywords"]:
                fkw = _fold(kw)
                if fkw in seen_kw:
                    continue
                if " " in fkw:
                    # Les stopwords sont retirés des tokens : « dégât des eaux »
                    # devient « degat eaux » dans la question normalisée.
                    phrase = " ".join(
                        word
                        for word in re.split(r"\W+", fkw)
                        if word and word not in self._stop_words
                    )
                    if phrase and f" {phrase} " in padded:
                        matched_kw.append(fkw)
                        seen_kw.add(fkw)
                elif fkw in token_set:
                    matched_kw.append(fkw)
                    seen_kw.add(fkw)

            matched_st = sorted(stem_set & stem_values)

            score = 0
            for kw in matched_kw:
                score += len(kw) + (total - kw_df.get(kw, 1))
            for st in matched_st:
                score += 1 + (total - stem_df.get(st, 1))

            if has_aggregation and ({"COUNT", "STATS", "PRIME"} & id_parts):
                score += 40

            if first_module == "GARANTIE" and "GARANTI" in intent["id"]:
                score += 100
            elif first_module == "SINISTRE" and "SINISTRE" in intent["id"]:
                score += 100

            # Sous-type explicite (vol, incendie, dégât des eaux…) : renforce
            # l'intention spécialisée face à l'intention générique du module.
            subtype_terms = {
                "INCENDIE": ("incendie", "incendies", "feu", "flammes"),
                "VOL": ("vol", "vols", "cambriolage", "effraction"),
                "DEGAT": ("degat", "degats", "fuite", "inondation", "eau", "eaux"),
                "BRIS": ("bris", "vitre", "vitrage", "glace"),
                "CATASTROPHE": ("catastrophe", "catastrophes", "seisme", "tempete"),
                "RESPONSABILITE": ("responsabilite", "civile"),
            }
            for key_id, words in subtype_terms.items():
                if key_id in id_parts and any(word in token_set for word in words):
                    score += 80

            for key_id, words in type_boost.items():
                if key_id in id_parts and any(word in token_set for word in words):
                    score += 25

            # Boost du type mentionné en premier (sujet de la question).
            first_type_token = ""
            for tok in tokens:
                if any(
                    tok == word or tok.rstrip("sx") == word
                    for words in type_boost.values()
                    for word in words
                ):
                    first_type_token = tok
                    break
            if first_type_token:
                for key_id, words in type_boost.items():
                    if key_id in id_parts and any(
                        first_type_token == word or first_type_token.rstrip("sx") == word
                        for word in words
                    ):
                        score += 40
                        break

            score += int(intent.get("priority", 0))
            max_kw_len = max((len(kw) for kw in matched_kw), default=0)
            key = (score, int(intent.get("priority", 0)), max_kw_len, len(matched_kw), -idx)

            if best_key is None or key > best_key:
                best_key = key
                best_intent = intent
                best_score = score
                best_matched_kw = matched_kw
                best_matched_st = matched_st

        if best_score == 0:
            return None
        return {
            **best_intent,
            "match_score": best_score,
            "matched_keywords": best_matched_kw,
            "matched_stems": best_matched_st,
        }

    # ── Extraction de paramètres (slots) via spaCy + regex ───────────────────
    def _extract_slots(self, question: str, step2: dict[str, Any]) -> dict[str, Any]:
        """
        Extrait les paramètres implicites de la question :
        montants, lieux, personnes, statut de déclaration et dates.
        spaCy fournit les entités nommées ; des regex ciblées complètent les cas
        que le petit modèle français ne reconnaît pas (noms collés, montants…).
        """
        folded = _fold(question)

        # ── Montant + opérateur de comparaison
        amount_raw = None
        currency = re.search(
            rf"({_NUMBER_RE})\s*(?:dinars?|dt|tnd|euros?|eur|€)",
            folded,
        )
        if currency:
            amount_raw = currency.group(1)
        else:
            contextual = re.search(
                rf"(?:prime|montant|indemnisation|indemnise|plafond|franchise|"
                rf"valeur|depasse|superieur|inferieur|plus de|moins de)"
                rf"\D{{0,25}}({_NUMBER_RE})",
                folded,
            )
            if contextual:
                amount_raw = contextual.group(1)
            else:
                for candidate in re.finditer(_NUMBER_RE, folded):
                    raw = candidate.group(0)
                    digits = raw.replace(" ", "").replace("\u00a0", "")
                    if re.fullmatch(r"(?:19|20)\d{2}", digits):
                        continue
                    amount_raw = raw
                    break

        amount = _to_amount(amount_raw) if amount_raw else None

        amount_op = None
        if amount:
            if re.search(r"au moins|minimum|>=|≥", folded):
                amount_op = ">="
            elif re.search(r"au plus|maximum|<=|≤", folded):
                amount_op = "<="
            elif re.search(r"plus de|superieur|depasse|au-dessus|>", folded):
                amount_op = ">"
            elif re.search(r"moins de|inferieur|en dessous|<", folded):
                amount_op = "<"
            else:
                amount_op = "="

        amount_target = None
        if "franchise" in folded:
            amount_target = "montantFranchise"
        elif "plafond" in folded:
            amount_target = "plafondGarantie"
        elif "prime" in folded or "cotisation" in folded:
            amount_target = "montantPrime"
        elif "indemn" in folded:
            amount_target = "montantIndemnise"
        elif "valeur" in folded:
            amount_target = "valeurBien"
        elif "taux" in folded:
            amount_target = "tauxFranchise"

        # ── Lieu (NER spaCy en priorité, puis préposition + nom propre)
        location = None
        for entity in step2.get("entities", []):
            if entity.get("label") in ("LOC", "GPE", "FAC") and _is_location_mention(
                question, entity.get("text", "")
            ):
                location = entity["text"]
                break
        if not location:
            loc_match = re.search(
                r"(?:^|\s)(?:à|a|dans|sur|au|aux)\s+"
                r"([A-ZÀ-ÖØ-Ý][\wÀ-ÿ'’-]+(?:\s+[A-ZÀ-ÖØ-Ý][\wÀ-ÿ'’-]+)?)",
                question,
            )
            if loc_match:
                location = loc_match.group(1)

        # ── Personne (NER spaCy, puis indicateur explicite)
        person = None
        detected_names = step2.get("detected_names") or []
        for name in detected_names:
            if _fold(name) not in _PERSON_STOPWORDS and not _is_location_mention(question, name):
                person = name
                break
        if not person:
            for entity in step2.get("entities", []):
                if entity.get("label") not in ("PER", "PERSON", "MISC"):
                    continue
                candidate = entity.get("text", "")
                if _fold(candidate) not in _PERSON_STOPWORDS and not _is_location_mention(
                    question, candidate
                ):
                    person = candidate
                    break
        if not person:
            person_match = re.search(
                r"(?i:assure|assuré|assuree|assurée|client|nomme|nommé|"
                r"souscripteur|beneficiaire|bénéficiaire|monsieur|madame|mme|m\.|de|du|des)"
                r"\s+([A-ZÀ-ÖØ-Ý][\wÀ-ÿ'’-]+(?:\s+[A-ZÀ-ÖØ-Ý][\wÀ-ÿ'’-]+)?)",
                question,
            )
            if person_match:
                candidate = person_match.group(1)
                if _fold(candidate) not in _PERSON_STOPWORDS and not _is_location_mention(
                    question, candidate
                ):
                    person = candidate
        if person and location and _fold(person) == _fold(location):
            person = None

        # ── Statut de déclaration
        status = None
        if re.search(r"accept|valid|approuv", folded):
            status = "DeclarationAcceptee"
        elif re.search(r"rejet|refus", folded):
            status = "DeclarationRejetee"
        elif re.search(r"en cours|\bcours\b", folded):
            status = "DeclarationEnCours"

        # ── Date (ISO, jj/mm/aaaa, année seule, mois + année)
        date = None
        iso = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", question)
        if iso:
            date = iso.group(0)
        else:
            french_date = re.search(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})\b", question)
            if french_date:
                day, month, year = french_date.groups()
                if len(year) == 2:
                    year = f"20{year}"
                date = f"{year}-{month.zfill(2)}-{day.zfill(2)}"
            else:
                month_names = {
                    "janvier": "01",
                    "fevrier": "02",
                    "février": "02",
                    "mars": "03",
                    "avril": "04",
                    "mai": "05",
                    "juin": "06",
                    "juillet": "07",
                    "aout": "08",
                    "août": "08",
                    "septembre": "09",
                    "octobre": "10",
                    "novembre": "11",
                    "decembre": "12",
                    "décembre": "12",
                }
                month_match = re.search(
                    r"\b(" + "|".join(month_names) + r")\s+(\d{4})\b",
                    folded,
                )
                if month_match:
                    date = f"{month_match.group(2)}-{month_names[month_match.group(1)]}"
                else:
                    year_match = re.search(r"\b(?:19|20)\d{2}\b", question)
                    if year_match and (amount is None or year_match.group(0) != amount):
                        date = year_match.group(0)

        # Un nombre issu d'une date (ex. « 12/05/2024 ») n'est pas un montant.
        if amount and date:
            date_parts = {_to_amount(part) for part in re.split(r"[-/]", date)}
            if amount in date_parts:
                amount = None
                amount_op = None

        return {
            "amount": amount,
            "amount_op": amount_op,
            "amount_target": amount_target,
            "location": location,
            "person": person,
            "status": status,
            "date": date,
        }

    # ── Point d'entrée public ─────────────────────────────────────────────────
    def translate_to_sparql(self, question: str) -> dict[str, Any]:
        """Pipeline complet : NLP → SPARQL → résultats."""
        t0 = time.time()

        # ── Étape 1 : NLTK
        step1 = self._step1_nltk(question)

        # ── Étape 2 : spaCy
        step2 = self._step2_spacy(question)

        # ── Étape 2b : extraction des paramètres (slots)
        slots = self._extract_slots(question, step2)

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
            filters = _build_filters(matched, slots)
            sparql_query = _inject_filters(sparql_query, filters)
        else:
            intent_id = "FALLBACK_ALL_PERSONNES"
            description = "Aucune intention précise détectée — affichage général des personnes"
            sparql_query = FALLBACK_SPARQL
            match_score = 0
            filters = []

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
                    "matched_keywords": matched.get("matched_keywords", []) if matched else [],
                    "matched_stems": matched.get("matched_stems", []) if matched else [],
                    "total_intents_available": len(INTENTS),
                },
                "step4_slots": {
                    "library": "spaCy NER + regex (montants, lieux, personnes, dates)",
                    "slots": slots,
                    "applied_filters": filters,
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
