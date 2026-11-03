"""
Routes FastAPI pour la gestion des Clauses (Module Montaha Trabelsi).
Ce module implémente le cycle de vie CRUD complet pour la classe Clause
et ses sous-classes (ClauseExclusion, ClauseFranchise, ClauseObligatoire).
"""

from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.services.ontology_service import ontology_service

router = APIRouter(prefix="/clauses", tags=["clause_montaha"])

# Sous-classes valides pour Clause dans Protégé
TYPES_CLAUSE_VALIDES = [
    "ClauseExclusion",
    "ClauseFranchise",
    "ClauseObligatoire",
]


# ── Modèles Pydantic ──────────────────────────────────────────────────────────


class ClauseCreate(BaseModel):
    """Schéma de création d'une clause contractuelle."""

    type_clause: str = Field(
        default="ClauseExclusion",
        description="Sous-classe ontologique (ClauseExclusion, ClauseFranchise, ClauseObligatoire)",
    )
    texte_clause: str = Field(
        ..., min_length=1, description="Texte juridique ou libellé de la clause"
    )
    description: str | None = Field(default="", description="Description explicative optionnelle")
    taux_franchise: float | None = Field(
        default=None,
        ge=0.0,
        le=100.0,
        description="Taux de franchise en % (applicable principalement pour ClauseFranchise)",
    )
    contrat_id: str | None = Field(
        default=None,
        description="Identifiant du Contrat auquel rattacher la clause (ex: Contrat1)",
    )


class ClauseUpdate(BaseModel):
    """Schéma de mise à jour d'une clause."""

    type_clause: str | None = None
    texte_clause: str | None = None
    description: str | None = None
    taux_franchise: float | None = None
    contrat_id: str | None = None


class ClauseResponse(BaseModel):
    """Schéma de réponse pour une clause."""

    id: str
    type: str
    texte_clause: str
    description: str | None = ""
    taux_franchise: float | None = None
    contrat: str | None = None


# ── Routes CRUD ───────────────────────────────────────────────────────────────


@router.get("/", response_model=list[ClauseResponse])
@router.get("", response_model=list[ClauseResponse])
def get_all_clauses(type_clause: str | None = None):
    """
    Récupère la liste de toutes les clauses depuis l'ontologie OWL/RDF.
    Filtre optionnel sur le type de clause.
    """
    try:
        clauses = ontology_service.get_clauses(type_filter=type_clause)
        return clauses
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la récupération des clauses: {str(e)}",
        ) from e


@router.get("/{clause_id}", response_model=ClauseResponse)
def get_clause_by_id(clause_id: str):
    """
    Récupère le détail d'une clause par son identifiant ontologique (ex: Clause1).
    Retourne 404 si la clause n'existe pas.
    """
    clause = ontology_service.get_clause_by_id(clause_id)
    if not clause:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Clause '{clause_id}' introuvable dans l'ontologie.",
        )
    return clause


@router.post("/", response_model=dict[str, Any], status_code=status.HTTP_201_CREATED)
@router.post("", response_model=dict[str, Any], status_code=status.HTTP_201_CREATED)
def create_clause(payload: ClauseCreate):
    """
    Crée un nouvel individu Clause dans l'ontologie OWL/RDF.
    Associe les propriétés textuelles et le rattachement au contrat.
    """
    if payload.type_clause not in TYPES_CLAUSE_VALIDES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Type de clause invalide '{payload.type_clause}'. "
                f"Valeurs acceptées : {TYPES_CLAUSE_VALIDES}"
            ),
        )

    # Vérification logique pour ClauseFranchise
    if payload.type_clause == "ClauseFranchise" and payload.taux_franchise is None:
        # On tolère mais on informe que c'est recommandé
        pass

    try:
        new_id = ontology_service.create_clause(payload.model_dump())
        return {
            "message": "Clause créée avec succès dans l'ontologie",
            "id": new_id,
            "clause": payload.model_dump(),
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la création de la clause: {str(e)}",
        ) from e


@router.put("/{clause_id}", response_model=dict[str, Any])
def update_clause(clause_id: str, payload: ClauseUpdate):
    """
    Met à jour une clause existante dans l'ontologie.
    Retourne 404 si la clause n'existe pas.
    """
    existing = ontology_service.get_clause_by_id(clause_id)
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Clause '{clause_id}' introuvable pour mise à jour.",
        )

    if payload.type_clause and payload.type_clause not in TYPES_CLAUSE_VALIDES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Type de clause invalide '{payload.type_clause}'.",
        )

    try:
        update_data = {k: v for k, v in payload.model_dump().items() if v is not None}
        success = ontology_service.update_clause(clause_id, update_data)
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Échec de la mise à jour pour la clause '{clause_id}'.",
            )
        updated_clause = ontology_service.get_clause_by_id(clause_id)
        return {
            "message": "Clause mise à jour avec succès",
            "id": clause_id,
            "clause": updated_clause,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la mise à jour de la clause: {str(e)}",
        ) from e


@router.delete("/{clause_id}", response_model=dict[str, Any])
def delete_clause(clause_id: str):
    """
    Supprime une clause de l'ontologie OWL/RDF.
    Retourne 404 si la clause n'existe pas.
    """
    existing = ontology_service.get_clause_by_id(clause_id)
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Clause '{clause_id}' introuvable pour suppression.",
        )

    try:
        success = ontology_service.delete_clause(clause_id)
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Impossible de supprimer la clause '{clause_id}'.",
            )
        return {
            "message": f"Clause '{clause_id}' supprimée avec succès de l'ontologie",
            "id": clause_id,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la suppression de la clause: {str(e)}",
        ) from e
