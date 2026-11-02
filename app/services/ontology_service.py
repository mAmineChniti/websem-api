import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
import rdflib
from rdflib import Graph, Literal, Namespace, RDF, RDFS, OWL, XSD, URIRef

# Lock global pour sérialiser l'analyse des requêtes SPARQL (pyparsing n'étant pas thread-safe dans rdflib)
_sparql_lock = threading.Lock()


def _date_time_literal(value: datetime | str) -> Literal:
    """Construit une date conforme à la plage xsd:dateTime de l’ontologie."""
    parsed = (
        value
        if isinstance(value, datetime)
        else datetime.fromisoformat(value.replace("Z", "+00:00"))
    )
    return Literal(parsed.isoformat(), datatype=XSD.dateTime)


AS = Namespace(
    "http://www.semanticweb.org/asus/ontologies/2026/8/Assuarnce_et_Gestion_des_Sinistres#"
)
UNT = Namespace("http://www.semanticweb.org/asus/ontologies/2026/8/untitled-ontology-5#")

DEFAULT_PREFIXES = """
PREFIX as: <http://www.semanticweb.org/asus/ontologies/2026/8/Assuarnce_et_Gestion_des_Sinistres#>
PREFIX unt: <http://www.semanticweb.org/asus/ontologies/2026/8/untitled-ontology-5#>
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX owl: <http://www.w3.org/2002/07/owl#>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
"""

# ── Bibliothèque de requêtes SPARQL exemples ─────────────────────────────────
SPARQL_EXAMPLES = [
    {
        "id": "ex01",
        "title": "Tous les assurés (SELECT + ORDER BY)",
        "category": "Personnes",
        "difficulty": "Débutant",
        "description": "Liste tous les assurés avec leurs informations triés par nom",
        "query": """\
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
        "id": "ex02",
        "title": "Compter les personnes par rôle (GROUP BY + COUNT)",
        "category": "Statistiques",
        "difficulty": "Intermédiaire",
        "description": "Compte le nombre d'individus pour chaque rôle (Assuré, Agent, Expert...)",
        "query": """\
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
    {
        "id": "ex03",
        "title": "Contrats avec prime élevée (FILTER numérique)",
        "category": "Contrats",
        "difficulty": "Intermédiaire",
        "description": "Filtre les contrats dont la prime annuelle dépasse 500 DT",
        "query": """\
SELECT DISTINCT ?contrat ?typeContrat ?numeroContrat ?montantPrime ?assure WHERE {
    ?contrat a ?typeContrat .
    FILTER(contains(str(?typeContrat), 'Contrat') || contains(str(?contrat), 'Contrat'))
    ?contrat as:montantPrime ?montantPrime .
    FILTER(xsd:float(?montantPrime) > 500)
    OPTIONAL { ?contrat as:numeroContrat ?numeroContrat }
    OPTIONAL { ?contrat as:aPourAssure ?assure }
}
ORDER BY DESC(?montantPrime)""",
    },
    {
        "id": "ex04",
        "title": "Tous les sinistres déclarés (SELECT + OPTIONAL)",
        "category": "Sinistres",
        "difficulty": "Débutant",
        "description": "Récupère tous les sinistres avec dates, lieu et type",
        "query": """\
SELECT DISTINCT ?sinistre ?typeSinistre ?dateSinistre ?lieuSinistre ?descriptionSinistre WHERE {
    ?sinistre a ?typeSinistre .
    FILTER(contains(str(?typeSinistre), 'Sinistre') || contains(str(?sinistre), 'Sinistre'))
    OPTIONAL { ?sinistre as:dateSinistre ?dateSinistre }
    OPTIONAL { ?sinistre as:lieuSinistre ?lieuSinistre }
    OPTIONAL { ?sinistre as:descriptionSinistre ?descriptionSinistre }
}
ORDER BY DESC(?dateSinistre)""",
    },
    {
        "id": "ex05",
        "title": "Relations assurés ↔ contrats (JOIN entre classes)",
        "category": "Relations",
        "difficulty": "Avancé",
        "description": "Jointure entre Assuré et Contrat via la propriété objet aPourAssure",
        "query": """\
SELECT ?assure ?nomAssure ?prenomAssure ?contrat ?typeContrat ?montantPrime WHERE {
    ?contrat a ?typeContrat .
    FILTER(contains(str(?typeContrat), 'Contrat') || contains(str(?contrat), 'Contrat'))
    ?contrat as:aPourAssure ?assure .
    OPTIONAL { ?assure as:nom ?nomAssure }
    OPTIONAL { ?assure as:prenom ?prenomAssure }
    OPTIONAL { ?contrat as:montantPrime ?montantPrime }
}
ORDER BY ?nomAssure""",
    },
    {
        "id": "ex06",
        "title": "Toutes les classes OWL de l'ontologie",
        "category": "Ontologie",
        "difficulty": "Débutant",
        "description": "Affiche la hiérarchie des classes (sous-classes de owl:Thing)",
        "query": """\
SELECT DISTINCT ?classe ?superClasse WHERE {
    ?classe a owl:Class .
    FILTER(!isBlank(?classe) && contains(str(?classe), 'Assuarnce'))
    OPTIONAL { ?classe rdfs:subClassOf ?superClasse . FILTER(!isBlank(?superClasse)) }
}
ORDER BY ?superClasse ?classe""",
    },
    {
        "id": "ex07",
        "title": "Propriétés datatype de l'ontologie",
        "category": "Ontologie",
        "difficulty": "Intermédiaire",
        "description": "Liste toutes les DataProperty définies dans l'ontologie",
        "query": """\
SELECT DISTINCT ?propriete WHERE {
    ?propriete a owl:DatatypeProperty .
    FILTER(contains(str(?propriete), 'Assuarnce'))
}
ORDER BY ?propriete""",
    },
    {
        "id": "ex08",
        "title": "Propriétés objet (relations entre classes)",
        "category": "Ontologie",
        "difficulty": "Intermédiaire",
        "description": "Liste toutes les ObjectProperty qui relient les classes",
        "query": """\
SELECT DISTINCT ?propriete WHERE {
    ?propriete a owl:ObjectProperty .
    FILTER(contains(str(?propriete), 'Assuarnce'))
}
ORDER BY ?propriete""",
    },
    {
        "id": "ex09",
        "title": "Tous les individus de l'ontologie",
        "category": "Individus",
        "difficulty": "Débutant",
        "description": "Liste tous les individus (NamedIndividual) créés dans Protégé",
        "query": """\
SELECT DISTINCT ?individu ?type WHERE {
    ?individu a owl:NamedIndividual .
    ?individu a ?type .
    FILTER(?type != owl:NamedIndividual)
    FILTER(!isBlank(?individu))
}
ORDER BY ?type ?individu""",
    },
    {
        "id": "ex10",
        "title": "Statistiques primes par type de contrat (GROUP BY + AVG)",
        "category": "Statistiques",
        "difficulty": "Avancé",
        "description": "Calcule le nombre de contrats par type (GROUP BY avec COUNT)",
        "query": """\
SELECT ?typeContrat (COUNT(?contrat) AS ?nbContrats) WHERE {
    ?contrat a ?typeContrat .
    FILTER(contains(str(?typeContrat), 'Contrat') || contains(str(?contrat), 'Contrat'))
    ?typeContrat a owl:Class .
}
GROUP BY ?typeContrat
ORDER BY DESC(?nbContrats)""",
    },
    {
        "id": "ex11",
        "title": "Garanties incendie avec plafond (FILTER + OPTIONAL)",
        "category": "Garanties",
        "difficulty": "Intermédiaire",
        "description": "Récupère les garanties incendie et leur plafond de remboursement",
        "query": """\
SELECT DISTINCT ?garantie ?typeGarantie ?plafond ?taux WHERE {
    ?garantie a ?typeGarantie .
    FILTER(contains(str(?typeGarantie), 'Garantie') || contains(str(?garantie), 'Garantie'))
    OPTIONAL { ?garantie as:plafondGarantie ?plafond }
    OPTIONAL { ?garantie as:tauxFranchise ?taux }
}
ORDER BY ?typeGarantie""",
    },
    {
        "id": "ex12",
        "title": "Déclarations acceptées vs rejetées (FILTER sur statut)",
        "category": "Déclarations",
        "difficulty": "Intermédiaire",
        "description": "Filtre les déclarations selon leur statut (Acceptée / Rejetée / En cours)",
        "query": """\
SELECT DISTINCT ?declaration ?typeDeclaration ?date ?statut WHERE {
    ?declaration a ?typeDeclaration .
    FILTER(contains(str(?typeDeclaration), 'Declaration') || contains(str(?declaration), 'Declaration'))
    OPTIONAL { ?declaration as:dateDeclaration ?date }
    OPTIONAL { ?declaration as:statutDeclaration ?statut }
}
ORDER BY ?typeDeclaration""",
    },
]


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
            print(
                f"[OntologyService] Ontologie chargee depuis {self.rdf_path} ({len(self.graph)} triplets)."
            )
        else:
            raise FileNotFoundError(f"Fichier d'ontologie non trouve: {self.rdf_path}")

    def reload_graph(self):
        """Recharge l'ontologie depuis le fichier RDF (après modification dans Protégé)."""
        with _sparql_lock:
            self.graph = Graph()
            self.load_graph()
            return {"status": "ok", "triples": len(self.graph), "path": self.rdf_path}

    def save_graph(self):
        with _sparql_lock:
            self.graph.serialize(destination=self.rdf_path, format="xml")

    def execute_sparql(self, query: str) -> Dict[str, Any]:
        with _sparql_lock:
            full_query = query
            if "PREFIX" not in query.upper():
                full_query = DEFAULT_PREFIXES + "\n" + query

            qres = self.graph.query(full_query)

            if hasattr(qres, "type") and qres.type == "ASK":
                return {"type": "ASK", "boolean": bool(qres)}

            vars_list = [str(v) for v in qres.vars] if hasattr(qres, "vars") and qres.vars else []
            rows = []
            for row in qres:
                row_dict = {}
                for v in vars_list:
                    val = row[rdflib.Variable(v)]
                    if val is not None:
                        val_str = str(val)
                        clean_str = val_str.split("#")[-1] if "#" in val_str else val_str
                        row_dict[v] = clean_str
                    else:
                        row_dict[v] = None
                rows.append(row_dict)

            return {"vars": vars_list, "count": len(rows), "results": rows, "query": query}

    # ── Module HIBA : PERSONNES (Agent, Assure, Beneficiaire, Expert) ─────────
    def get_personnes(self, role: str | None = None) -> List[Dict[str, Any]]:
        filter_clause = ""
        if role:
            filter_clause = (
                f"FILTER(contains(str(?type), '{role}') || contains(str(?personne), '{role}'))"
            )

        q = f"""
        SELECT DISTINCT ?personne ?type ?nom ?prenom ?cin ?telephone ?adresse WHERE {{
            {{
                # Cas 1 : Individu avec type explicite (Assure, Agent, Expert, Beneficiaire, Personne)
                ?personne a ?type .
                FILTER(!isBlank(?personne))
                FILTER(?type != owl:NamedIndividual)
                FILTER(?type != owl:Class)
                FILTER(?type != owl:ObjectProperty)
                FILTER(?type != owl:DatatypeProperty)
                FILTER(!contains(str(?type), 'Rapport'))
                FILTER(!contains(str(?type), 'Contrat'))
                FILTER(!contains(str(?type), 'Sinistre'))
                FILTER(!contains(str(?type), 'Habitation'))
                FILTER(
                    contains(str(?type), 'Assure') ||
                    contains(str(?type), 'Agent') ||
                    contains(str(?type), 'Expert') ||
                    contains(str(?type), 'Beneficiaire') ||
                    contains(str(?type), 'Personne')
                )
            }}
            UNION
            {{
                # Cas 2 : Individu lie a un contrat en tant qu'assure (meme sans rdf:type explicite dans Protege)
                {{ ?personne as:souscritContrat ?c }} UNION {{ ?c as:aPourAssure ?personne }}
                FILTER(!isBlank(?personne))
                BIND(uri(concat(str(as:), "Assure")) AS ?type)
            }}
            UNION
            {{
                # Cas 3 : Expert lie a un sinistre
                {{ ?personne as:evalueSinistre ?s }} UNION {{ ?s as:estEvaluePar ?personne }}
                FILTER(!isBlank(?personne))
                BIND(uri(concat(str(as:), "Expert")) AS ?type)
            }}
            UNION
            {{
                # Cas 4 : Agent lie a un contrat
                {{ ?personne as:gereContrat ?c2 }} UNION {{ ?c2 as:estGerePar ?personne }}
                FILTER(!isBlank(?personne))
                BIND(uri(concat(str(as:), "Agent")) AS ?type)
            }}
            {filter_clause}
            OPTIONAL {{ ?personne as:nom ?nom }}
            OPTIONAL {{ ?personne as:prenom ?prenom }}
            OPTIONAL {{ ?personne as:cin ?cin }}
            OPTIONAL {{ ?personne as:telephone ?telephone }}
            OPTIONAL {{ ?personne as:adresse ?adresse }}
        }}
        ORDER BY ?type ?nom
        """
        raw_results = self.execute_sparql(q)["results"]

        # Deduplication intelligente par identifiant
        merged: Dict[str, Dict[str, Any]] = {}
        for r in raw_results:
            pid = r.get("personne")
            if not pid:
                continue
            if pid not in merged:
                merged[pid] = dict(r)
            else:
                for field in ["nom", "prenom", "cin", "telephone", "adresse"]:
                    if not merged[pid].get(field) and r.get(field):
                        merged[pid][field] = r[field]
                if merged[pid].get("type") in ["Personne", None] and r.get("type"):
                    merged[pid]["type"] = r["type"]

        # Extraction automatique du nom/prenom si non renseigne dans Protege
        results = list(merged.values())
        for p in results:
            if not p.get("prenom") and not p.get("nom"):
                pid_clean = p["personne"].replace("_", " ").replace("-", " ").strip()
                parts = pid_clean.split()
                if len(parts) >= 2:
                    p["prenom"] = parts[0].capitalize()
                    p["nom"] = " ".join(parts[1:]).capitalize()
                elif len(parts) == 1:
                    p["nom"] = parts[0]
                    p["prenom"] = ""

        return results

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

    def update_personne(self, personne_id: str, data: Dict[str, Any]) -> bool:
        """Update properties of an existing person in the RDF graph."""
        p_uri = AS[personne_id]
        exists = (p_uri, RDF.type, OWL.NamedIndividual) in self.graph
        if not exists:
            found = any(True for _ in self.graph.triples((p_uri, RDF.type, None)))
            if not found:
                return False

        for prop, key in [
            (AS.nom, "nom"),
            (AS.prenom, "prenom"),
            (AS.cin, "cin"),
            (AS.telephone, "telephone"),
            (AS.adresse, "adresse"),
        ]:
            self.graph.remove((p_uri, prop, None))
            if data.get(key):
                self.graph.add((p_uri, prop, Literal(data[key], datatype=XSD.string)))

        self.save_graph()
        return True

    def delete_personne(self, personne_id: str) -> bool:
        """Remove all triples for a given person from the RDF graph."""
        p_uri = AS[personne_id]
        triples = list(self.graph.triples((p_uri, None, None)))
        if not triples:
            return False
        for t in triples:
            self.graph.remove(t)
        for t in list(self.graph.triples((None, None, p_uri))):
            self.graph.remove(t)
        self.save_graph()
        return True

    def change_role_personne(self, personne_id: str, new_role: str) -> bool:
        """Change the OWL type of a person to a new role."""
        p_uri = AS[personne_id]
        for role_name in ["Assure", "Agent", "Expert", "Beneficiaire", "Admin"]:
            for ns in [AS, UNT]:
                try:
                    old_uri = ns[role_name]
                    self.graph.remove((p_uri, RDF.type, old_uri))
                except Exception:
                    pass
        new_role_uri = UNT[new_role]
        self.graph.add((p_uri, RDF.type, OWL.NamedIndividual))
        self.graph.add((p_uri, RDF.type, new_role_uri))
        self.save_graph()
        return True

    # ── Module HIBA : CONTRATS ────────────────────────────────────────────────
    def get_contrats(self, type_filter: str | None = None) -> List[Dict[str, Any]]:
        filter_clause = ""
        if type_filter:
            filter_clause = f"FILTER(contains(str(?typeContrat), '{type_filter}'))"

        q = f"""
        SELECT DISTINCT ?contrat ?typeContrat ?numeroContrat ?dateDebut ?dateFin ?montantPrime ?franchise ?assure ?habitation ?garanties ?beneficiaire WHERE {{
            ?contrat a ?typeContrat .
            FILTER(!isBlank(?contrat))
            FILTER(?typeContrat != owl:NamedIndividual)
            FILTER(?typeContrat != owl:Class)
            FILTER(?typeContrat != owl:ObjectProperty)
            FILTER(?typeContrat != owl:DatatypeProperty)
            FILTER(?typeContrat != owl:FunctionalProperty)
            FILTER(contains(str(?typeContrat), 'Contrat'))
            {filter_clause}
            OPTIONAL {{ ?contrat as:numeroContrat ?numeroContrat }}
            OPTIONAL {{ ?contrat as:dateDebut ?dateDebut }}
            OPTIONAL {{ ?contrat as:dateFin ?dateFin }}
            OPTIONAL {{ ?contrat as:montantPrime ?montantPrime }}
            OPTIONAL {{ ?contrat as:montantFranchise ?franchise }}
            OPTIONAL {{ ?contrat as:aPourAssure ?assure }}
            OPTIONAL {{ ?contrat as:typeHabitation ?habitation }}
            OPTIONAL {{ ?contrat as:garanties ?garanties }}
            OPTIONAL {{ ?contrat as:aPourBeneficiaire ?beneficiaire }}
        }}
        ORDER BY ?typeContrat ?numeroContrat
        """
        raw_contrats = self.execute_sparql(q)["results"]
        return [
            c
            for c in raw_contrats
            if c.get("contrat")
            and not c["contrat"].endswith("Property")
            and c["contrat"] not in ["numeroContrat", "souscritContrat"]
        ]

    def add_contrat(self, data: Dict[str, Any]) -> str:
        c_id = data.get("id") or f"Contrat{len(self.get_contrats()) + 1}"
        c_uri = AS[c_id]
        c_type = data.get("type", "ContratProprietaire")
        type_uri = UNT[c_type] if hasattr(UNT, c_type) else AS[c_type]

        self.graph.add((c_uri, RDF.type, OWL.NamedIndividual))
        self.graph.add((c_uri, RDF.type, type_uri))

        if data.get("numeroContrat"):
            self.graph.add(
                (c_uri, AS.numeroContrat, Literal(data["numeroContrat"], datatype=XSD.string))
            )
        if data.get("dateDebut"):
            self.graph.add((c_uri, AS.dateDebut, Literal(data["dateDebut"], datatype=XSD.dateTime)))
        if data.get("dateFin"):
            self.graph.add((c_uri, AS.dateFin, Literal(data["dateFin"], datatype=XSD.dateTime)))
        if data.get("montantPrime") is not None:
            self.graph.add(
                (c_uri, AS.montantPrime, Literal(float(data["montantPrime"]), datatype=XSD.float))
            )
        if data.get("franchise") is not None:
            self.graph.add(
                (c_uri, AS.montantFranchise, Literal(float(data["franchise"]), datatype=XSD.float))
            )
        if data.get("habitation"):
            self.graph.add(
                (c_uri, AS.typeHabitation, Literal(data["habitation"], datatype=XSD.string))
            )
        if data.get("garanties"):
            self.graph.add((c_uri, AS.garanties, Literal(data["garanties"], datatype=XSD.string)))
        if data.get("assure"):
            assure_uri = AS[data["assure"]]
            self.graph.add((c_uri, AS.aPourAssure, assure_uri))
            self.graph.add((assure_uri, AS.souscritContrat, c_uri))
        if data.get("beneficiaire"):
            self.graph.add((c_uri, AS.aPourBeneficiaire, AS[data["beneficiaire"]]))

        self.save_graph()
        return c_id

    def update_contrat(self, contrat_id: str, data: Dict[str, Any]) -> bool:
        """Update properties and links of an existing contract in the RDF graph."""
        c_uri = AS[contrat_id]
        found = any(True for _ in self.graph.triples((c_uri, None, None)))
        if not found:
            return False

        # 1. Update contract type
        if data.get("type"):
            new_type = data["type"]
            for ct in ["ContratProprietaire", "ContratLocataire", "ContratCopropriete", "Contrat"]:
                for ns in [AS, UNT]:
                    try:
                        self.graph.remove((c_uri, RDF.type, ns[ct]))
                    except Exception:
                        pass
            type_uri = UNT[new_type] if hasattr(UNT, new_type) else AS[new_type]
            self.graph.add((c_uri, RDF.type, type_uri))
            self.graph.add((c_uri, RDF.type, OWL.NamedIndividual))

        # 2. Update numeroContrat
        if data.get("numeroContrat"):
            self.graph.remove((c_uri, AS.numeroContrat, None))
            self.graph.add(
                (c_uri, AS.numeroContrat, Literal(data["numeroContrat"], datatype=XSD.string))
            )

        # 3. Update dates
        if data.get("dateDebut"):
            self.graph.remove((c_uri, AS.dateDebut, None))
            self.graph.add((c_uri, AS.dateDebut, Literal(data["dateDebut"], datatype=XSD.dateTime)))
        if data.get("dateFin"):
            self.graph.remove((c_uri, AS.dateFin, None))
            self.graph.add((c_uri, AS.dateFin, Literal(data["dateFin"], datatype=XSD.dateTime)))

        # 4. Update prime & franchise
        if data.get("montantPrime") is not None:
            self.graph.remove((c_uri, AS.montantPrime, None))
            self.graph.add(
                (c_uri, AS.montantPrime, Literal(float(data["montantPrime"]), datatype=XSD.float))
            )
        if data.get("franchise") is not None:
            self.graph.remove((c_uri, AS.montantFranchise, None))
            self.graph.add(
                (c_uri, AS.montantFranchise, Literal(float(data["franchise"]), datatype=XSD.float))
            )

        # 5. Update Assure
        if data.get("assure"):
            old_assures = list(self.graph.objects(c_uri, AS.aPourAssure))
            for old_a in old_assures:
                self.graph.remove((c_uri, AS.aPourAssure, old_a))
                self.graph.remove((old_a, AS.souscritContrat, c_uri))
            new_a_uri = AS[data["assure"]]
            self.graph.add((c_uri, AS.aPourAssure, new_a_uri))
            self.graph.add((new_a_uri, AS.souscritContrat, c_uri))

        # 6. Habitation / Garanties / Beneficiaire
        if data.get("habitation"):
            self.graph.remove((c_uri, AS.typeHabitation, None))
            self.graph.add(
                (c_uri, AS.typeHabitation, Literal(data["habitation"], datatype=XSD.string))
            )
        if data.get("garanties"):
            self.graph.remove((c_uri, AS.garanties, None))
            self.graph.add((c_uri, AS.garanties, Literal(data["garanties"], datatype=XSD.string)))
        if "beneficiaire" in data:
            self.graph.remove((c_uri, AS.aPourBeneficiaire, None))
            if data["beneficiaire"]:
                self.graph.add((c_uri, AS.aPourBeneficiaire, AS[data["beneficiaire"]]))

        self.save_graph()
        return True

    def delete_contrat(self, contrat_id: str) -> bool:
        c_uri = AS[contrat_id]
        triples_to_remove = list(self.graph.triples((c_uri, None, None))) + list(
            self.graph.triples((None, None, c_uri))
        )
        for t in triples_to_remove:
            self.graph.remove(t)
        self.save_graph()
        return len(triples_to_remove) > 0

    # ── Méthodes d'exploration ontologique ───────────────────────────────────
    def get_all_classes(self) -> List[Dict[str, Any]]:
        """Retourne toutes les classes OWL de l'ontologie avec leur hiérarchie."""
        q = """
        SELECT DISTINCT ?classe ?superClasse WHERE {
            ?classe a owl:Class .
            FILTER(!isBlank(?classe) && contains(str(?classe), 'Assuarnce'))
            OPTIONAL { ?classe rdfs:subClassOf ?superClasse . FILTER(!isBlank(?superClasse)) }
        }
        ORDER BY ?superClasse ?classe
        """
        return self.execute_sparql(q)["results"]

    def get_class_instances(self, class_name: str) -> List[Dict[str, Any]]:
        """Retourne tous les individus d'une classe donnée."""
        q = f"""
        SELECT DISTINCT ?individu ?nom ?prenom WHERE {{
            ?individu a ?type .
            FILTER(contains(str(?type), '{class_name}') || contains(str(?individu), '{class_name}'))
            OPTIONAL {{ ?individu as:nom ?nom }}
            OPTIONAL {{ ?individu as:prenom ?prenom }}
        }}
        ORDER BY ?individu
        """
        return self.execute_sparql(q)["results"]

    def get_object_properties(self) -> List[Dict[str, Any]]:
        """Retourne toutes les ObjectProperty de l'ontologie."""
        q = """
        SELECT DISTINCT ?propriete WHERE {
            ?propriete a owl:ObjectProperty .
            FILTER(contains(str(?propriete), 'Assuarnce'))
        }
        ORDER BY ?propriete
        """
        return self.execute_sparql(q)["results"]

    def get_data_properties(self) -> List[Dict[str, Any]]:
        """Retourne toutes les DataProperty de l'ontologie."""
        q = """
        SELECT DISTINCT ?propriete WHERE {
            ?propriete a owl:DatatypeProperty .
            FILTER(contains(str(?propriete), 'Assuarnce'))
        }
        ORDER BY ?propriete
        """
        return self.execute_sparql(q)["results"]

    def get_sparql_examples(self) -> List[Dict[str, Any]]:
        """Retourne la bibliothèque des requêtes SPARQL exemples."""
        return SPARQL_EXAMPLES

    # ── Stats globales ────────────────────────────────────────────────────────
    def get_stats(self) -> Dict[str, Any]:
        personnes = self.get_personnes()
        contrats = self.get_contrats()

        # Compter par rôle
        def count_role(role: str) -> int:
            return len(
                [
                    p
                    for p in personnes
                    if role in (p.get("type") or "") or role in (p.get("personne") or "")
                ]
            )

        # Compter les classes disponibles
        classes = self.get_all_classes()

        return {
            "module": "Système d'Assurance Habitation (Personnes & Contrats)",
            "personnes_count": len(personnes),
            "contrats_count": len(contrats),
            "assures_count": count_role("Assure"),
            "agents_count": count_role("Agent"),
            "experts_count": count_role("Expert"),
            "beneficiaires_count": count_role("Beneficiaire"),
            "classes_count": len(classes),
            "dommages_count": len(self.get_dommages()),
            "clauses_count": len(self.get_clauses()),
            "total_triples": len(self.graph),
            "sparql_examples_count": len(SPARQL_EXAMPLES),
            "ontology_uri": "http://www.semanticweb.org/asus/ontologies/2026/8/Assuarnce_et_Gestion_des_Sinistres",
            "rdf_format": "OWL/RDF XML (Protégé)",
        }

    # ── Module MONTAHA : DOMMAGES ─────────────────────────────────────────────
    def get_dommages(self, type_filter: str | None = None) -> List[Dict[str, Any]]:
        """Retourne la liste des dommages depuis l'ontologie OWL/RDF."""
        filter_clause = ""
        if type_filter:
            filter_clause = f"FILTER(contains(str(?typeDommage), '{type_filter}'))"

        q = f"""
        SELECT DISTINCT ?dommage ?typeDommage ?gravite ?montant ?description ?date ?lieu ?sinistre WHERE {{
            ?dommage a ?typeDommage .
            FILTER(!isBlank(?dommage))
            FILTER(?typeDommage != owl:NamedIndividual)
            FILTER(?typeDommage != owl:Class)
            FILTER(?typeDommage != owl:ObjectProperty)
            FILTER(?typeDommage != owl:DatatypeProperty)
            FILTER(contains(str(?typeDommage), 'Dommage') || contains(str(?dommage), 'Dommage'))
            {filter_clause}
            OPTIONAL {{ ?dommage as:niveauGravite ?gravite }}
            OPTIONAL {{ ?dommage as:montantIndemnise ?montant }}
            OPTIONAL {{ ?dommage as:descriptionSinistre ?description }}
            OPTIONAL {{ ?dommage as:dateSinistre ?date }}
            OPTIONAL {{ ?dommage as:lieuSinistre ?lieu }}
            OPTIONAL {{
                {{ ?sinistre as:provoqueDommage ?dommage }}
                UNION
                {{ ?sinistre as:aPourDommage ?dommage }}
                UNION
                {{ ?dommage as:estProvoquePar ?sinistre }}
            }}
        }}
        ORDER BY ?typeDommage ?dommage
        """
        raw = self.execute_sparql(q)["results"]
        cleaned = []
        seen = set()
        for d in raw:
            dom_id = d.get("dommage")
            if not dom_id or dom_id in seen:
                continue
            if dom_id.endswith("Property") or dom_id.startswith("provoque") or dom_id == "Dommage":
                continue
            seen.add(dom_id)
            cleaned.append(
                {
                    "id": dom_id,
                    "type": d.get("typeDommage") or "DommageMateriel",
                    "description": d.get("description") or "",
                    "montant": float(d["montant"]) if d.get("montant") else 0.0,
                    "gravite": d.get("gravite") or "Faible",
                    "sinistre": d.get("sinistre"),
                    "date": d.get("date"),
                    "lieu": d.get("lieu"),
                }
            )
        return cleaned

    def get_all_dommages(self, type_filter: str | None = None) -> List[Dict[str, Any]]:
        return self.get_dommages(type_filter)

    def get_dommage_by_id(self, dommage_id: str) -> Dict[str, Any] | None:
        dommages = self.get_dommages()
        for d in dommages:
            if d["id"] == dommage_id:
                return d
        return None

    def create_dommage(self, data: Dict[str, Any]) -> str:
        """Crée un nouvel individu Dommage dans l'ontologie RDF."""
        existing = self.get_dommages()
        d_id = data.get("id") or f"Dommage{len(existing) + 1}"
        existing_ids = {e["id"] for e in existing}
        counter = len(existing) + 1
        while d_id in existing_ids:
            counter += 1
            d_id = f"Dommage{counter}"

        d_uri = AS[d_id]
        raw_type = data.get("type_dommage") or data.get("type") or "DommageMateriel"
        if "materiel" in raw_type.lower() and "im" not in raw_type.lower():
            type_name = "DommageMateriel"
        elif "corporel" in raw_type.lower():
            type_name = "DommageCorporel"
        elif "immateriel" in raw_type.lower() or "immatériel" in raw_type.lower():
            type_name = "DommageImmateriel"
        else:
            type_name = raw_type

        type_uri = UNT[type_name]

        self.graph.add((d_uri, RDF.type, OWL.NamedIndividual))
        self.graph.add((d_uri, RDF.type, type_uri))

        if data.get("gravite"):
            self.graph.add((d_uri, AS.niveauGravite, Literal(data["gravite"], datatype=XSD.string)))
        if data.get("montant") is not None:
            self.graph.add(
                (d_uri, AS.montantIndemnise, Literal(float(data["montant"]), datatype=XSD.float))
            )
        if data.get("description"):
            self.graph.add(
                (d_uri, AS.descriptionSinistre, Literal(data["description"], datatype=XSD.string))
            )
        if data.get("date"):
            self.graph.add((d_uri, AS.dateSinistre, _date_time_literal(data["date"])))
        if data.get("lieu"):
            self.graph.add((d_uri, AS.lieuSinistre, Literal(data["lieu"], datatype=XSD.string)))

        # Liaison avec Sinistre
        if data.get("sinistre_id") or data.get("sinistre"):
            sinistre_val = data.get("sinistre_id") or data.get("sinistre")
            sinistre_uri = AS[sinistre_val]
            self.graph.add((sinistre_uri, AS.provoqueDommage, d_uri))
            self.graph.add((d_uri, AS.estProvoquePar, sinistre_uri))

        self.save_graph()
        return d_id

    def update_dommage(self, dommage_id: str, data: Dict[str, Any]) -> bool:
        """Met à jour les propriétés d'un Dommage existant."""
        d_uri = AS[dommage_id]
        found = any(True for _ in self.graph.triples((d_uri, None, None)))
        if not found:
            return False

        # Mise à jour du type si fourni
        if data.get("type_dommage") or data.get("type"):
            raw_type = data.get("type_dommage") or data.get("type")
            if "materiel" in raw_type.lower() and "im" not in raw_type.lower():
                type_name = "DommageMateriel"
            elif "corporel" in raw_type.lower():
                type_name = "DommageCorporel"
            elif "immateriel" in raw_type.lower() or "immatériel" in raw_type.lower():
                type_name = "DommageImmateriel"
            else:
                type_name = raw_type

            for dt in [
                "DommageMateriel",
                "DommageCorporel",
                "DommageImmateriel",
                "DommageImmatériel",
                "Dommage",
            ]:
                for ns in [AS, UNT]:
                    try:
                        self.graph.remove((d_uri, RDF.type, ns[dt]))
                    except Exception:
                        pass
            self.graph.add((d_uri, RDF.type, UNT[type_name]))
            self.graph.add((d_uri, RDF.type, OWL.NamedIndividual))

        if "gravite" in data and data["gravite"]:
            self.graph.remove((d_uri, AS.niveauGravite, None))
            self.graph.add((d_uri, AS.niveauGravite, Literal(data["gravite"], datatype=XSD.string)))

        if "montant" in data and data["montant"] is not None:
            self.graph.remove((d_uri, AS.montantIndemnise, None))
            self.graph.add(
                (d_uri, AS.montantIndemnise, Literal(float(data["montant"]), datatype=XSD.float))
            )

        if "description" in data and data["description"]:
            self.graph.remove((d_uri, AS.descriptionSinistre, None))
            self.graph.add(
                (d_uri, AS.descriptionSinistre, Literal(data["description"], datatype=XSD.string))
            )

        if "date" in data and data["date"]:
            self.graph.remove((d_uri, AS.dateSinistre, None))
            self.graph.add((d_uri, AS.dateSinistre, _date_time_literal(data["date"])))

        if "lieu" in data and data["lieu"]:
            self.graph.remove((d_uri, AS.lieuSinistre, None))
            self.graph.add((d_uri, AS.lieuSinistre, Literal(data["lieu"], datatype=XSD.string)))

        if "sinistre_id" in data or "sinistre" in data:
            sinistre_val = data.get("sinistre_id") or data.get("sinistre")
            for s, p, o in list(self.graph.triples((None, AS.provoqueDommage, d_uri))):
                self.graph.remove((s, p, o))
            self.graph.remove((d_uri, AS.estProvoquePar, None))
            if sinistre_val:
                s_uri = AS[sinistre_val]
                self.graph.add((s_uri, AS.provoqueDommage, d_uri))
                self.graph.add((d_uri, AS.estProvoquePar, s_uri))

        self.save_graph()
        return True

    def delete_dommage(self, dommage_id: str) -> bool:
        """Supprime un dommage et tous ses triplets associés."""
        d_uri = AS[dommage_id]
        triples_to_remove = list(self.graph.triples((d_uri, None, None))) + list(
            self.graph.triples((None, None, d_uri))
        )
        for t in triples_to_remove:
            self.graph.remove(t)
        self.save_graph()
        return len(triples_to_remove) > 0

    # ── Module MONTAHA : CLAUSES ──────────────────────────────────────────────
    def get_clauses(self, type_filter: str | None = None) -> List[Dict[str, Any]]:
        """Retourne la liste des clauses depuis l'ontologie OWL/RDF."""
        filter_clause = ""
        if type_filter:
            filter_clause = f"FILTER(contains(str(?typeClause), '{type_filter}'))"

        q = f"""
        SELECT DISTINCT ?clause ?typeClause ?texteClause ?tauxFranchise ?description ?contrat WHERE {{
            ?clause a ?typeClause .
            FILTER(!isBlank(?clause))
            FILTER(?typeClause != owl:NamedIndividual)
            FILTER(?typeClause != owl:Class)
            FILTER(?typeClause != owl:ObjectProperty)
            FILTER(?typeClause != owl:DatatypeProperty)
            FILTER(contains(str(?typeClause), 'Clause') || contains(str(?clause), 'Clause'))
            {filter_clause}
            OPTIONAL {{ ?clause as:texteClause ?texteClause }}
            OPTIONAL {{ ?clause as:tauxFranchise ?tauxFranchise }}
            OPTIONAL {{ ?clause as:description ?description }}
            OPTIONAL {{
                {{ ?contrat as:aPourClause ?clause }}
                UNION
                {{ ?clause as:estClauseDe ?contrat }}
                UNION
                {{ ?clause as:concerneContrat ?contrat }}
            }}
        }}
        ORDER BY ?typeClause ?clause
        """
        raw = self.execute_sparql(q)["results"]
        cleaned = []
        seen = set()
        for c in raw:
            cl_id = c.get("clause")
            if not cl_id or cl_id in seen:
                continue
            if cl_id.endswith("Property") or cl_id.startswith("aPour") or cl_id == "Clause":
                continue
            seen.add(cl_id)
            cleaned.append(
                {
                    "id": cl_id,
                    "type": c.get("typeClause") or "ClauseExclusion",
                    "texte_clause": c.get("texteClause") or "",
                    "description": c.get("description") or "",
                    "taux_franchise": float(c["tauxFranchise"]) if c.get("tauxFranchise") else None,
                    "contrat": c.get("contrat"),
                }
            )
        return cleaned

    def get_all_clauses(self, type_filter: str | None = None) -> List[Dict[str, Any]]:
        return self.get_clauses(type_filter)

    def get_clause_by_id(self, clause_id: str) -> Dict[str, Any] | None:
        clauses = self.get_clauses()
        for c in clauses:
            if c["id"] == clause_id:
                return c
        return None

    def create_clause(self, data: Dict[str, Any]) -> str:
        """Crée une nouvelle clause dans l'ontologie RDF."""
        existing = self.get_clauses()
        c_id = data.get("id") or f"Clause{len(existing) + 1}"
        existing_ids = {e["id"] for e in existing}
        counter = len(existing) + 1
        while c_id in existing_ids:
            counter += 1
            c_id = f"Clause{counter}"

        c_uri = AS[c_id]
        raw_type = data.get("type_clause") or data.get("type") or "ClauseExclusion"
        if "exclusion" in raw_type.lower():
            type_name = "ClauseExclusion"
        elif "franchise" in raw_type.lower():
            type_name = "ClauseFranchise"
        elif "obligatoire" in raw_type.lower():
            type_name = "ClauseObligatoire"
        else:
            type_name = raw_type

        type_uri = UNT[type_name]

        self.graph.add((c_uri, RDF.type, OWL.NamedIndividual))
        self.graph.add((c_uri, RDF.type, type_uri))

        if data.get("texte_clause") or data.get("texteClause"):
            txt = data.get("texte_clause") or data.get("texteClause")
            self.graph.add((c_uri, AS.texteClause, Literal(txt, datatype=XSD.string)))

        if (data.get("taux_franchise") is not None) or (data.get("tauxFranchise") is not None):
            val = (
                data.get("taux_franchise")
                if data.get("taux_franchise") is not None
                else data.get("tauxFranchise")
            )
            self.graph.add((c_uri, AS.tauxFranchise, Literal(float(val), datatype=XSD.float)))

        if data.get("description"):
            self.graph.add(
                (c_uri, AS.description, Literal(data["description"], datatype=XSD.string))
            )

        # Liaison avec Contrat
        if data.get("contrat_id") or data.get("contrat"):
            contrat_val = data.get("contrat_id") or data.get("contrat")
            contrat_uri = AS[contrat_val]
            self.graph.add((contrat_uri, AS.aPourClause, c_uri))
            self.graph.add((c_uri, AS.estClauseDe, contrat_uri))

        self.save_graph()
        return c_id

    def update_clause(self, clause_id: str, data: Dict[str, Any]) -> bool:
        """Met à jour une clause existante."""
        c_uri = AS[clause_id]
        found = any(True for _ in self.graph.triples((c_uri, None, None)))
        if not found:
            return False

        if data.get("type_clause") or data.get("type"):
            raw_type = data.get("type_clause") or data.get("type")
            if "exclusion" in raw_type.lower():
                type_name = "ClauseExclusion"
            elif "franchise" in raw_type.lower():
                type_name = "ClauseFranchise"
            elif "obligatoire" in raw_type.lower():
                type_name = "ClauseObligatoire"
            else:
                type_name = raw_type

            for ct in ["ClauseExclusion", "ClauseFranchise", "ClauseObligatoire", "Clause"]:
                for ns in [AS, UNT]:
                    try:
                        self.graph.remove((c_uri, RDF.type, ns[ct]))
                    except Exception:
                        pass
            self.graph.add((c_uri, RDF.type, UNT[type_name]))
            self.graph.add((c_uri, RDF.type, OWL.NamedIndividual))

        if ("texte_clause" in data and data["texte_clause"]) or (
            "texteClause" in data and data["texteClause"]
        ):
            txt = data.get("texte_clause") or data.get("texteClause")
            self.graph.remove((c_uri, AS.texteClause, None))
            self.graph.add((c_uri, AS.texteClause, Literal(txt, datatype=XSD.string)))

        if ("taux_franchise" in data and data["taux_franchise"] is not None) or (
            "tauxFranchise" in data and data["tauxFranchise"] is not None
        ):
            val = (
                data.get("taux_franchise")
                if data.get("taux_franchise") is not None
                else data.get("tauxFranchise")
            )
            self.graph.remove((c_uri, AS.tauxFranchise, None))
            self.graph.add((c_uri, AS.tauxFranchise, Literal(float(val), datatype=XSD.float)))

        if "description" in data and data["description"]:
            self.graph.remove((c_uri, AS.description, None))
            self.graph.add(
                (c_uri, AS.description, Literal(data["description"], datatype=XSD.string))
            )

        if "contrat_id" in data or "contrat" in data:
            contrat_val = data.get("contrat_id") or data.get("contrat")
            for s, p, o in list(self.graph.triples((None, AS.aPourClause, c_uri))):
                self.graph.remove((s, p, o))
            self.graph.remove((c_uri, AS.estClauseDe, None))
            if contrat_val:
                co_uri = AS[contrat_val]
                self.graph.add((co_uri, AS.aPourClause, c_uri))
                self.graph.add((c_uri, AS.estClauseDe, co_uri))

        self.save_graph()
        return True

    def delete_clause(self, clause_id: str) -> bool:
        """Supprime une clause et ses triplets associés."""
        c_uri = AS[clause_id]
        triples_to_remove = list(self.graph.triples((c_uri, None, None))) + list(
            self.graph.triples((None, None, c_uri))
        )
        for t in triples_to_remove:
            self.graph.remove(t)
        self.save_graph()
        return len(triples_to_remove) > 0


ontology_service = OntologyService()
