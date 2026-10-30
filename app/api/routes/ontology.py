from typing import Any, Dict
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services.ontology_service import ontology_service
from app.services.nlp_sparql import nlp_translator

router = APIRouter(prefix="/ontology", tags=["ontology"])

class SPARQLQueryRequest(BaseModel):
    query: str

class NLPQuestionRequest(BaseModel):
    question: str

class SinistreCreateRequest(BaseModel):
    id: str | None = None
    type: str = "SinistreDegatDesEaux"
    date: str | None = None
    description: str | None = None
    lieu: str | None = None
    assure: str = "Assure1"
    expert: str = "Expert1"

@router.get("/stats")
def get_stats() -> Dict[str, Any]:
    return ontology_service.get_stats()

@router.get("/sinistres")
def get_sinistres():
    return ontology_service.get_sinistres()

@router.post("/sinistres")
def create_sinistre(req: SinistreCreateRequest):
    sin_id = ontology_service.add_sinistre(req.model_dump(exclude_unset=True))
    return {"status": "success", "message": f"Sinistre {sin_id} cree dans l'ontologie", "id": sin_id}

@router.get("/assures")
def get_assures():
    return ontology_service.get_assures()

@router.get("/contrats")
def get_contrats():
    return ontology_service.get_contrats()

@router.post("/sparql")
def execute_custom_sparql(req: SPARQLQueryRequest):
    try:
        return ontology_service.execute_sparql(req.query)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/nlp/ask")
def ask_nlp(req: NLPQuestionRequest):
    try:
        return nlp_translator.translate_to_sparql(req.question)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
