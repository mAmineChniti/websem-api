"""
Routes FastAPI pour la gestion des Déclarations de Sinistre.
Module Déclarations & Documents.
"""

from typing import Any, Optional
from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.services.declaration_service import declaration_service

router = APIRouter(prefix="/declarations", tags=["declarations"])


class DeclarationCreateRequest(BaseModel):
    id: Optional[str] = Field(None, description="Identifiant unique optionnel (ex: Declaration_1)")
    statut: str = Field("En cours", description="Statut (En cours, Acceptée, Rejetée)")
    dateDeclaration: Optional[str] = Field(None, description="Date de déclaration ISO (ex: 2026-11-04T12:00:00)")
    sinistre_id: Optional[str] = Field(None, description="Identifiant du sinistre lié (ex: Sinistre1)")
    documents: list[str] = Field(default_factory=list, description="Liste d'identifiants de documents justificatifs")


class DeclarationUpdateRequest(BaseModel):
    statut: Optional[str] = Field(None, description="Nouveau statut")
    dateDeclaration: Optional[str] = Field(None, description="Date de déclaration")
    sinistre_id: Optional[str] = Field(None, description="Sinistre associé")
    documents: Optional[list[str]] = Field(None, description="Liste des documents associés")


class DeclarationStatutUpdateRequest(BaseModel):
    statut: str = Field(..., description="Nouveau statut (En cours, Acceptée, Rejetée)")


class LinkDocumentRequest(BaseModel):
    document_id: str = Field(..., description="Identifiant du document à lier")


@router.get("", summary="Lister les déclarations")
def list_declarations(
    statut: Optional[str] = Query(None, description="Filtrer par statut"),
    sinistre: Optional[str] = Query(None, description="Filtrer par identifiant de sinistre"),
) -> list[dict[str, Any]]:
    return declaration_service.get_all_declarations(statut_filter=statut, sinistre_filter=sinistre)


@router.get("/{declaration_id}", summary="Détail d'une déclaration")
def get_declaration(declaration_id: str) -> dict[str, Any]:
    try:
        decl = declaration_service.get_declaration(declaration_id)
        if not decl:
            raise HTTPException(status_code=404, detail=f"Déclaration '{declaration_id}' introuvable")
        return decl
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("", status_code=status.HTTP_201_CREATED, summary="Créer une déclaration")
def create_declaration(payload: DeclarationCreateRequest) -> dict[str, Any]:
    try:
        return declaration_service.create_declaration(payload.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/{declaration_id}/statut", summary="Mettre à jour le statut d'une déclaration")
def update_statut(declaration_id: str, payload: DeclarationStatutUpdateRequest) -> dict[str, Any]:
    try:
        updated = declaration_service.update_declaration_statut(declaration_id, payload.statut)
        if not updated:
            raise HTTPException(status_code=404, detail=f"Déclaration '{declaration_id}' introuvable")
        return updated
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/{declaration_id}", summary="Modifier une déclaration")
def update_declaration(declaration_id: str, payload: DeclarationUpdateRequest) -> dict[str, Any]:
    try:
        data = {k: v for k, v in payload.model_dump().items() if v is not None}
        updated = declaration_service.update_declaration(declaration_id, data)
        if not updated:
            raise HTTPException(status_code=404, detail=f"Déclaration '{declaration_id}' introuvable")
        return updated
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{declaration_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Supprimer une déclaration")
def delete_declaration(declaration_id: str) -> None:
    try:
        deleted = declaration_service.delete_declaration(declaration_id)
        if not deleted:
            raise HTTPException(status_code=404, detail=f"Déclaration '{declaration_id}' introuvable")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{declaration_id}/documents", summary="Lier un document à une déclaration")
def link_document_to_declaration(declaration_id: str, payload: LinkDocumentRequest) -> dict[str, Any]:
    try:
        success = declaration_service.link_document(declaration_id, payload.document_id)
        if not success:
            raise HTTPException(
                status_code=400,
                detail=f"Impossible de lier le document '{payload.document_id}' à la déclaration '{declaration_id}'"
            )
        return {"message": "Document lié avec succès", "declaration_id": declaration_id, "document_id": payload.document_id}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{declaration_id}/documents/{document_id}", summary="Détacher un document d'une déclaration")
def unlink_document_from_declaration(declaration_id: str, document_id: str) -> dict[str, Any]:
    try:
        success = declaration_service.unlink_document(declaration_id, document_id)
        if not success:
            raise HTTPException(
                status_code=400,
                detail=f"Impossible de détacher le document '{document_id}' de la déclaration '{declaration_id}'"
            )
        return {"message": "Document détaché avec succès"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

