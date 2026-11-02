import os
import re
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

import rdflib
from rdflib import OWL, RDF, RDFS, XSD, Graph, Literal, Namespace

# Lock global pour sérialiser l'analyse des requêtes SPARQL (pyparsing n'étant pas thread-safe dans rdflib)
# RLock : save_graph() peut être appelé depuis execute_sparql() qui détient déjà le verrou.
_sparql_lock = threading.RLock()
_IDENTIFIER_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")


def _sparql_string(value: Any) -> str:
    """Échappe une valeur pour l'insérer dans un littéral SPARQL entre guillemets."""
    return str(value).replace("\\", "\\\\").replace('"', '\\"')


def _is_update_query(query: str) -> bool:
    """Détecte les opérations SPARQL Update (INSERT/DELETE/LOAD...)."""
    return bool(
        re.search(
            r"\b(?:INSERT\s+DATA|INSERT\s*\{|DELETE\s+DATA|DELETE\s*\{|DELETE\s+WHERE|"
            r"LOAD|CLEAR|CREATE|DROP|COPY|MOVE|ADD)\b",
            query,
            flags=re.IGNORECASE,
        )
    )


def _validate_identifier(identifier: str) -> str:
    if not _IDENTIFIER_RE.fullmatch(identifier):
        raise ValueError("Identifiant ontologique invalide")
    return identifier


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
        "id": "ex02",
        "title": "Compter les personnes par rôle (GROUP BY + COUNT)",
        "category": "Statistiques",
        "difficulty": "Intermédiaire",
        "description": "Compte le nombre d'individus pour chaque rôle (Assuré, Agent, Expert...)",
        "query": """\
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
    {
        "id": "ex03",
        "title": "Contrats avec prime élevée (FILTER numérique)",
        "category": "Contrats",
        "difficulty": "Intermédiaire",
        "description": "Filtre les contrats dont la prime annuelle dépasse 500 DT",
        "query": """\
SELECT DISTINCT ?contrat ?typeContrat ?numeroContrat ?montantPrime ?assure WHERE {
    ?contrat a owl:NamedIndividual ;
             a ?typeContrat .
    FILTER(?typeContrat != owl:NamedIndividual && contains(str(?typeContrat), 'Contrat'))
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
    ?sinistre a owl:NamedIndividual ;
              a ?typeSinistre .
    FILTER(?typeSinistre != owl:NamedIndividual && contains(str(?typeSinistre), 'Sinistre'))
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
    ?contrat a owl:NamedIndividual ;
             a ?typeContrat .
    FILTER(?typeContrat != owl:NamedIndividual && contains(str(?typeContrat), 'Contrat'))
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
    FILTER(!isBlank(?classe))
    FILTER(STRSTARTS(STR(?classe), STR(as:)) || STRSTARTS(STR(?classe), STR(unt:)))
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
    FILTER(STRSTARTS(STR(?propriete), STR(as:)))
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
    FILTER(STRSTARTS(STR(?propriete), STR(as:)))
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
    ?contrat a owl:NamedIndividual ;
             a ?typeContrat .
    FILTER(?typeContrat != owl:NamedIndividual && contains(str(?typeContrat), 'Contrat'))
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
    ?garantie a owl:NamedIndividual ;
              a ?typeGarantie .
    FILTER(?typeGarantie != owl:NamedIndividual && contains(str(?typeGarantie), 'Garantie'))
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
    ?declaration a owl:NamedIndividual ;
                 a ?typeDeclaration .
    FILTER(?typeDeclaration != owl:NamedIndividual && contains(str(?typeDeclaration), 'Declaration'))
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

    def execute_sparql(self, query: str) -> dict[str, Any]:
        """Exécute une requête SPARQL (SELECT/ASK) ou une mise à jour (INSERT/DELETE...)."""
        with _sparql_lock:
            full_query = query
            if "PREFIX" not in query.upper():
                full_query = DEFAULT_PREFIXES + "\n" + query

            # CRUD SPARQL : les opérations Update sont exécutées via graph.update()
            # puis persistées dans le fichier RDF.
            if _is_update_query(full_query):
                self.graph.update(full_query)
                self.graph.serialize(destination=self.rdf_path, format="xml")
                return {
                    "type": "UPDATE",
                    "message": "Mise à jour SPARQL exécutée et ontologie sauvegardée",
                    "total_triples": len(self.graph),
                    "query": query,
                }

            qres = self.graph.query(full_query)

            if hasattr(qres, "type") and qres.type == "ASK":
                return {"type": "ASK", "boolean": bool(qres)}

            if hasattr(qres, "type") and qres.type in {"CONSTRUCT", "DESCRIBE"}:
                return {
                    "type": qres.type,
                    "count": len(qres.graph),
                    "results": qres.graph.serialize(format="turtle"),
                    "query": query,
                }

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
    def get_personnes(self, role: str | None = None) -> list[dict[str, Any]]:
        filter_clause = ""
        if role:
            escaped_role = _sparql_string(role)
            filter_clause = (
                f'FILTER(contains(str(?type), "{escaped_role}") || '
                f'contains(str(?personne), "{escaped_role}"))'
            )

        q = f"""
        SELECT DISTINCT ?personne ?type ?nom ?prenom ?cin ?telephone ?adresse WHERE {{
            ?personne a owl:NamedIndividual .
            {{
                # Cas 1 : Individu avec type explicite (Assure, Agent, Expert, Beneficiaire, Personne)
                ?personne a ?type .
                FILTER(?type != owl:NamedIndividual)
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
                # Cas 2 : Individu lié à un contrat en tant qu'assuré
                {{ ?personne as:souscritContrat ?c }} UNION {{ ?c as:aPourAssure ?personne }}
                FILTER(!isBlank(?personne))
                BIND(unt:Assure AS ?type)
            }}
            UNION
            {{
                # Cas 3 : Expert lié à un sinistre
                ?s as:expertisePar ?personne .
                BIND(unt:Expert AS ?type)
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
        merged: dict[str, dict[str, Any]] = {}
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

    def add_personne(self, data: dict[str, Any]) -> str:
        role = data.get("role", "Assure")
        if role not in {"Assure", "Agent", "Expert", "Beneficiaire"}:
            raise ValueError("Rôle ontologique invalide")
        p_id = data.get("id") or f"{role}_{len(self.get_personnes()) + 1}"
        _validate_identifier(p_id)
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

    def update_personne(self, personne_id: str, data: dict[str, Any]) -> bool:
        """Update properties of an existing person in the RDF graph."""
        _validate_identifier(personne_id)
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
        _validate_identifier(personne_id)
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
        _validate_identifier(personne_id)
        if new_role not in {"Assure", "Agent", "Expert", "Beneficiaire"}:
            raise ValueError("Rôle ontologique invalide")
        p_uri = AS[personne_id]
        if (p_uri, RDF.type, OWL.NamedIndividual) not in self.graph:
            return False
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
    def get_contrats(self, type_filter: str | None = None) -> list[dict[str, Any]]:
        filter_clause = ""
        if type_filter:
            escaped_type = _sparql_string(type_filter)
            filter_clause = f'FILTER(contains(str(?typeContrat), "{escaped_type}"))'

        q = f"""
        SELECT DISTINCT ?contrat ?typeContrat ?numeroContrat ?dateDebut ?dateFin ?montantPrime ?franchise ?assure ?habitation ?garanties ?beneficiaire WHERE {{
            ?contrat a owl:NamedIndividual ;
                     a ?typeContrat .
            FILTER(?typeContrat != owl:NamedIndividual)
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

    def add_contrat(self, data: dict[str, Any]) -> str:
        c_id = data.get("id") or f"Contrat{len(self.get_contrats()) + 1}"
        _validate_identifier(c_id)
        c_uri = AS[c_id]
        c_type = data.get("type", "ContratProprietaire")
        if c_type not in {"Contrat", "ContratProprietaire", "ContratLocataire", "ContratCopropriete"}:
            raise ValueError("Type de contrat ontologique invalide")
        type_uri = UNT[c_type]

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

    def update_contrat(self, contrat_id: str, data: dict[str, Any]) -> bool:
        """Update properties and links of an existing contract in the RDF graph."""
        _validate_identifier(contrat_id)
        c_uri = AS[contrat_id]
        found = any(True for _ in self.graph.triples((c_uri, None, None)))
        if not found:
            return False

        # 1. Update contract type
        if data.get("type"):
            new_type = data["type"]
            if new_type not in {
                "Contrat",
                "ContratProprietaire",
                "ContratLocataire",
                "ContratCopropriete",
            }:
                raise ValueError("Type de contrat ontologique invalide")
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
        _validate_identifier(contrat_id)
        c_uri = AS[contrat_id]
        triples_to_remove = list(self.graph.triples((c_uri, None, None))) + list(
            self.graph.triples((None, None, c_uri))
        )
        for t in triples_to_remove:
            self.graph.remove(t)
        self.save_graph()
        return len(triples_to_remove) > 0

    # ── Module HIBA : SINISTRES ────────────────────────────────────────────────
    _SINISTRE_TYPES = {
        "SinistreIncendie",
        "SinistreVol",
        "SinistreDegatDesEaux",
        "SinistreBrisDeGlace",
        "SinistreCatastropheNaturelle",
    }

    def add_sinistre(self, data: dict[str, Any]) -> dict[str, Any]:
        """Ajoute un sinistre à l'ontologie."""
        type_name = data.get("type") or data.get("typeSinistre") or "SinistreIncendie"
        if type_name not in self._SINISTRE_TYPES:
            raise ValueError("Type de sinistre ontologique invalide")
        s_id = data.get("id") or f"Sinistre_{len(self.get_all_sinistres()) + 1}"
        _validate_identifier(s_id)
        s_uri = AS[s_id]
        type_uri = UNT[type_name]

        self.graph.add((s_uri, RDF.type, OWL.NamedIndividual))
        self.graph.add((s_uri, RDF.type, type_uri))
        if data.get("dateSinistre"):
            self.graph.add(
                (s_uri, AS.dateSinistre, Literal(data["dateSinistre"], datatype=XSD.dateTime))
            )
        if data.get("lieuSinistre"):
            self.graph.add(
                (s_uri, AS.lieuSinistre, Literal(data["lieuSinistre"], datatype=XSD.string))
            )
        if data.get("descriptionSinistre"):
            self.graph.add(
                (
                    s_uri,
                    AS.descriptionSinistre,
                    Literal(data["descriptionSinistre"], datatype=XSD.string),
                )
            )
        if data.get("causeSinistre"):
            self.graph.add(
                (s_uri, RDFS.comment, Literal(data["causeSinistre"], datatype=XSD.string))
            )

        # Le contrat n'est pas relié directement à un sinistre dans l'ontologie.
        # On passe par la propriété existante : Contrat aPourAssure Personne
        # et Personne declareSinistre Sinistre.
        assure_uri = None
        if data.get("assure"):
            assure_uri = AS[data["assure"]]
        elif data.get("contrat"):
            assure_uri = self.graph.value(AS[data["contrat"]], AS.aPourAssure)
        if assure_uri is not None:
            self.graph.add((s_uri, AS.estDeclarePar, assure_uri))
            self.graph.add((assure_uri, AS.declareSinistre, s_uri))

        self._ensure_declaration_for_sinistre(s_uri, statut=data.get("statut"))

        self.save_graph()
        return {"id": s_id, "type": type_name, "message": "Sinistre créé avec succès"}

    def _ensure_declaration_for_sinistre(self, sinistre_uri, statut: str | None = None):
        """Utilise la classe Declaration existante pour porter le statut d'un sinistre."""
        declaration = self.graph.value(sinistre_uri, AS.faitObjetDe)
        if declaration is None:
            declaration = AS[f"Declaration_{str(sinistre_uri).split('#')[-1]}"]
            self.graph.add((declaration, RDF.type, OWL.NamedIndividual))
            self.graph.add((declaration, RDF.type, UNT.DeclarationEnCours))
            self.graph.add((sinistre_uri, AS.faitObjetDe, declaration))
            self.graph.add(
                (
                    declaration,
                    AS.dateDeclaration,
                    Literal(datetime.now().isoformat(timespec="seconds"), datatype=XSD.dateTime),
                )
            )
        if statut:
            self.graph.remove((declaration, AS.statutDeclaration, None))
            self.graph.add(
                (declaration, AS.statutDeclaration, Literal(statut, datatype=XSD.string))
            )
            status_types = {
                "acceptee": UNT.DeclarationAcceptee,
                "rejetee": UNT.DeclarationRejetee,
                "en cours": UNT.DeclarationEnCours,
                "encours": UNT.DeclarationEnCours,
            }
            normalized_status = (
                statut.strip().casefold().replace("é", "e").replace("è", "e")
            )
            for status_type in (
                UNT.DeclarationAcceptee,
                UNT.DeclarationRejetee,
                UNT.DeclarationEnCours,
            ):
                self.graph.remove((declaration, RDF.type, status_type))
            self.graph.add(
                (
                    declaration,
                    RDF.type,
                    status_types.get(normalized_status, UNT.DeclarationEnCours),
                )
            )
        return declaration

    def get_all_sinistres(
        self,
        type_filter: str | None = None,
        statut: str | None = None,
        lieu: str | None = None,
        assure: str | None = None,
    ) -> list[dict[str, Any]]:
        """Retourne tous les sinistres, avec filtres SPARQL optionnels."""
        filters = []
        if type_filter:
            filters.append(f'CONTAINS(STR(?typeSinistre), "{_sparql_string(type_filter)}")')
        if statut:
            filters.append(f'CONTAINS(LCASE(STR(?statut)), "{_sparql_string(statut).lower()}")')
        if lieu:
            filters.append(f'CONTAINS(LCASE(STR(?lieuSinistre)), "{_sparql_string(lieu).lower()}")')
        if assure:
            filters.append(
                f'(CONTAINS(LCASE(STR(?assure)), "{_sparql_string(assure).lower()}") || '
                f'CONTAINS(LCASE(STR(?assureNom)), "{_sparql_string(assure).lower()}"))'
            )
        filter_block = "".join(f"\n            FILTER({f})" for f in filters)

        q = f"""
        SELECT DISTINCT ?sinistre ?typeSinistre ?dateSinistre ?lieuSinistre ?descriptionSinistre
               ?statut ?dateDeclaration ?causeSinistre ?contrat ?assure ?assureNom WHERE {{
            ?sinistre a owl:NamedIndividual ;
                      a ?typeSinistre .
            FILTER(?typeSinistre != owl:NamedIndividual && CONTAINS(STR(?typeSinistre), 'Sinistre'))
            OPTIONAL {{ ?sinistre as:dateSinistre ?dateSinistre }}
            OPTIONAL {{ ?sinistre as:lieuSinistre ?lieuSinistre }}
            OPTIONAL {{ ?sinistre as:descriptionSinistre ?descriptionSinistre }}
            OPTIONAL {{ ?sinistre rdfs:comment ?causeSinistre }}
            OPTIONAL {{ ?sinistre as:faitObjetDe ?declaration }}
            OPTIONAL {{ ?declaration as:statutDeclaration ?statut }}
            OPTIONAL {{ ?declaration as:dateDeclaration ?dateDeclaration }}
            OPTIONAL {{ ?sinistre as:estDeclarePar ?assure }}
            OPTIONAL {{ ?assure as:nom ?assureNom }}
            OPTIONAL {{ ?contrat as:aPourAssure ?assure }}
            {filter_block}
        }}
        ORDER BY ?sinistre
        """
        results = self.execute_sparql(q)["results"]
        # Déduplique par sinistre (plusieurs contrats peuvent être liés au même assuré)
        merged: dict[str, dict[str, Any]] = {}
        for row in results:
            sid = row.get("sinistre")
            if not sid:
                continue
            if sid not in merged:
                merged[sid] = dict(row)
            elif not merged[sid].get("contrat") and row.get("contrat"):
                merged[sid]["contrat"] = row["contrat"]
        return list(merged.values())

    def get_sinistre(self, ontology_id: str) -> dict[str, Any]:
        """Récupère un sinistre par son identifiant."""
        _validate_identifier(ontology_id)
        q = f"""
        SELECT DISTINCT ?sinistre ?typeSinistre ?dateSinistre ?lieuSinistre ?descriptionSinistre
               ?statut ?dateDeclaration ?causeSinistre ?contrat ?assure WHERE {{
            VALUES ?sinistre {{ <{AS[ontology_id]}> }}
            ?sinistre a owl:NamedIndividual ;
                      a ?typeSinistre .
            FILTER(?typeSinistre != owl:NamedIndividual && CONTAINS(STR(?typeSinistre), 'Sinistre'))
            OPTIONAL {{ ?sinistre as:dateSinistre ?dateSinistre }}
            OPTIONAL {{ ?sinistre as:lieuSinistre ?lieuSinistre }}
            OPTIONAL {{ ?sinistre as:descriptionSinistre ?descriptionSinistre }}
            OPTIONAL {{ ?sinistre rdfs:comment ?causeSinistre }}
            OPTIONAL {{ ?sinistre as:faitObjetDe ?declaration }}
            OPTIONAL {{ ?declaration as:statutDeclaration ?statut }}
            OPTIONAL {{ ?declaration as:dateDeclaration ?dateDeclaration }}
            OPTIONAL {{ ?sinistre as:estDeclarePar ?assure }}
            OPTIONAL {{ ?contrat as:aPourAssure ?assure }}
        }}
        """
        results = self.execute_sparql(q)
        return results["results"][0] if results["results"] else {}

    def update_sinistre(self, sinistre_id: str, data: dict[str, Any]) -> bool:
        """Met à jour les propriétés d'un sinistre existant."""
        _validate_identifier(sinistre_id)
        s_uri = AS[sinistre_id]
        exists = (s_uri, RDF.type, OWL.NamedIndividual) in self.graph
        if not exists:
            return False

        type_name = data.get("type") or data.get("typeSinistre")
        if type_name:
            if type_name not in self._SINISTRE_TYPES:
                raise ValueError("Type de sinistre ontologique invalide")
            type_uri = UNT[type_name]
            for old_type in list(self.graph.objects(s_uri, RDF.type)):
                if old_type != OWL.NamedIndividual:
                    self.graph.remove((s_uri, RDF.type, old_type))
            self.graph.add((s_uri, RDF.type, type_uri))
        if data.get("dateSinistre"):
            self.graph.remove((s_uri, AS.dateSinistre, None))
            self.graph.add(
                (s_uri, AS.dateSinistre, Literal(data["dateSinistre"], datatype=XSD.dateTime))
            )
        if data.get("lieuSinistre"):
            self.graph.remove((s_uri, AS.lieuSinistre, None))
            self.graph.add(
                (s_uri, AS.lieuSinistre, Literal(data["lieuSinistre"], datatype=XSD.string))
            )
        if data.get("descriptionSinistre"):
            self.graph.remove((s_uri, AS.descriptionSinistre, None))
            self.graph.add(
                (
                    s_uri,
                    AS.descriptionSinistre,
                    Literal(data["descriptionSinistre"], datatype=XSD.string),
                )
            )
        if data.get("causeSinistre"):
            self.graph.remove((s_uri, RDFS.comment, None))
            self.graph.add(
                (s_uri, RDFS.comment, Literal(data["causeSinistre"], datatype=XSD.string))
            )
        if "assure" in data or "contrat" in data:
            for old_a in list(self.graph.objects(s_uri, AS.estDeclarePar)):
                self.graph.remove((s_uri, AS.estDeclarePar, old_a))
                self.graph.remove((old_a, AS.declareSinistre, s_uri))
            assure_uri = AS[data["assure"]] if data.get("assure") else None
            if assure_uri is None and data.get("contrat"):
                assure_uri = self.graph.value(AS[data["contrat"]], AS.aPourAssure)
            if assure_uri is not None:
                self.graph.add((s_uri, AS.estDeclarePar, assure_uri))
                self.graph.add((assure_uri, AS.declareSinistre, s_uri))
        if "statut" in data:
            self._ensure_declaration_for_sinistre(s_uri, statut=data.get("statut"))

        self.save_graph()
        return True

    def delete_sinistre(self, ontology_id: str) -> bool:
        """Supprime un sinistre de l'ontologie et ses liens entrants/sortants."""
        _validate_identifier(ontology_id)
        s_uri = AS[ontology_id]
        triples = set(self.graph.triples((s_uri, None, None))) | set(
            self.graph.triples((None, None, s_uri))
        )
        if not triples:
            return False
        for t in triples:
            self.graph.remove(t)
        self.save_graph()
        return True

    # ── Module HIBA : GARANTIES ────────────────────────────────────────────────
    _GARANTIE_TYPES = {
        "GarantieIncendie",
        "GarantieVol",
        "GarantieDegatDesEaux",
        "GarantieBrisDeGlace",
        "GarantieCatastropheNaturelle",
        "GarantieResponsabiliteCivile",
    }

    def add_garantie(self, data: dict[str, Any]) -> dict[str, Any]:
        """Ajoute une garantie à l'ontologie."""
        g_id = data.get("id") or f"Garantie_{len(self.get_all_garanties()) + 1}"
        _validate_identifier(g_id)
        g_uri = AS[g_id]
        type_name = data.get("type") or data.get("typeGarantie") or "GarantieIncendie"
        if type_name not in self._GARANTIE_TYPES:
            type_name = "GarantieIncendie"
        type_uri = UNT[type_name]

        self.graph.add((g_uri, RDF.type, OWL.NamedIndividual))
        self.graph.add((g_uri, RDF.type, type_uri))
        if data.get("nomGarantie"):
            self.graph.add((g_uri, RDFS.label, Literal(data["nomGarantie"], datatype=XSD.string)))
        if data.get("plafondGarantie") is not None:
            self.graph.add(
                (
                    g_uri,
                    AS.plafondGarantie,
                    Literal(float(data["plafondGarantie"]), datatype=XSD.float),
                )
            )
        taux = data.get("tauxFranchise", data.get("franchise"))
        if taux is not None:
            self.graph.add((g_uri, AS.tauxFranchise, Literal(float(taux), datatype=XSD.float)))

        self.save_graph()
        return {"id": g_id, "type": type_name, "message": "Garantie créée avec succès"}

    def get_all_garanties(self) -> list[dict[str, Any]]:
        """Retourne toutes les garanties de l'ontologie."""
        q = """
        SELECT DISTINCT ?garantie ?typeGarantie ?nomGarantie ?plafondGarantie ?tauxFranchise WHERE {
            ?garantie a owl:NamedIndividual ;
                      a ?typeGarantie .
            FILTER(?typeGarantie != owl:NamedIndividual && contains(str(?typeGarantie), 'Garantie'))
            OPTIONAL { ?garantie rdfs:label ?nomGarantie }
            OPTIONAL { ?garantie as:plafondGarantie ?plafondGarantie }
            OPTIONAL { ?garantie as:tauxFranchise ?tauxFranchise }
        }
        ORDER BY ?garantie
        """
        results = self.execute_sparql(q)
        return results["results"]

    def get_garantie(self, ontology_id: str) -> dict[str, Any]:
        """Récupère une garantie par son identifiant."""
        _validate_identifier(ontology_id)
        q = f"""
        SELECT DISTINCT ?garantie ?typeGarantie ?nomGarantie ?plafondGarantie ?tauxFranchise WHERE {{
            VALUES ?garantie {{ <{AS[ontology_id]}> }}
            ?garantie a owl:NamedIndividual ;
                      a ?typeGarantie .
            FILTER(?typeGarantie != owl:NamedIndividual && contains(str(?typeGarantie), 'Garantie'))
            OPTIONAL {{ ?garantie rdfs:label ?nomGarantie }}
            OPTIONAL {{ ?garantie as:plafondGarantie ?plafondGarantie }}
            OPTIONAL {{ ?garantie as:tauxFranchise ?tauxFranchise }}
        }}
        """
        results = self.execute_sparql(q)
        return results["results"][0] if results["results"] else {}

    def update_garantie(self, garantie_id: str, data: dict[str, Any]) -> bool:
        """Met à jour les propriétés d'une garantie existante."""
        _validate_identifier(garantie_id)
        g_uri = AS[garantie_id]
        exists = (g_uri, RDF.type, OWL.NamedIndividual) in self.graph
        if not exists:
            return False

        type_name = data.get("type") or data.get("typeGarantie")
        if type_name:
            if type_name not in self._GARANTIE_TYPES:
                type_name = "GarantieIncendie"
            type_uri = UNT[type_name]
            for old_type in list(self.graph.objects(g_uri, RDF.type)):
                if old_type != OWL.NamedIndividual:
                    self.graph.remove((g_uri, RDF.type, old_type))
            self.graph.add((g_uri, RDF.type, type_uri))
        if data.get("nomGarantie"):
            self.graph.remove((g_uri, RDFS.label, None))
            self.graph.add((g_uri, RDFS.label, Literal(data["nomGarantie"], datatype=XSD.string)))
        if data.get("plafondGarantie") is not None:
            self.graph.remove((g_uri, AS.plafondGarantie, None))
            self.graph.add(
                (
                    g_uri,
                    AS.plafondGarantie,
                    Literal(float(data["plafondGarantie"]), datatype=XSD.float),
                )
            )
        taux = data.get("tauxFranchise", data.get("franchise"))
        if taux is not None:
            self.graph.remove((g_uri, AS.tauxFranchise, None))
            self.graph.add((g_uri, AS.tauxFranchise, Literal(float(taux), datatype=XSD.float)))

        self.save_graph()
        return True

    def delete_garantie(self, ontology_id: str) -> bool:
        """Supprime une garantie de l'ontologie et ses liens entrants/sortants."""
        _validate_identifier(ontology_id)
        g_uri = AS[ontology_id]
        triples = set(self.graph.triples((g_uri, None, None))) | set(
            self.graph.triples((None, None, g_uri))
        )
        if not triples:
            return False
        for t in triples:
            self.graph.remove(t)
        self.save_graph()
        return True

    # ── Module HIBA : DOCUMENTS ────────────────────────────────────────────────
    _DOCUMENT_TYPES = {
        "RapportExpertise",
        "PhotoDommage",
        "Facture",
        "Document",
    }

    def _link_document_sinistre(self, document_uri, sinistre_id: str | None) -> None:
        # Retire les liens existants via Declaration estJustifiePar Document
        for declaration in list(self.graph.subjects(AS.estJustifiePar, document_uri)):
            self.graph.remove((declaration, AS.estJustifiePar, document_uri))
        if sinistre_id:
            s_uri = AS[sinistre_id]
            declaration = self.graph.value(s_uri, AS.faitObjetDe)
            if declaration is None:
                declaration = AS[f"Declaration_{str(s_uri).split('#')[-1]}"]
                self.graph.add((declaration, RDF.type, OWL.NamedIndividual))
                self.graph.add((declaration, RDF.type, UNT.DeclarationEnCours))
                self.graph.add((s_uri, AS.faitObjetDe, declaration))
                self.graph.add(
                    (
                        declaration,
                        AS.dateDeclaration,
                        Literal(
                            datetime.now().isoformat(timespec="seconds"), datatype=XSD.dateTime
                        ),
                    )
                )
                self.graph.add(
                    (declaration, AS.statutDeclaration, Literal("En cours", datatype=XSD.string))
                )
            self.graph.add((declaration, AS.estJustifiePar, document_uri))

    def add_document(self, data: dict[str, Any]) -> dict[str, Any]:
        """Ajoute un document à l'ontologie."""
        d_id = data.get("id") or f"Document_{len(self.get_all_documents()) + 1}"
        _validate_identifier(d_id)
        d_uri = AS[d_id]
        type_name = data.get("type") or data.get("typeDocument") or "RapportExpertise"
        if type_name not in self._DOCUMENT_TYPES:
            type_name = "RapportExpertise"
        type_uri = UNT[type_name]

        self.graph.add((d_uri, RDF.type, OWL.NamedIndividual))
        self.graph.add((d_uri, RDF.type, type_uri))
        if data.get("nomFichier"):
            self.graph.add((d_uri, AS.nomFichier, Literal(data["nomFichier"], datatype=XSD.string)))
        if data.get("dateUpload"):
            self.graph.add(
                (d_uri, AS.dateUpload, Literal(data["dateUpload"], datatype=XSD.dateTime))
            )
        self._link_document_sinistre(d_uri, data.get("associeSinistre"))

        self.save_graph()
        return {"id": d_id, "type": type_name, "message": "Document créé avec succès"}

    def get_all_documents(self) -> list[dict[str, Any]]:
        """Retourne tous les documents de l'ontologie."""
        q = """
        SELECT DISTINCT ?document ?typeDocument ?nomFichier ?dateUpload ?associeSinistre WHERE {
            ?document a owl:NamedIndividual ;
                      a ?typeDocument .
            FILTER(?typeDocument != owl:NamedIndividual && contains(str(?typeDocument), 'Document')
                   || contains(str(?typeDocument), 'Rapport')
                   || contains(str(?typeDocument), 'Photo')
                   || contains(str(?typeDocument), 'Facture'))
            OPTIONAL { ?document as:nomFichier ?nomFichier }
            OPTIONAL { ?document as:dateUpload ?dateUpload }
            OPTIONAL { ?declaration as:estJustifiePar ?document . ?viaSinistre as:faitObjetDe ?declaration }
            BIND(COALESCE(?viaSinistre, "") AS ?associeSinistre)
        }
        ORDER BY ?document
        """
        results = self.execute_sparql(q)
        return results["results"]

    def get_document(self, ontology_id: str) -> dict[str, Any]:
        """Récupère un document par son identifiant."""
        _validate_identifier(ontology_id)
        q = f"""
        SELECT DISTINCT ?document ?typeDocument ?nomFichier ?dateUpload ?associeSinistre WHERE {{
            VALUES ?document {{ <{AS[ontology_id]}> }}
            ?document a owl:NamedIndividual ;
                      a ?typeDocument .
            FILTER(?typeDocument != owl:NamedIndividual && contains(str(?typeDocument), 'Document')
                   || contains(str(?typeDocument), 'Rapport')
                   || contains(str(?typeDocument), 'Photo')
                   || contains(str(?typeDocument), 'Facture'))
            OPTIONAL {{ ?document as:nomFichier ?nomFichier }}
            OPTIONAL {{ ?document as:dateUpload ?dateUpload }}
            OPTIONAL {{ ?declaration as:estJustifiePar ?document . ?viaSinistre as:faitObjetDe ?declaration }}
            BIND(COALESCE(?viaSinistre, "") AS ?associeSinistre)
        }}
        """
        results = self.execute_sparql(q)
        return results["results"][0] if results["results"] else {}

    def update_document(self, document_id: str, data: dict[str, Any]) -> bool:
        """Met à jour les propriétés d'un document existant."""
        _validate_identifier(document_id)
        d_uri = AS[document_id]
        exists = (d_uri, RDF.type, OWL.NamedIndividual) in self.graph
        if not exists:
            return False

        type_name = data.get("type") or data.get("typeDocument")
        if type_name:
            if type_name not in self._DOCUMENT_TYPES:
                type_name = "RapportExpertise"
            type_uri = UNT[type_name]
            for old_type in list(self.graph.objects(d_uri, RDF.type)):
                if old_type != OWL.NamedIndividual:
                    self.graph.remove((d_uri, RDF.type, old_type))
            self.graph.add((d_uri, RDF.type, type_uri))
        if data.get("nomFichier"):
            self.graph.remove((d_uri, AS.nomFichier, None))
            self.graph.add((d_uri, AS.nomFichier, Literal(data["nomFichier"], datatype=XSD.string)))
        if data.get("dateUpload"):
            self.graph.remove((d_uri, AS.dateUpload, None))
            self.graph.add(
                (d_uri, AS.dateUpload, Literal(data["dateUpload"], datatype=XSD.dateTime))
            )
        if "associeSinistre" in data:
            self._link_document_sinistre(d_uri, data["associeSinistre"])

        self.save_graph()
        return True

    def delete_document(self, ontology_id: str) -> bool:
        """Supprime un document de l'ontologie et ses liens entrants/sortants."""
        _validate_identifier(ontology_id)
        d_uri = AS[ontology_id]
        triples = set(self.graph.triples((d_uri, None, None))) | set(
            self.graph.triples((None, None, d_uri))
        )
        if not triples:
            return False
        for t in triples:
            self.graph.remove(t)
        self.save_graph()
        return True

    # ── Module HIBA : DOMMAGES ────────────────────────────────────────────────
    def add_dommage(self, data: dict[str, Any]) -> dict[str, Any]:
        """Ajoute un dommage à l'ontologie."""
        d_id = data.get("id") or f"Dommage_{len(self.get_all_dommages()) + 1}"
        _validate_identifier(d_id)
        d_uri = AS[d_id]
        type_name = data.get("type", "DommageMateriel")
        if type_name not in {
            "Dommage",
            "DommageCorporel",
            "DommageImmateriel",
            "DommageMateriel",
        }:
            raise ValueError("Type de dommage ontologique invalide")
        type_uri = UNT[type_name]

        self.graph.add((d_uri, RDF.type, OWL.NamedIndividual))
        self.graph.add((d_uri, RDF.type, type_uri))
        if data.get("description"):
            self.graph.add((d_uri, RDFS.comment, Literal(data["description"], datatype=XSD.string)))
        if data.get("niveauGravite"):
            self.graph.add(
                (d_uri, AS.niveauGravite, Literal(data["niveauGravite"], datatype=XSD.string))
            )
        if data.get("valeurBien") is not None:
            self.graph.add(
                (d_uri, AS.valeurBien, Literal(float(data["valeurBien"]), datatype=XSD.float))
            )
        if data.get("associeSinistre"):
            s_uri = AS[data["associeSinistre"]]
            self.graph.add((s_uri, AS.provoqueDommage, d_uri))

        self.save_graph()
        return {"id": d_id, "type": type_name, "message": "Dommage créé avec succès"}

    def get_all_dommages(self) -> list[dict[str, Any]]:
        """Retourne tous les dommages de l'ontologie."""
        q = """
        SELECT DISTINCT ?dommage ?typeDommage ?description ?niveauGravite ?valeurBien ?associeSinistre WHERE {
            ?dommage a owl:NamedIndividual ;
                      a ?typeDommage .
            FILTER(?typeDommage != owl:NamedIndividual && contains(str(?typeDommage), 'Dommage'))
            OPTIONAL { ?dommage rdfs:comment ?description }
            OPTIONAL { ?dommage as:niveauGravite ?niveauGravite }
            OPTIONAL { ?dommage as:valeurBien ?valeurBien }
            OPTIONAL { ?sinistre as:provoqueDommage ?dommage }
            BIND(COALESCE(?sinistre, "") AS ?associeSinistre)
        }
        ORDER BY ?dommage
        """
        results = self.execute_sparql(q)
        return results["results"]

    def get_dommage(self, ontology_id: str) -> dict[str, Any]:
        """Récupère un dommage par son identifiant."""
        _validate_identifier(ontology_id)
        q = f"""
        SELECT DISTINCT ?dommage ?typeDommage ?description ?niveauGravite ?valeurBien ?associeSinistre WHERE {{
            VALUES ?dommage {{ <{AS[ontology_id]}> }}
            ?dommage a ?typeDommage .
            FILTER(contains(str(?typeDommage), 'Dommage'))
            OPTIONAL {{ ?dommage rdfs:comment ?description }}
            OPTIONAL {{ ?dommage as:niveauGravite ?niveauGravite }}
            OPTIONAL {{ ?dommage as:valeurBien ?valeurBien }}
            OPTIONAL {{ ?sinistre as:provoqueDommage ?dommage }}
            BIND(COALESCE(?sinistre, "") AS ?associeSinistre)
        }}
        """
        results = self.execute_sparql(q)
        return results["results"][0] if results["results"] else {}

    def update_dommage(self, dommage_id: str, data: dict[str, Any]) -> bool:
        """Met à jour les propriétés d'un dommage existant."""
        _validate_identifier(dommage_id)
        d_uri = AS[dommage_id]
        exists = (d_uri, RDF.type, OWL.NamedIndividual) in self.graph
        if not exists:
            return False

        if data.get("typeDommage"):
            if data["typeDommage"] not in {
                "Dommage",
                "DommageCorporel",
                "DommageImmateriel",
                "DommageMateriel",
            }:
                raise ValueError("Type de dommage ontologique invalide")
            type_uri = UNT[data["typeDommage"]]
            self.graph.remove((d_uri, RDF.type, None))
            self.graph.add((d_uri, RDF.type, OWL.NamedIndividual))
            self.graph.add((d_uri, RDF.type, type_uri))
        if data.get("description"):
            self.graph.remove((d_uri, RDFS.comment, None))
            self.graph.add((d_uri, RDFS.comment, Literal(data["description"], datatype=XSD.string)))
        if data.get("niveauGravite"):
            self.graph.remove((d_uri, AS.niveauGravite, None))
            self.graph.add(
                (d_uri, AS.niveauGravite, Literal(data["niveauGravite"], datatype=XSD.string))
            )
        if data.get("valeurBien") is not None:
            self.graph.remove((d_uri, AS.valeurBien, None))
            self.graph.add(
                (d_uri, AS.valeurBien, Literal(float(data["valeurBien"]), datatype=XSD.float))
            )
        if "associeSinistre" in data:
            for old_s in list(self.graph.subjects(AS.provoqueDommage, d_uri)):
                self.graph.remove((old_s, AS.provoqueDommage, d_uri))
            if data["associeSinistre"]:
                s_uri = AS[data["associeSinistre"]]
                self.graph.add((s_uri, AS.provoqueDommage, d_uri))

        self.save_graph()
        return True

    def delete_dommage(self, ontology_id: str) -> bool:
        """Supprime un dommage de l'ontologie."""
        _validate_identifier(ontology_id)
        d_uri = AS[ontology_id]
        triples = list(self.graph.triples((d_uri, None, None)))
        if not triples:
            return False
        for t in triples:
            self.graph.remove(t)
        self.save_graph()
        return len(triples) > 0

    # ── Méthodes d'exploration ontologique ───────────────────────────────────
    def get_all_classes(self) -> list[dict[str, Any]]:
        """Retourne toutes les classes OWL de l'ontologie avec leur hiérarchie."""
        q = """
        SELECT DISTINCT ?classe ?superClasse WHERE {
            ?classe a owl:Class .
            FILTER(!isBlank(?classe) && (STRSTARTS(STR(?classe), STR(unt:)) || STRSTARTS(STR(?classe), STR(as:))))
            OPTIONAL { ?classe rdfs:subClassOf ?superClasse . FILTER(!isBlank(?superClasse)) }
        }
        ORDER BY ?superClasse ?classe
        """
        return self.execute_sparql(q)["results"]

    def get_class_instances(self, class_name: str) -> list[dict[str, Any]]:
        """Retourne tous les individus d'une classe donnée."""
        _validate_identifier(class_name)
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

    def get_object_properties(self) -> list[dict[str, Any]]:
        """Retourne toutes les ObjectProperty de l'ontologie."""
        q = """
        SELECT DISTINCT ?propriete WHERE {
            ?propriete a owl:ObjectProperty .
            FILTER(contains(str(?propriete), 'Assuarnce'))
        }
        ORDER BY ?propriete
        """
        return self.execute_sparql(q)["results"]

    def get_data_properties(self) -> list[dict[str, Any]]:
        """Retourne toutes les DataProperty de l'ontologie."""
        q = """
        SELECT DISTINCT ?propriete WHERE {
            ?propriete a owl:DatatypeProperty .
            FILTER(contains(str(?propriete), 'Assuarnce'))
        }
        ORDER BY ?propriete
        """
        return self.execute_sparql(q)["results"]

    def search(self, text: str, limit: int = 100) -> list[dict[str, Any]]:
        """Recherche textuelle dans les individus et leurs valeurs littérales."""
        term = _sparql_string(text.lower())
        q = f'''
        SELECT DISTINCT ?entite ?type ?propriete ?valeur WHERE {{
            ?entite a owl:NamedIndividual ;
                    a ?type .
            FILTER(?type != owl:NamedIndividual)
            ?entite ?propriete ?valeur .
            FILTER(isLiteral(?valeur))
            FILTER(
                CONTAINS(LCASE(STR(?valeur)), "{term}") ||
                CONTAINS(LCASE(STR(?entite)), "{term}") ||
                CONTAINS(LCASE(STR(?type)), "{term}")
            )
        }}
        ORDER BY ?entite
        LIMIT {int(limit)}
        '''
        return self.execute_sparql(q)["results"]

    def get_sparql_examples(self) -> list[dict[str, Any]]:
        """Retourne la bibliothèque des requêtes SPARQL exemples."""
        return SPARQL_EXAMPLES

    # ── Stats globales ────────────────────────────────────────────────────────
    def get_stats(self) -> dict[str, Any]:
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
            "total_triples": len(self.graph),
            "sparql_examples_count": len(SPARQL_EXAMPLES),
            "ontology_uri": "http://www.semanticweb.org/asus/ontologies/2026/8/Assuarnce_et_Gestion_des_Sinistres",
            "rdf_format": "OWL/RDF XML (Protégé)",
        }


ontology_service = OntologyService()
