import os
from pathlib import Path
from typing import Any, Dict, List
import rdflib
from rdflib import Graph, Literal, Namespace, RDF, RDFS, OWL, XSD, URIRef

AS = Namespace("http://www.semanticweb.org/asus/ontologies/2026/8/Assuarnce_et_Gestion_des_Sinistres#")
UNT = Namespace("http://www.semanticweb.org/asus/ontologies/2026/8/untitled-ontology-5#")

DEFAULT_PREFIXES = """
PREFIX as: <http://www.semanticweb.org/asus/ontologies/2026/8/Assuarnce_et_Gestion_des_Sinistres#>
PREFIX unt: <http://www.semanticweb.org/asus/ontologies/2026/8/untitled-ontology-5#>
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX owl: <http://www.w3.org/2002/07/owl#>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
"""

class OntologyService:
    def __init__(self, rdf_path: str | None = None):
        if not rdf_path:
            base_dir = Path(__file__).resolve().parent.parent.parent
            rdf_path = str(base_dir / "assurance.rdf")
        self.rdf_path = rdf_path
        self.graph = Graph()
        self.load_graph()

    def load_graph(self):
        if os.path.exists(self.rdf_path):
            self.graph.parse(self.rdf_path, format="xml")
            print(f"[OntologyService] Ontologie chargee depuis {self.rdf_path} ({len(self.graph)} triplets).")
        else:
            raise FileNotFoundError(f"Fichier d'ontologie non trouve: {self.rdf_path}")

    def save_graph(self):
        self.graph.serialize(destination=self.rdf_path, format="xml")

    def execute_sparql(self, query: str) -> Dict[str, Any]:
        full_query = query
        if "PREFIX" not in query.upper():
            full_query = DEFAULT_PREFIXES + "\n" + query

        qres = self.graph.query(full_query)
        
        if hasattr(qres, 'type') and qres.type == 'ASK':
            return {"type": "ASK", "boolean": bool(qres)}

        vars_list = [str(v) for v in qres.vars] if hasattr(qres, 'vars') and qres.vars else []
        rows = []
        for row in qres:
            row_dict = {}
            for v in vars_list:
                val = row[rdflib.Variable(v)]
                if val is not None:
                    val_str = str(val)
                    clean_str = val_str.split('#')[-1] if '#' in val_str else val_str
                    row_dict[v] = clean_str
                else:
                    row_dict[v] = None
            rows.append(row_dict)

        return {
            "vars": vars_list,
            "count": len(rows),
            "results": rows,
            "query": query
        }

    # Module HIBA : PERSONNES (Agent, Assure, Beneficiaire, Expert)
    def get_personnes(self, role: str | None = None) -> List[Dict[str, Any]]:
        filter_clause = ""
        if role:
            filter_clause = f"FILTER(contains(str(?type), '{role}') || contains(str(?personne), '{role}'))"

        q = f"""
        SELECT DISTINCT ?personne ?type ?nom ?prenom ?cin ?telephone ?adresse WHERE {{
            ?personne a ?type .
            FILTER(?type != owl:NamedIndividual && ?type != owl:Class && !isBlank(?personne) &&
                   (contains(str(?type), 'Personne') || contains(str(?type), 'Assure') || 
                    contains(str(?type), 'Agent') || contains(str(?type), 'Expert') || 
                    contains(str(?type), 'Beneficiaire') ||
                    contains(str(?personne), 'Assure') || contains(str(?personne), 'Agent') ||
                    contains(str(?personne), 'Expert') || contains(str(?personne), 'Beneficiaire')))
            {filter_clause}
            OPTIONAL {{ ?personne as:nom ?nom }}
            OPTIONAL {{ ?personne as:prenom ?prenom }}
            OPTIONAL {{ ?personne as:cin ?cin }}
            OPTIONAL {{ ?personne as:telephone ?telephone }}
            OPTIONAL {{ ?personne as:adresse ?adresse }}
        }}
        """
        return self.execute_sparql(q)["results"]

    def add_personne(self, data: Dict[str, Any]) -> str:
        role = data.get("role", "Assure")
        p_id = data.get("id") or f"{role}_{len(self.get_personnes()) + 1}"
        p_uri = AS[p_id]
        role_uri = UNT[role] if hasattr(UNT, role) else AS[role]

        self.graph.add((p_uri, RDF.type, OWL.NamedIndividual))
        self.graph.add((p_uri, RDF.type, role_uri))

        if data.get("nom"):
            self.graph.add((p_uri, AS.nom, Literal(data["nom"], datatype=XSD.string)))
        if data.get("prenom"):
            self.graph.add((p_uri, AS.prenom, Literal(data["prenom"], datatype=XSD.string)))
        if data.get("cin"):
            self.graph.add((p_uri, AS.cin, Literal(data["cin"], datatype=XSD.string)))
        if data.get("telephone"):
            self.graph.add((p_uri, AS.telephone, Literal(data["telephone"], datatype=XSD.string)))
        if data.get("adresse"):
            self.graph.add((p_uri, AS.adresse, Literal(data["adresse"], datatype=XSD.string)))

        self.save_graph()
        return p_id

    # Module HIBA : CONTRATS (ContratProprietaire, ContratLocataire, ContratCopropriete)
    def get_contrats(self, type_filter: str | None = None) -> List[Dict[str, Any]]:
        filter_clause = ""
        if type_filter:
            filter_clause = f"FILTER(contains(str(?typeContrat), '{type_filter}'))"

        q = f"""
        SELECT DISTINCT ?contrat ?typeContrat ?numeroContrat ?dateDebut ?dateFin ?montantPrime ?assure WHERE {{
            ?contrat a ?typeContrat .
            FILTER(?typeContrat != owl:NamedIndividual && ?typeContrat != owl:Class && !isBlank(?contrat) &&
                   (contains(str(?typeContrat), 'Contrat') || contains(str(?contrat), 'Contrat')))
            {filter_clause}
            OPTIONAL {{ ?contrat as:numeroContrat ?numeroContrat }}
            OPTIONAL {{ ?contrat as:dateDebut ?dateDebut }}
            OPTIONAL {{ ?contrat as:dateFin ?dateFin }}
            OPTIONAL {{ ?contrat as:montantPrime ?montantPrime }}
            OPTIONAL {{ ?contrat as:aPourAssure ?assure }}
        }}
        """
        return self.execute_sparql(q)["results"]

    def add_contrat(self, data: Dict[str, Any]) -> str:
        c_id = data.get("id") or f"Contrat{len(self.get_contrats()) + 1}"
        c_uri = AS[c_id]
        c_type = data.get("type", "ContratProprietaire")
        type_uri = UNT[c_type] if hasattr(UNT, c_type) else AS[c_type]

        self.graph.add((c_uri, RDF.type, OWL.NamedIndividual))
        self.graph.add((c_uri, RDF.type, type_uri))

        if data.get("numeroContrat"):
            self.graph.add((c_uri, AS.numeroContrat, Literal(data["numeroContrat"], datatype=XSD.string)))
        if data.get("dateDebut"):
            self.graph.add((c_uri, AS.dateDebut, Literal(data["dateDebut"], datatype=XSD.dateTime)))
        if data.get("dateFin"):
            self.graph.add((c_uri, AS.dateFin, Literal(data["dateFin"], datatype=XSD.dateTime)))
        if data.get("montantPrime"):
            self.graph.add((c_uri, AS.montantPrime, Literal(float(data["montantPrime"]), datatype=XSD.float)))
        if data.get("assure"):
            assure_uri = AS[data["assure"]]
            self.graph.add((c_uri, AS.aPourAssure, assure_uri))
            # Relation inverse
            self.graph.add((assure_uri, AS.souscritContrat, c_uri))

        self.save_graph()
        return c_id

    def delete_contrat(self, contrat_id: str) -> bool:
        c_uri = AS[contrat_id]
        triples_to_remove = list(self.graph.triples((c_uri, None, None))) + list(self.graph.triples((None, None, c_uri)))
        for t in triples_to_remove:
            self.graph.remove(t)
        self.save_graph()
        return len(triples_to_remove) > 0

    def get_stats(self) -> Dict[str, Any]:
        personnes = self.get_personnes()
        contrats = self.get_contrats()
        return {
            "module": "Système d'Assurance Habitation (Personnes & Contrats)",
            "personnes_count": len(personnes),
            "contrats_count": len(contrats),
            "assures_count": len([p for p in personnes if 'Assure' in (p.get('type') or '') or 'Assure' in (p.get('personne') or '')]),
            "agents_count": len([p for p in personnes if 'Agent' in (p.get('type') or '') or 'Agent' in (p.get('personne') or '')]),
            "experts_count": len([p for p in personnes if 'Expert' in (p.get('type') or '') or 'Expert' in (p.get('personne') or '')]),
            "total_triples": len(self.graph),
            "ontology_uri": "http://www.semanticweb.org/asus/ontologies/2026/8/Assuarnce_et_Gestion_des_Sinistres"
        }

ontology_service = OntologyService()
