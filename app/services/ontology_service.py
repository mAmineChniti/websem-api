import os
from pathlib import Path
from typing import Any, Dict, List, Optional
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
            print(f"[OntologyService] Ontologie chargee depuis {self.rdf_path} ({len(self.graph)} triplets).")
        else:
            raise FileNotFoundError(f"Fichier d'ontologie non trouve: {self.rdf_path}")

    def reload_graph(self):
        """Recharge l'ontologie depuis le fichier RDF (après modification dans Protégé)."""
        self.graph = Graph()
        self.load_graph()
        return {"status": "ok", "triples": len(self.graph), "path": self.rdf_path}

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

    # ── Module HIBA : PERSONNES (Agent, Assure, Beneficiaire, Expert) ─────────
    def get_personnes(self, role: str | None = None) -> List[Dict[str, Any]]:
        filter_clause = ""
        if role:
            filter_clause = f"FILTER(contains(str(?type), '{role}') || contains(str(?personne), '{role}'))"

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
                pid_clean = p["personne"].replace('_', ' ').replace('-', ' ').strip()
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
            (AS.nom,       'nom'),
            (AS.prenom,    'prenom'),
            (AS.cin,       'cin'),
            (AS.telephone, 'telephone'),
            (AS.adresse,   'adresse'),
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
        for role_name in ['Assure', 'Agent', 'Expert', 'Beneficiaire', 'Admin']:
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
        return [c for c in raw_contrats if c.get("contrat") and not c["contrat"].endswith("Property") and c["contrat"] not in ["numeroContrat", "souscritContrat"]]

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
        if data.get("montantPrime") is not None:
            self.graph.add((c_uri, AS.montantPrime, Literal(float(data["montantPrime"]), datatype=XSD.float)))
        if data.get("franchise") is not None:
            self.graph.add((c_uri, AS.montantFranchise, Literal(float(data["franchise"]), datatype=XSD.float)))
        if data.get("habitation"):
            self.graph.add((c_uri, AS.typeHabitation, Literal(data["habitation"], datatype=XSD.string)))
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
            self.graph.add((c_uri, AS.numeroContrat, Literal(data["numeroContrat"], datatype=XSD.string)))

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
            self.graph.add((c_uri, AS.montantPrime, Literal(float(data["montantPrime"]), datatype=XSD.float)))
        if data.get("franchise") is not None:
            self.graph.remove((c_uri, AS.montantFranchise, None))
            self.graph.add((c_uri, AS.montantFranchise, Literal(float(data["franchise"]), datatype=XSD.float)))

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
            self.graph.add((c_uri, AS.typeHabitation, Literal(data["habitation"], datatype=XSD.string)))
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
        triples_to_remove = list(self.graph.triples((c_uri, None, None))) + list(self.graph.triples((None, None, c_uri)))
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
            return len([p for p in personnes
                        if role in (p.get('type') or '') or role in (p.get('personne') or '')])

        # Compter les classes disponibles
        classes = self.get_all_classes()

        return {
            "module": "Système d'Assurance Habitation (Personnes & Contrats)",
            "personnes_count": len(personnes),
            "contrats_count": len(contrats),
            "assures_count": count_role('Assure'),
            "agents_count": count_role('Agent'),
            "experts_count": count_role('Expert'),
            "beneficiaires_count": count_role('Beneficiaire'),
            "classes_count": len(classes),
            "total_triples": len(self.graph),
            "sparql_examples_count": len(SPARQL_EXAMPLES),
            "ontology_uri": "http://www.semanticweb.org/asus/ontologies/2026/8/Assuarnce_et_Gestion_des_Sinistres",
            "rdf_format": "OWL/RDF XML (Protégé)",
        }


ontology_service = OntologyService()
