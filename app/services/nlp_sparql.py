import re
from typing import Any, Dict, List
import nltk
from nltk.tokenize import word_tokenize
from nltk.corpus import stopwords
from app.services.ontology_service import ontology_service

class NLPSPARQLTranslator:
    """
    Module TALN (NLP) specialise sur le module de HIBA : Personne & Contrat.
    Prend une question en francais et la traduit en requete SPARQL valide.
    """
    def __init__(self):
        try:
            self.stop_words = set(stopwords.words('french'))
        except Exception:
            self.stop_words = {"le", "la", "les", "un", "une", "des", "du", "de", "d", "a", "au", "en", "pour", "que", "qui"}

    def preprocess(self, question: str) -> List[str]:
        clean_text = question.lower()
        clean_text = re.sub(r"[?'’!,;.]", " ", clean_text)
        tokens = word_tokenize(clean_text, language='french')
        filtered = [w for w in tokens if w not in self.stop_words and len(w) > 1]
        return filtered

    def translate_to_sparql(self, question: str) -> Dict[str, Any]:
        tokens = self.preprocess(question)
        normalized = " ".join(tokens)

        intent = "UNKNOWN"
        sparql_query = ""
        explanation = []

        explanation.append(f"1. Tokenisation & filtrage NLTK : tokens = {tokens}")

        # Intent 1 : Lister les assures
        if any(w in normalized for w in ["assure", "assures", "client", "clients"]):
            intent = "LIST_ASSURES"
            explanation.append("2. Intention : Recherche des personnes assurees (Classe Assure)")
            sparql_query = """SELECT DISTINCT ?assure ?nom ?prenom ?cin ?telephone ?adresse WHERE {
    ?assure a ?type .
    FILTER(contains(str(?type), 'Assure') || contains(str(?assure), 'Assure'))
    OPTIONAL { ?assure as:nom ?nom }
    OPTIONAL { ?assure as:prenom ?prenom }
    OPTIONAL { ?assure as:cin ?cin }
    OPTIONAL { ?assure as:telephone ?telephone }
    OPTIONAL { ?assure as:adresse ?adresse }
}"""

        # Intent 2 : Lister les agents
        elif any(w in normalized for w in ["agent", "agents", "conseiller", "gestionnaire"]):
            intent = "LIST_AGENTS"
            explanation.append("2. Intention : Recherche des agents d'assurance (Classe Agent)")
            sparql_query = """SELECT DISTINCT ?agent ?nom ?prenom ?telephone WHERE {
    ?agent a ?type .
    FILTER(contains(str(?type), 'Agent') || contains(str(?agent), 'Agent'))
    OPTIONAL { ?agent as:nom ?nom }
    OPTIONAL { ?agent as:prenom ?prenom }
    OPTIONAL { ?agent as:telephone ?telephone }
}"""

        # Intent 3 : Lister les experts
        elif any(w in normalized for w in ["expert", "experts", "expertise"]):
            intent = "LIST_EXPERTS"
            explanation.append("2. Intention : Recherche des experts d'assurance (Classe Expert)")
            sparql_query = """SELECT DISTINCT ?expert ?nom ?prenom ?telephone ?adresse WHERE {
    ?expert a ?type .
    FILTER(contains(str(?type), 'Expert') || contains(str(?expert), 'Expert'))
    OPTIONAL { ?expert as:nom ?nom }
    OPTIONAL { ?expert as:prenom ?prenom }
    OPTIONAL { ?expert as:telephone ?telephone }
    OPTIONAL { ?expert as:adresse ?adresse }
}"""

        # Intent 4 : Contrats par sous-classe (Proprietaire, Locataire, Copropriete)
        elif any(w in normalized for w in ["proprietaire", "proprietaires"]):
            intent = "LIST_CONTRATS_PROPRIETAIRE"
            explanation.append("2. Intention : Filtrage des contrats sous-classe ContratProprietaire")
            sparql_query = """SELECT DISTINCT ?contrat ?numeroContrat ?montantPrime ?assure WHERE {
    ?contrat a ?typeContrat .
    FILTER(contains(str(?typeContrat), 'ContratProprietaire'))
    OPTIONAL { ?contrat as:numeroContrat ?numeroContrat }
    OPTIONAL { ?contrat as:montantPrime ?montantPrime }
    OPTIONAL { ?contrat as:aPourAssure ?assure }
}"""

        elif any(w in normalized for w in ["locataire", "locataires"]):
            intent = "LIST_CONTRATS_LOCATAIRE"
            explanation.append("2. Intention : Filtrage des contrats sous-classe ContratLocataire")
            sparql_query = """SELECT DISTINCT ?contrat ?numeroContrat ?montantPrime ?assure WHERE {
    ?contrat a ?typeContrat .
    FILTER(contains(str(?typeContrat), 'ContratLocataire'))
    OPTIONAL { ?contrat as:numeroContrat ?numeroContrat }
    OPTIONAL { ?contrat as:montantPrime ?montantPrime }
    OPTIONAL { ?contrat as:aPourAssure ?assure }
}"""

        # Intent 5 : Tous les contrats ou montant prime
        elif any(w in normalized for w in ["contrat", "contrats", "police", "prime", "prix", "cotisation"]):
            intent = "LIST_ALL_CONTRATS"
            explanation.append("2. Intention : Liste globale des contrats d'assurance et montants des primes")
            sparql_query = """SELECT DISTINCT ?contrat ?typeContrat ?numeroContrat ?dateDebut ?dateFin ?montantPrime ?assure WHERE {
    ?contrat a ?typeContrat .
    FILTER(contains(str(?typeContrat), 'Contrat') || contains(str(?contrat), 'Contrat'))
    OPTIONAL { ?contrat as:numeroContrat ?numeroContrat }
    OPTIONAL { ?contrat as:dateDebut ?dateDebut }
    OPTIONAL { ?contrat as:dateFin ?dateFin }
    OPTIONAL { ?contrat as:montantPrime ?montantPrime }
    OPTIONAL { ?contrat as:aPourAssure ?assure }
}"""

        # Fallback : Toutes les personnes de l'ontologie
        else:
            intent = "LIST_ALL_PERSONNES"
            explanation.append("2. Intention générale : Liste de toutes les personnes et leurs rôles dans l'ontologie")
            sparql_query = """SELECT DISTINCT ?personne ?type ?nom ?prenom WHERE {
    ?personne a ?type .
    FILTER(?type != owl:NamedIndividual && ?type != owl:Class &&
           (contains(str(?type), 'Personne') || contains(str(?type), 'Assure') || 
            contains(str(?type), 'Agent') || contains(str(?type), 'Expert')))
    OPTIONAL { ?personne as:nom ?nom }
    OPTIONAL { ?personne as:prenom ?prenom }
} LIMIT 15"""

        explanation.append("3. Génération de la requête SPARQL ciblée sur le module Personne & Contrat.")
        explanation.append("4. Exécution directe sur le graphe RDF.")

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
