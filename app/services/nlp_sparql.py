import re
from typing import Any, Dict, List, Tuple
import nltk
from nltk.tokenize import word_tokenize
from nltk.corpus import stopwords

from app.services.ontology_service import ontology_service, DEFAULT_PREFIXES

class NLPSPARQLTranslator:
    """
    Module de Traitement du Langage Naturel (NLP/TALN)
    Traduit les requetes en francais en requetes SPARQL conformes a l'ontologie d'assurance habitation.
    Utilise NLTK pour la tokenisation, le filtrage des mots vides (stopwords),
    et l'extraction d'entites / intentions pour construire les patrons SPARQL.
    """
    def __init__(self):
        try:
            self.stop_words = set(stopwords.words('french'))
        except Exception:
            self.stop_words = {"le", "la", "les", "un", "une", "des", "du", "de", "d", "a", "au", "en", "pour", "que", "qui"}

    def preprocess(self, question: str) -> List[str]:
        # Nettoyage et tokenisation NLTK
        clean_text = question.lower()
        clean_text = re.sub(r"[?'’!,;.]", " ", clean_text)
        tokens = word_tokenize(clean_text, language='french')
        filtered = [w for w in tokens if w not in self.stop_words and len(w) > 1]
        return filtered

    def translate_to_sparql(self, question: str) -> Dict[str, Any]:
        tokens = self.preprocess(question)
        normalized = " ".join(tokens)
        q_lower = question.lower()

        intent = "UNKNOWN"
        sparql_query = ""
        explanation = []

        explanation.append(f"1. Tokenisation & filtrage NLTK : tokens = {tokens}")

        # Intent 1 : Lister tous les sinistres ou filtrer par type
        if any(w in normalized for w in ["sinistre", "sinistres", "degat", "incendie", "vol", "bris", "catastrophe"]):
            if "incendie" in normalized:
                intent = "LIST_SINISTRES_INCENDIE"
                explanation.append("2. Intention detectee : Recherche des sinistres de type Incendie")
                sparql_query = """SELECT ?sinistre ?date ?description ?assure ?expert WHERE {
    ?sinistre a ?type .
    FILTER(contains(str(?type), 'Incendie'))
    OPTIONAL { ?sinistre as:dateSinistre ?date }
    OPTIONAL { ?sinistre as:descriptionSinistre ?description }
    OPTIONAL { ?sinistre as:estDeclarePar ?assure }
    OPTIONAL { ?sinistre as:expertisePar ?expert }
}"""
            elif any(w in normalized for w in ["vol", "cambriolage"]):
                intent = "LIST_SINISTRES_VOL"
                explanation.append("2. Intention detectee : Recherche des sinistres de type Vol & Vandalisme")
                sparql_query = """SELECT ?sinistre ?date ?description ?assure WHERE {
    ?sinistre a ?type .
    FILTER(contains(str(?type), 'Vol'))
    OPTIONAL { ?sinistre as:dateSinistre ?date }
    OPTIONAL { ?sinistre as:descriptionSinistre ?description }
    OPTIONAL { ?sinistre as:estDeclarePar ?assure }
}"""
            elif any(w in normalized for w in ["eau", "eaux", "inondation", "fuite"]):
                intent = "LIST_SINISTRES_EAUX"
                explanation.append("2. Intention detectee : Recherche des sinistres de type Degat des Eaux")
                sparql_query = """SELECT ?sinistre ?date ?description ?assure WHERE {
    ?sinistre a ?type .
    FILTER(contains(str(?type), 'DegatDesEaux') || contains(str(?type), 'Catastrophe'))
    OPTIONAL { ?sinistre as:dateSinistre ?date }
    OPTIONAL { ?sinistre as:descriptionSinistre ?description }
    OPTIONAL { ?sinistre as:estDeclarePar ?assure }
}"""
            else:
                intent = "LIST_ALL_SINISTRES"
                explanation.append("2. Intention detectee : Liste globale de tous les sinistres avec leurs details")
                sparql_query = """SELECT ?sinistre ?typeSinistre ?date ?lieu ?description ?assure WHERE {
    ?sinistre a ?typeSinistre .
    FILTER(contains(str(?typeSinistre), 'Sinistre') && ?typeSinistre != owl:NamedIndividual)
    OPTIONAL { ?sinistre as:dateSinistre ?date }
    OPTIONAL { ?sinistre as:lieuSinistre ?lieu }
    OPTIONAL { ?sinistre as:descriptionSinistre ?description }
    OPTIONAL { ?sinistre as:estDeclarePar ?assure }
}"""

        # Intent 2 : Indemnisations et montants
        elif any(w in normalized for w in ["indemnisation", "indemnisations", "remboursement", "montant", "paye", "verse"]):
            intent = "GET_INDEMNISATIONS"
            explanation.append("2. Intention detectee : Consultation des montants d'indemnisation verses pour les sinistres")
            sparql_query = """SELECT ?sinistre ?indemnisation ?montantIndemnise ?tauxIndemnisation WHERE {
    ?sinistre as:donneLieuA ?indemnisation .
    OPTIONAL { ?indemnisation as:montantIndemnise ?montantIndemnise }
    OPTIONAL { ?indemnisation as:tauxIndemnisation ?tauxIndemnisation }
}"""

        # Intent 3 : Assures et personnes
        elif any(w in normalized for w in ["assure", "assures", "client", "clients", "personne", "souscripteur"]):
            intent = "LIST_ASSURES"
            explanation.append("2. Intention detectee : Liste des personnes assurees et coordonnees")
            sparql_query = """SELECT ?assure ?nom ?prenom ?cin ?telephone ?adresse WHERE {
    ?assure a ?type .
    FILTER(contains(str(?type), 'Assure') || contains(str(?assure), 'Assure'))
    OPTIONAL { ?assure as:nom ?nom }
    OPTIONAL { ?assure as:prenom ?prenom }
    OPTIONAL { ?assure as:cin ?cin }
    OPTIONAL { ?assure as:telephone ?telephone }
    OPTIONAL { ?assure as:adresse ?adresse }
}"""

        # Intent 4 : Contrats et formules
        elif any(w in normalized for w in ["contrat", "contrats", "police", "prime", "prix", "cotisation"]):
            intent = "LIST_CONTRATS"
            explanation.append("2. Intention detectee : Consultation des contrats d'assurance habitation")
            sparql_query = """SELECT ?contrat ?typeContrat ?numero ?prime ?assure WHERE {
    ?contrat a ?typeContrat .
    FILTER(contains(str(?typeContrat), 'Contrat'))
    OPTIONAL { ?contrat as:numeroContrat ?numero }
    OPTIONAL { ?contrat as:montantPrime ?prime }
    OPTIONAL { ?contrat as:aPourAssure ?assure }
}"""

        # Intent 5 : Garanties
        elif any(w in normalized for w in ["garantie", "garanties", "couverture", "plafond", "franchise"]):
            intent = "LIST_GARANTIES"
            explanation.append("2. Intention detectee : Consultation des garanties et plafonds")
            sparql_query = """SELECT ?garantie ?typeGarantie ?plafond ?franchise WHERE {
    ?garantie a ?typeGarantie .
    FILTER(contains(str(?typeGarantie), 'Garantie'))
    OPTIONAL { ?garantie as:plafondGarantie ?plafond }
    OPTIONAL { ?garantie as:tauxFranchise ?franchise }
}"""

        # Intent 6 : Experts
        elif any(w in normalized for w in ["expert", "experts", "expertise", "rapport"]):
            intent = "LIST_EXPERTS"
            explanation.append("2. Intention detectee : Identification des experts et dossiers expertises")
            sparql_query = """SELECT ?expert ?sinistre ?dateSinistre WHERE {
    ?sinistre as:expertisePar ?expert .
    OPTIONAL { ?sinistre as:dateSinistre ?dateSinistre }
}"""

        # Intent 7 : Habitations / Biens
        elif any(w in normalized for w in ["habitation", "habitations", "maison", "appartement", "bien", "logement"]):
            intent = "LIST_HABITATIONS"
            explanation.append("2. Intention detectee : Consultation des logements et habitations assures")
            sparql_query = """SELECT ?habitation ?type ?adresseBien ?superficie ?valeurBien WHERE {
    ?habitation a ?type .
    FILTER(?type != owl:NamedIndividual && (contains(str(?type), 'Maison') || contains(str(?type), 'Appartement') || contains(str(?type), 'habitation') || contains(str(?habitation), 'Maison')))
    OPTIONAL { ?habitation as:adresseBien ?adresseBien }
    OPTIONAL { ?habitation as:superficie ?superficie }
    OPTIONAL { ?habitation as:valeurBien ?valeurBien }
}"""

        # Fallback query
        else:
            intent = "GENERAL_SEARCH"
            explanation.append("2. Intention generale : Recherche globale des entites et relations dans l'ontologie")
            sparql_query = """SELECT ?individu ?type WHERE {
    ?individu a ?type .
    FILTER(?type != owl:Class && ?type != owl:NamedIndividual && ?type != owl:ObjectProperty && ?type != owl:DatatypeProperty)
} LIMIT 15"""

        explanation.append("3. Generation de la requete SPARQL correspondante avec prefixes ontologie.")
        explanation.append("4. Execution directe sur le graphe RDFlib.")

        # Execute query
        results = ontology_service.execute_sparql(sparql_query)

        return {
            "question": question,
            "tokens": tokens,
            "intent": intent,
            "sparql_query": sparql_query,
            "explanation": explanation,
            "results": results["results"],
            "count": results["count"],
            "vars": results["vars"]
        }

nlp_translator = NLPSPARQLTranslator()
