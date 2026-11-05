
"""
Service métier pour la gestion des Déclarations de Sinistre dans l'ontologie.
Module CRUD Déclarations & Documents.
"""

from datetime import datetime
from typing import Any, Optional

from rdflib import OWL, RDF, XSD, Literal, URIRef

from app.services.ontology_service import (
    AS,
    UNT,
    _date_time_literal,
    _validate_identifier,
    ontology_service,
)


class DeclarationService:
    """Service gérant le cycle de vie des déclarations de sinistre."""

    STATUS_TYPE_MAP = {
        "en cours": UNT.DeclarationEnCours,
        "encours": UNT.DeclarationEnCours,
        "declara": UNT.DeclarationEnCours,
        "declare": UNT.DeclarationEnCours,
        "acceptee": UNT.DeclarationAcceptee,
        "accepte": UNT.DeclarationAcceptee,
        "rejetee": UNT.DeclarationRejetee,
        "rejete": UNT.DeclarationRejetee,
        "refuse": UNT.DeclarationRejetee,
    }

    STATUS_LABELS = {
        UNT.DeclarationEnCours: "En cours",
        UNT.DeclarationAcceptee: "Acceptée",
        UNT.DeclarationRejetee: "Rejetée",
    }

    def __init__(self):
        self.ont = ontology_service

    @property
    def graph(self):
        return self.ont.graph

    # ── Helpers ──────────────────────────────────────────────────────

    def _normalize_status(self, statut: str) -> str:
        return (
            statut.strip()
            .casefold()
            .replace("é", "e")
            .replace("è", "e")
        )

    def _next_declaration_id(self) -> str:
        index = len(self.get_all_declarations()) + 1

        while any(
            self.graph.triples(
                (AS[f"Declaration_{index}"], None, None)
            )
        ):
            index += 1

        return f"Declaration_{index}"

    def _get_type_uri_for_status(self, statut: str) -> URIRef:
        normalized = self._normalize_status(statut)
        type_uri = self.STATUS_TYPE_MAP.get(normalized)

        if type_uri is None:
            raise ValueError(
                f"Statut invalide : « {statut} ». "
                "Valeurs acceptées : En cours, Acceptée, Rejetée."
            )

        return type_uri

    def _resolve_sinistre(self, raw_id, allowed=None):
        """Retourne l'URI d'un sinistre existant."""
        if not raw_id:
            return None

        clean = str(raw_id).split("#")[-1]
        _validate_identifier(clean)

        sinistre_uri = AS[clean]

        if (
            sinistre_uri,
            RDF.type,
            OWL.NamedIndividual,
        ) not in self.graph:
            raise ValueError(f"Sinistre {clean} introuvable")

        existing = self.graph.value(sinistre_uri, AS.faitObjetDe)

        if existing is not None and existing != allowed:
            raise ValueError(
                f"Le sinistre {clean} possède déjà une déclaration "
                f"({str(existing).split('#')[-1]}). "
                "Modifiez-la au lieu d'en créer une autre."
            )

        return sinistre_uri

    def _resolve_document(self, raw_id):
        clean = str(raw_id).split("#")[-1]
        _validate_identifier(clean)

        document_uri = AS[clean]

        if (
            document_uri,
            RDF.type,
            OWL.NamedIndividual,
        ) not in self.graph:
            raise ValueError(f"Document {clean} introuvable")

        return document_uri

    def _set_statut(self, declaration_uri, type_uri):
        """Met à jour simultanément la classe OWL et le libellé du statut."""
        self.graph.remove(
            (declaration_uri, AS.statutDeclaration, None)
        )

        self.graph.add(
            (
                declaration_uri,
                AS.statutDeclaration,
                Literal(
                    self.STATUS_LABELS[type_uri],
                    datatype=XSD.string,
                ),
            )
        )

        for old_type in self.STATUS_LABELS:
            self.graph.remove(
                (declaration_uri, RDF.type, old_type)
            )

        self.graph.add(
            (declaration_uri, RDF.type, type_uri)
        )

    def _attach_document(self, declaration_uri, document_uri):
        """Un document ne justifie qu'une seule déclaration."""
        for other in list(
            self.graph.subjects(
                AS.estJustifiePar,
                document_uri,
            )
        ):
            if other != declaration_uri:
                self.graph.remove(
                    (other, AS.estJustifiePar, document_uri)
                )

        self.graph.add(
            (
                declaration_uri,
                AS.estJustifiePar,
                document_uri,
            )
        )

    def _is_declaration(self, declaration_uri) -> bool:
        if (
            declaration_uri,
            RDF.type,
            OWL.NamedIndividual,
        ) not in self.graph:
            return False

        return any(
            (
                declaration_uri,
                RDF.type,
                status_type,
            ) in self.graph
            for status_type in self.STATUS_LABELS
        ) or any(
            self.graph.triples(
                (declaration_uri, AS.statutDeclaration, None)
            )
        ) or any(
            self.graph.triples(
                (declaration_uri, AS.dateDeclaration, None)
            )
        )

    
    def _serialize_declaration(self, declaration_uri) -> dict[str, Any]:
        declaration_id = str(declaration_uri).split("#")[-1]

        date = self.graph.value(
            declaration_uri,
            AS.dateDeclaration,
        )

        statut = self.graph.value(
            declaration_uri,
            AS.statutDeclaration,
        )

        sinistre_uri = next(
            (
                subject
                for subject in self.graph.subjects(
                    AS.faitObjetDe,
                    declaration_uri,
                )
            ),
            None,
        )

        documents = list(
            self.graph.objects(
                declaration_uri,
                AS.estJustifiePar,
            )
        )

        type_uri = next(
            (
                t
                for t in self.STATUS_LABELS
                if (declaration_uri, RDF.type, t) in self.graph
            ),
            None,
        )

        if statut is None and type_uri is not None:
            statut_value = self.STATUS_LABELS[type_uri]
        else:
            statut_value = str(statut) if statut is not None else None

        sinistre_id = (
            str(sinistre_uri).split("#")[-1]
            if sinistre_uri is not None
            else ""
        )

        
        document_list = []

        for document_uri in documents:
            document_id = str(document_uri).split("#")[-1]

            nom_fichier = self.graph.value(
                document_uri,
                AS.nomFichier,
            )

            document_list.append({
                "id": document_id,
                "document": document_id,
                "nomFichier": (
                    str(nom_fichier)
                    if nom_fichier is not None
                    else document_id
                ),
            })


        return {
            "id": declaration_id,
            "declaration": declaration_id,
            "typeDeclaration": (
                str(type_uri).split("#")[-1]
                if type_uri is not None
                else None
            ),
            "dateDeclaration": str(date) if date is not None else None,
            "statut": statut_value,
            "sinistre": sinistre_id,
            "documents": document_list,
        }

    # ── CRUD Déclarations ───────────────────────────────────────────

    def get_all_declarations(
        self,
        statut_filter: Optional[str] = None,
        sinistre_filter: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """Retourne toutes les déclarations avec filtres optionnels."""

        declaration_uris = set()

        for status_type in self.STATUS_LABELS:
            declaration_uris.update(
                self.graph.subjects(RDF.type, status_type)
            )

        declaration_uris.update(
            self.graph.subjects(
                AS.statutDeclaration,
                None,
            )
        )

        declaration_uris.update(
            self.graph.subjects(
                AS.dateDeclaration,
                None,
            )
        )

        declaration_uris.update(
            self.graph.objects(
                None,
                AS.faitObjetDe,
            )
        )

        results = []

        for declaration_uri in declaration_uris:
            if not self._is_declaration(declaration_uri):
                continue

            declaration = self._serialize_declaration(
                declaration_uri
            )

            if statut_filter:
                current_status = (
                    declaration.get("statut") or ""
                ).casefold()

                if statut_filter.casefold() not in current_status:
                    continue

            if sinistre_filter:
                current_sinistre = (
                    declaration.get("sinistre") or ""
                ).casefold()

                if sinistre_filter.casefold() not in current_sinistre:
                    continue

            results.append(declaration)

        return sorted(
            results,
            key=lambda item: item["id"],
        )

    def get_declaration(
        self,
        declaration_id: str,
    ) -> dict[str, Any]:
        """Récupère une déclaration par son identifiant."""

        clean = declaration_id.split("#")[-1]
        _validate_identifier(clean)

        declaration_uri = AS[clean]

        if not self._is_declaration(declaration_uri):
            return {}

        return self._serialize_declaration(declaration_uri)

    def create_declaration(
        self,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        """Crée une déclaration et ses relations RDF."""

        declaration_id = (
            data.get("id") or self._next_declaration_id()
        )

        _validate_identifier(declaration_id)

        declaration_uri = AS[declaration_id]

        if any(
            self.graph.triples(
                (declaration_uri, None, None)
            )
        ):
            raise ValueError(
                f"La déclaration {declaration_id} existe déjà."
            )

        statut = data.get("statut", "En cours")
        type_uri = self._get_type_uri_for_status(statut)

        sinistre_uri = self._resolve_sinistre(
            data.get("sinistre_id")
        )

        document_uris = [
            self._resolve_document(document_id)
            for document_id in data.get("documents", [])
        ]

        date_value = data.get("dateDeclaration")

        if date_value:
            date_literal = _date_time_literal(date_value)
        else:
            date_literal = _date_time_literal(
                datetime.now()
            )

        self.graph.add(
            (declaration_uri, RDF.type, OWL.NamedIndividual)
        )

        self._set_statut(declaration_uri, type_uri)

        self.graph.add(
            (
                declaration_uri,
                AS.dateDeclaration,
                date_literal,
            )
        )

        if sinistre_uri is not None:
            self.graph.add(
                (
                    sinistre_uri,
                    AS.faitObjetDe,
                    declaration_uri,
                )
            )

        for document_uri in document_uris:
            self._attach_document(
                declaration_uri,
                document_uri,
            )

        self.ont.save_graph()

        return self.get_declaration(declaration_id)

    def update_declaration_statut(
        self,
        declaration_id: str,
        statut: str,
    ) -> Optional[dict[str, Any]]:
        """Modifie le statut d'une déclaration."""

        clean = declaration_id.split("#")[-1]
        _validate_identifier(clean)

        declaration_uri = AS[clean]

        if not self._is_declaration(declaration_uri):
            return None

        type_uri = self._get_type_uri_for_status(statut)

        self._set_statut(declaration_uri, type_uri)

        self.ont.save_graph()

        return self.get_declaration(clean)

    def update_declaration(
        self,
        declaration_id: str,
        data: dict[str, Any],
    ) -> Optional[dict[str, Any]]:
        """Modifie les informations d'une déclaration."""

        clean = declaration_id.split("#")[-1]
        _validate_identifier(clean)

        declaration_uri = AS[clean]

        if not self._is_declaration(declaration_uri):
            return None

        # Mise à jour du statut
        if data.get("statut"):
            type_uri = self._get_type_uri_for_status(
                data["statut"]
            )
            self._set_statut(
                declaration_uri,
                type_uri,
            )

        # Mise à jour de la date
        if data.get("dateDeclaration"):
            self.graph.remove(
                (declaration_uri, AS.dateDeclaration, None)
            )
            self.graph.add(
                (
                    declaration_uri,
                    AS.dateDeclaration,
                    _date_time_literal(data["dateDeclaration"]),
                )
            )

        # Mise à jour du sinistre associé
        if "sinistre_id" in data:
            new_sinistre = data.get("sinistre_id")

            new_sinistre_uri = self._resolve_sinistre(
                new_sinistre,
                allowed=declaration_uri,
            )

            for old_sinistre in list(
                self.graph.subjects(
                    AS.faitObjetDe,
                    declaration_uri,
                )
            ):
                self.graph.remove(
                    (
                        old_sinistre,
                        AS.faitObjetDe,
                        declaration_uri,
                    )
                )

            if new_sinistre_uri is not None:
                self.graph.add(
                    (
                        new_sinistre_uri,
                        AS.faitObjetDe,
                        declaration_uri,
                    )
                )

        # Remplacement de la liste des documents
        if "documents" in data:
            new_documents = [
                self._resolve_document(document_id)
                for document_id in data["documents"]
            ]

            self.graph.remove(
                (
                    declaration_uri,
                    AS.estJustifiePar,
                    None,
                )
            )

            for document_uri in new_documents:
                self._attach_document(
                    declaration_uri,
                    document_uri,
                )

        self.ont.save_graph()

        return self.get_declaration(clean)

    def delete_declaration(
        self,
        declaration_id: str,
    ) -> bool:
        """Supprime une déclaration sans supprimer ses sinistres ou documents."""

        clean = declaration_id.split("#")[-1]
        _validate_identifier(clean)

        declaration_uri = AS[clean]

        if not self._is_declaration(declaration_uri):
            return False

        triples = (
            set(
                self.graph.triples(
                    (declaration_uri, None, None)
                )
            )
            |
            set(
                self.graph.triples(
                    (None, None, declaration_uri)
                )
            )
        )

        for triple in triples:
            self.graph.remove(triple)

        self.ont.save_graph()

        return True

    # ── Gestion des documents justificatifs ─────────────────────────

    def link_document(
        self,
        declaration_id: str,
        document_id: str,
    ) -> bool:
        """Associe un document existant à une déclaration."""

        clean_declaration = declaration_id.split("#")[-1]
        _validate_identifier(clean_declaration)

        declaration_uri = AS[clean_declaration]

        if not self._is_declaration(declaration_uri):
            raise ValueError(
                f"Déclaration {clean_declaration} introuvable"
            )

        document_uri = self._resolve_document(document_id)

        self._attach_document(
            declaration_uri,
            document_uri,
        )

        self.ont.save_graph()

        return True

    def unlink_document(
        self,
        declaration_id: str,
        document_id: str,
    ) -> bool:
        """Détache un document d'une déclaration."""

        clean_declaration = declaration_id.split("#")[-1]
        clean_document = document_id.split("#")[-1]

        _validate_identifier(clean_declaration)
        _validate_identifier(clean_document)

        declaration_uri = AS[clean_declaration]
        document_uri = AS[clean_document]

        if not self._is_declaration(declaration_uri):
            raise ValueError(
                f"Déclaration {clean_declaration} introuvable"
            )

        if (
            declaration_uri,
            AS.estJustifiePar,
            document_uri,
        ) not in self.graph:
            return False

        self.graph.remove(
            (
                declaration_uri,
                AS.estJustifiePar,
                document_uri,
            )
        )

        self.ont.save_graph()

        return True


# Instance globale du service
declaration_service = DeclarationService()
