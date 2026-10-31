from typing import Any, Dict, Optional
from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel

from app.services.ontology_service import ontology_service
from app.services.nlp_sparql import nlp_translator
from app.services.auth_service import auth_service

router = APIRouter(prefix="/ontology", tags=["ontology_hiba"])

# Auth Schemas
class RegisterRequest(BaseModel):
    email: str
    password: str
    nom: str
    prenom: str
    cin: str
    telephone: str
    adresse: str
    role: str = "Assure"

class LoginRequest(BaseModel):
    email: str
    password: str

# Contract & Person Schemas
class PersonneCreateRequest(BaseModel):
    role: str = "Assure" # Assure, Agent, Expert, Beneficiaire
    nom: str
    prenom: str
    cin: str
    telephone: str
    adresse: str

class ContratCreateRequest(BaseModel):
    type: str = "ContratProprietaire" # ContratProprietaire, ContratLocataire, ContratCopropriete
    numeroContrat: str
    dateDebut: str
    dateFin: str
    montantPrime: float
    assure: str = "Assure1"

class SPARQLQueryRequest(BaseModel):
    query: str

class NLPQuestionRequest(BaseModel):
    question: str

# 1. AUTHENTICATION & SECURITY (Role based)
@router.post("/auth/register")
def register(req: RegisterRequest):
    try:
        res = auth_service.register(req.model_dump())
        # Sync with ontology
        ontology_service.add_personne({
            "id": res["user"]["ontology_id"],
            "role": req.role,
            "nom": req.nom,
            "prenom": req.prenom,
            "cin": req.cin,
            "telephone": req.telephone,
            "adresse": req.adresse
        })
        return res
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/auth/login")
def login(req: LoginRequest):
    try:
        return auth_service.login(req.email, req.password)
    except Exception as e:
        raise HTTPException(status_code=401, detail=str(e))

@router.get("/auth/me")
def get_current_user(authorization: Optional[str] = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail="Token manquant")
    token = authorization.replace("Bearer ", "")
    user = auth_service.get_current_user(token)
    if not user:
        raise HTTPException(status_code=401, detail="Session invalide ou expirée")
    return user

# 2. MODULE HIBA : PERSONNES
@router.get("/personnes")
def get_personnes(role: Optional[str] = None):
    return ontology_service.get_personnes(role)

@router.post("/personnes")
def create_personne(req: PersonneCreateRequest):
    p_id = ontology_service.add_personne(req.model_dump())
    return {"status": "success", "message": f"Personne {p_id} ajoutée à l'ontologie", "id": p_id}

# 3. MODULE HIBA : CONTRATS (CRUD)
@router.get("/contrats")
def get_contrats(type_filter: Optional[str] = None):
    return ontology_service.get_contrats(type_filter)

@router.post("/contrats")
def create_contrat(req: ContratCreateRequest):
    c_id = ontology_service.add_contrat(req.model_dump())
    return {"status": "success", "message": f"Contrat {c_id} créé dans l'ontologie", "id": c_id}

@router.delete("/contrats/{contrat_id}")
def delete_contrat(contrat_id: str):
    success = ontology_service.delete_contrat(contrat_id)
    if not success:
        raise HTTPException(status_code=404, detail="Contrat non trouvé dans l'ontologie")
    return {"status": "success", "message": f"Contrat {contrat_id} supprimé de l'ontologie"}

# 4. STATS & SPARQL
@router.get("/stats")
def get_stats():
    return ontology_service.get_stats()

@router.post("/sparql")
def execute_sparql(req: SPARQLQueryRequest):
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
