"""
Routes FastAPI pour la gestion des Dommages (Module Montaha Trabelsi).
Ce module implémente le cycle de vie CRUD complet pour la classe Dommage
et ses sous-classes (DommageMateriel, DommageCorporel, DommageImmateriel).
"""

from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.services.ontology_service import ontology_service

router = APIRouter(prefix="/dommages", tags=["dommage_montaha"])

# Types valides pour la classe Dommage dans l'ontologie Protégé
TYPES_DOMMAGE_VALIDES = [
    "DommageMateriel",
    "DommageCorporel",
    "DommageImmateriel",
    "DommageImmatériel",
]

# Niveaux de gravité supportés
NIVEAUX_GRAVITE_VALIDES = ["Faible", "Moyen", "Grave"]


# ── Modèles Pydantic ──────────────────────────────────────────────────────────


class DommageCreate(BaseModel):
    """Schéma de création d'un dommage."""

    type_dommage: str = Field(
        default="DommageMateriel",
        description="Sous-classe ontologique (DommageMateriel, DommageCorporel, DommageImmateriel)",
    )
    description: str = Field(..., min_length=1, description="Description du dommage")
    montant: float = Field(default=0.0, ge=0.0, description="Montant indemnisé / estimé")
    gravite: str = Field(default="Faible", description="Niveau de gravité (Faible, Moyen, Grave)")
    sinistre_id: str | None = Field(
        default=None, description="Identifiant du Sinistre lié (ex: Sinistre1)"
    )
    date: datetime | None = Field(default=None, description="Date du sinistre / dommage")
    lieu: str | None = Field(default=None, description="Lieu de survenance")


class DommageUpdate(BaseModel):
    """Schéma de mise à jour d'un dommage."""

    type_dommage: str | None = None
    description: str | None = None
    montant: float | None = None
    gravite: str | None = None
    sinistre_id: str | None = None
    date: datetime | None = None
    lieu: str | None = None


class DommageResponse(BaseModel):
    """Schéma de réponse pour un dommage."""

    id: str
    type: str
    description: str
    montant: float
    gravite: str
    sinistre: str | None = None
    date: str | None = None
    lieu: str | None = None


# ── Routes CRUD ───────────────────────────────────────────────────────────────


@router.get("/", response_model=list[DommageResponse])
@router.get("", response_model=list[DommageResponse])
def get_all_dommages(type_dommage: str | None = None):
    """
    Récupère la liste de tous les dommages depuis l'ontologie OWL/RDF.
    Permet un filtrage optionnel par sous-type.
    """
    try:
        dommages = ontology_service.get_dommages(type_filter=type_dommage)
        return dommages
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la récupération des dommages: {str(e)}",
        ) from e


@router.get("/{dommage_id}", response_model=DommageResponse)
def get_dommage_by_id(dommage_id: str):
    """
    Récupère le détail d'un dommage par son identifiant ontologique (ex: Dommage1).
    Retourne 404 si le dommage n'existe pas.
    """
    dommage = ontology_service.get_dommage_by_id(dommage_id)
    if not dommage:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Dommage '{dommage_id}' introuvable dans l'ontologie.",
        )
    return dommage


@router.post("/", response_model=dict[str, Any], status_code=status.HTTP_201_CREATED)
@router.post("", response_model=dict[str, Any], status_code=status.HTTP_201_CREATED)
def create_dommage(payload: DommageCreate):
    """
    Crée un nouvel individu Dommage dans l'ontologie OWL/RDF.
    Associe les propriétés de données et la relation vers le Sinistre correspondant.
    """
    # Validation du type
    if payload.type_dommage not in TYPES_DOMMAGE_VALIDES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Type de dommage invalide '{payload.type_dommage}'. "
                f"Valeurs acceptées : {TYPES_DOMMAGE_VALIDES}"
            ),
        )

    # Validation du niveau de gravité si spécifié
    if payload.gravite and payload.gravite not in NIVEAUX_GRAVITE_VALIDES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Niveau de gravité invalide '{payload.gravite}'. "
                f"Valeurs acceptées : {NIVEAUX_GRAVITE_VALIDES}"
            ),
        )

    try:
        new_id = ontology_service.create_dommage(payload.model_dump())
        return {
            "message": "Dommage créé avec succès dans l'ontologie",
            "id": new_id,
            "dommage": payload.model_dump(),
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la création du dommage: {str(e)}",
        ) from e


@router.put("/{dommage_id}", response_model=dict[str, Any])
def update_dommage(dommage_id: str, payload: DommageUpdate):
    """
    Met à jour les propriétés d'un dommage existant.
    Retourne 404 si l'individu n'existe pas.
    """
    existing = ontology_service.get_dommage_by_id(dommage_id)
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Dommage '{dommage_id}' introuvable pour mise à jour.",
        )

    if payload.type_dommage and payload.type_dommage not in TYPES_DOMMAGE_VALIDES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Type de dommage invalide '{payload.type_dommage}'.",
        )

    if payload.gravite and payload.gravite not in NIVEAUX_GRAVITE_VALIDES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Niveau de gravité invalide '{payload.gravite}'.",
        )

    try:
        # Filtrer les champs non renseignés (None)
        update_data = {k: v for k, v in payload.model_dump().items() if v is not None}
        success = ontology_service.update_dommage(dommage_id, update_data)
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Échec de la mise à jour pour le dommage '{dommage_id}'.",
            )
        updated_dommage = ontology_service.get_dommage_by_id(dommage_id)
        return {
            "message": "Dommage mis à jour avec succès",
            "id": dommage_id,
            "dommage": updated_dommage,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la mise à jour du dommage: {str(e)}",
        ) from e


@router.delete("/{dommage_id}", response_model=dict[str, Any])
def delete_dommage(dommage_id: str):
    """
    Supprime un dommage de l'ontologie OWL/RDF ainsi que tous ses triplets liés.
    Retourne 404 si l'individu n'existe pas.
    """
    existing = ontology_service.get_dommage_by_id(dommage_id)
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Dommage '{dommage_id}' introuvable pour suppression.",
        )

    try:
        success = ontology_service.delete_dommage(dommage_id)
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Impossible de supprimer le dommage '{dommage_id}'.",
            )
        return {
            "message": f"Dommage '{dommage_id}' supprimé avec succès de l'ontologie",
            "id": dommage_id,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la suppression du dommage: {str(e)}",
        ) from e
