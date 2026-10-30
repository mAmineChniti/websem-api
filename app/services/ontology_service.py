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

    def get_stats(self) -> Dict[str, Any]:
        classes_q = """
        SELECT (COUNT(DISTINCT ?c) as ?count) WHERE {
            ?c a owl:Class .
            FILTER(!isBlank(?c))
        }
        """
        obj_props_q = """
        SELECT (COUNT(DISTINCT ?p) as ?count) WHERE {
            ?p a owl:ObjectProperty .
        }
        """
        data_props_q = """
        SELECT (COUNT(DISTINCT ?p) as ?count) WHERE {
            ?p a owl:DatatypeProperty .
        }
        """
        indivs_q = """
        SELECT (COUNT(DISTINCT ?i) as ?count) WHERE {
            ?i a ?t .
            FILTER(?t != owl:Class && ?t != owl:NamedIndividual && ?t != owl:ObjectProperty && ?t != owl:DatatypeProperty && ?t != owl:Ontology && !isBlank(?i))
        }
        """
        classes_res = list(self.graph.query(DEFAULT_PREFIXES + classes_q))
        obj_res = list(self.graph.query(DEFAULT_PREFIXES + obj_props_q))
        data_res = list(self.graph.query(DEFAULT_PREFIXES + data_props_q))
        indivs_res = list(self.graph.query(DEFAULT_PREFIXES + indivs_q))

        return {
            "triples_count": len(self.graph),
            "classes_count": int(classes_res[0][0]) if classes_res else 0,
            "object_properties_count": int(obj_res[0][0]) if obj_res else 0,
            "datatype_properties_count": int(data_res[0][0]) if data_res else 0,
            "individuals_count": int(indivs_res[0][0]) if indivs_res else 0,
            "ontology_uri": "http://www.semanticweb.org/asus/ontologies/2026/8/Assuarnce_et_Gestion_des_Sinistres"
        }

    def get_sinistres(self) -> List[Dict[str, Any]]:
        q = """
        SELECT DISTINCT ?sinistre ?typeSinistre ?date ?lieu ?description ?assure ?expert ?indemnisation ?montantIndemnise WHERE {
            ?sinistre a ?typeSinistre .
            FILTER(?typeSinistre != owl:NamedIndividual && 
                   ?typeSinistre != owl:Class && 
                   ?typeSinistre != owl:ObjectProperty && 
                   ?typeSinistre != owl:DatatypeProperty && 
                   ?typeSinistre != owl:FunctionalProperty && 
                   ?typeSinistre != owl:Ontology && 
                   !isBlank(?sinistre) &&
                   (contains(str(?sinistre), 'Sinistre') || contains(str(?typeSinistre), 'Sinistre')))
            OPTIONAL { ?sinistre as:dateSinistre ?date }
            OPTIONAL { ?sinistre as:lieuSinistre ?lieu }
            OPTIONAL { ?sinistre as:descriptionSinistre ?description }
            OPTIONAL { ?sinistre as:estDeclarePar ?assure }
            OPTIONAL { ?sinistre as:expertisePar ?expert }
            OPTIONAL { ?sinistre as:donneLieuA ?indemnisation .
                       OPTIONAL { ?indemnisation as:montantIndemnise ?montantIndemnise } }
        }
        """
        res = self.execute_sparql(q)
        return res["results"]

    def get_assures(self) -> List[Dict[str, Any]]:
        q = """
        SELECT DISTINCT ?assure ?nom ?prenom ?cin ?telephone ?adresse WHERE {
            ?assure a ?type .
            FILTER(?type != owl:NamedIndividual && ?type != owl:Class && !isBlank(?assure) && (contains(str(?type), 'Assure') || contains(str(?assure), 'Assure')))
            OPTIONAL { ?assure as:nom ?nom }
            OPTIONAL { ?assure as:prenom ?prenom }
            OPTIONAL { ?assure as:cin ?cin }
            OPTIONAL { ?assure as:telephone ?telephone }
            OPTIONAL { ?assure as:adresse ?adresse }
        }
        """
        return self.execute_sparql(q)["results"]

    def get_contrats(self) -> List[Dict[str, Any]]:
        q = """
        SELECT DISTINCT ?contrat ?typeContrat ?numero ?dateDebut ?dateFin ?prime ?assure WHERE {
            ?contrat a ?typeContrat .
            FILTER(?typeContrat != owl:NamedIndividual && ?typeContrat != owl:Class && !isBlank(?contrat) && (contains(str(?typeContrat), 'Contrat') || contains(str(?contrat), 'Contrat')))
            OPTIONAL { ?contrat as:numeroContrat ?numero }
            OPTIONAL { ?contrat as:dateDebut ?dateDebut }
            OPTIONAL { ?contrat as:dateFin ?dateFin }
            OPTIONAL { ?contrat as:montantPrime ?prime }
            OPTIONAL { ?contrat as:aPourAssure ?assure }
        }
        """
        return self.execute_sparql(q)["results"]

    def get_classes_hierarchy(self) -> List[Dict[str, Any]]:
        q = """
        SELECT DISTINCT ?class ?subClass WHERE {
            ?subClass rdfs:subClassOf ?class .
            FILTER(!isBlank(?class) && !isBlank(?subClass) && ?class != owl:Thing)
        }
        """
        return self.execute_sparql(q)["results"]

    def add_sinistre(self, data: Dict[str, Any]) -> str:
        sin_id = data.get("id") or f"Sinistre{len(self.get_sinistres()) + 1}"
        sin_uri = AS[sin_id]
        sin_type_str = data.get("type", "SinistreDegatDesEaux")
        
        sin_type_uri = UNT[sin_type_str] if hasattr(UNT, sin_type_str) else AS[sin_type_str]
        
        self.graph.add((sin_uri, RDF.type, OWL.NamedIndividual))
        self.graph.add((sin_uri, RDF.type, sin_type_uri))

        if "date" in data:
            self.graph.add((sin_uri, AS.dateSinistre, Literal(data["date"], datatype=XSD.dateTime)))
        if "description" in data:
            self.graph.add((sin_uri, AS.descriptionSinistre, Literal(data["description"], datatype=XSD.string)))
        if "lieu" in data:
            self.graph.add((sin_uri, AS.lieuSinistre, Literal(data["lieu"], datatype=XSD.string)))
        if "assure" in data:
            self.graph.add((sin_uri, AS.estDeclarePar, AS[data["assure"]]))
        if "expert" in data:
            self.graph.add((sin_uri, AS.expertisePar, AS[data["expert"]]))

        self.save_graph()
        return sin_id

ontology_service = OntologyService()
