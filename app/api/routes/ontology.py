from pathlib import Path
from typing import Any, Dict, Optional
from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel

from app.services.ontology_service import ontology_service
from app.services.nlp_sparql import nlp_translator
from app.services.auth_service import auth_service

router = APIRouter(prefix="/ontology", tags=["ontology_hiba"])

# ── Auth Schemas ──────────────────────────────────────────────────────────────
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

# ── Person / Contract Schemas ─────────────────────────────────────────────────
class PersonneCreateRequest(BaseModel):
    role: str = "Assure"  # Assure, Agent, Expert, Beneficiaire
    nom: str
    prenom: str
    cin: str
    telephone: str
    adresse: str

class PersonneUpdateRequest(BaseModel):
    nom: str = ""
    prenom: str = ""
    cin: str = ""
    telephone: str = ""
    adresse: str = ""

class ChangeRoleRequest(BaseModel):
    new_role: str  # Assure, Agent, Expert, Beneficiaire

class ContratCreateRequest(BaseModel):
    type: str = "ContratProprietaire"
    numeroContrat: str
    dateDebut: str
    dateFin: str
    montantPrime: float
    assure: str = "Assure1"
    habitation: Optional[str] = "Maison"
    garanties: Optional[str] = "Incendie"
    beneficiaire: Optional[str] = None
    franchise: Optional[float] = 150.0

class ContratUpdateRequest(BaseModel):
    type: Optional[str] = None
    numeroContrat: Optional[str] = None
    dateDebut: Optional[str] = None
    dateFin: Optional[str] = None
    montantPrime: Optional[float] = None
    assure: Optional[str] = None
    habitation: Optional[str] = None
    garanties: Optional[str] = None
    beneficiaire: Optional[str] = None
    franchise: Optional[float] = None

class SPARQLQueryRequest(BaseModel):
    query: str

class NLPQuestionRequest(BaseModel):
    question: str

# ── 0. RECHARGEMENT ONTOLOGIE (après modification Protégé) ─────────────────────
@router.post("/reload")
def reload_ontology():
    """Recharge l'ontologie depuis le fichier assurance.rdf (après modification dans Protégé)."""
    try:
        result = ontology_service.reload_graph()
        return {"message": "Ontologie rechargée avec succès", **result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ── 1. AUTHENTIFICATION ───────────────────────────────────────────────────────
@router.post("/auth/register")
def register(req: RegisterRequest):
    try:
        safe_data = req.model_dump()
        safe_data["role"] = "Assure"
        res = auth_service.register(safe_data)
        ontology_service.add_personne({
            "id": res["user"]["ontology_id"],
            "role": "Assure",
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

# ── 2. MODULE HIBA : PERSONNES ────────────────────────────────────────────────
@router.get("/personnes")
def get_personnes(role: Optional[str] = None):
    return ontology_service.get_personnes(role)

@router.post("/personnes")
def create_personne(req: PersonneCreateRequest):
    p_id = ontology_service.add_personne(req.model_dump())
    return {"status": "success", "message": f"Personne {p_id} ajoutée à l'ontologie", "id": p_id}

@router.put("/personnes/{personne_id}")
def update_personne(personne_id: str, req: PersonneUpdateRequest):
    try:
        success = ontology_service.update_personne(personne_id, req.model_dump())
        if not success:
            raise HTTPException(status_code=404, detail=f"Personne {personne_id} non trouvee dans l'ontologie")
        return {"status": "success", "message": f"Personne {personne_id} mise a jour"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.delete("/personnes/{personne_id}")
def delete_personne(personne_id: str):
    try:
        success = ontology_service.delete_personne(personne_id)
        if not success:
            raise HTTPException(status_code=404, detail=f"Personne {personne_id} non trouvee")
        try:
            auth_service.delete_user_by_ontology_id(personne_id)
        except Exception:
            pass
        return {"status": "success", "message": f"Personne {personne_id} supprimee"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.patch("/personnes/{personne_id}/role")
def change_role_personne(personne_id: str, req: ChangeRoleRequest):
    try:
        success = ontology_service.change_role_personne(personne_id, req.new_role)
        if not success:
            raise HTTPException(status_code=404, detail=f"Personne {personne_id} non trouvee")
        try:
            auth_service.update_user_role(personne_id, req.new_role)
        except Exception:
            pass
        return {"status": "success", "message": f"Role de {personne_id} change en {req.new_role}"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

# ── 3. MODULE HIBA : CONTRATS ─────────────────────────────────────────────────
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

# ── 4. STATS ──────────────────────────────────────────────────────────────────
@router.get("/stats")
def get_stats():
    return ontology_service.get_stats()

# ── 5. SPARQL DIRECT ─────────────────────────────────────────────────────────
@router.post("/sparql")
def execute_sparql(req: SPARQLQueryRequest):
    try:
        return ontology_service.execute_sparql(req.query)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/sparql/examples")
def get_sparql_examples():
    """Retourne la bibliothèque de requêtes SPARQL exemples (12 requêtes commentées)."""
    return ontology_service.get_sparql_examples()

# ── 6. NLP / TALN ─────────────────────────────────────────────────────────────
@router.post("/nlp/ask")
def ask_nlp(req: NLPQuestionRequest):
    """
    Traduit une question en langage naturel français en requête SPARQL.
    Pipeline : NLTK tokenisation → spaCy NER → Intent matching → SPARQL
    """
    try:
        return nlp_translator.translate_to_sparql(req.question)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/nlp/intents")
def get_nlp_intents():
    """Liste toutes les intentions NLP disponibles dans le traducteur."""
    return {
        "total": len(nlp_translator.get_available_intents()),
        "intents": nlp_translator.get_available_intents(),
        "pipeline_description": [
            "Étape 1 — NLTK : word_tokenize (fr) + stopwords français + SnowballStemmer",
            "Étape 2 — spaCy fr_core_news_sm : NER (entités nommées) + POS tagging",
            "Étape 3 — Intent Matcher : score sur mots-clés et stems → SPARQL ciblé",
        ],
        "libraries": ["NLTK 3.x", "spaCy 3.x (fr_core_news_sm)", "rdflib 7.x"],
    }

# ── 7. EXPLORATION ONTOLOGIQUE ────────────────────────────────────────────────
@router.get("/classes")
def get_all_classes():
    """Retourne la hiérarchie des classes OWL de l'ontologie."""
    return ontology_service.get_all_classes()

@router.get("/classes/{class_name}/instances")
def get_class_instances(class_name: str):
    """Retourne les individus d'une classe donnée."""
    return ontology_service.get_class_instances(class_name)

@router.get("/properties/object")
def get_object_properties():
    """Retourne toutes les ObjectProperty de l'ontologie."""
    return ontology_service.get_object_properties()

@router.get("/properties/datatype")
def get_data_properties():
    """Retourne toutes les DataProperty de l'ontologie."""
    return ontology_service.get_data_properties()

# ── 8. PROMOTIONS (Assuré → Agent) ───────────────────────────────────────────
import os
import json as _json

PROMOTIONS_FILE = str(Path(__file__).resolve().parent.parent.parent.parent / "promotions.json")

def _load_promotions():
    if os.path.exists(PROMOTIONS_FILE):
        with open(PROMOTIONS_FILE, 'r', encoding='utf-8') as _f:
            return _json.load(_f)
    return []

def _save_promotions(data):
    with open(PROMOTIONS_FILE, 'w', encoding='utf-8') as _f:
        _json.dump(data, _f, ensure_ascii=False, indent=2)

class PromotionRequest(BaseModel):
    ontology_id: str
    current_name: str
    requested_role: str
    message: str = ""

@router.get("/promotions")
def get_promotions():
    """Admin: get all pending promotion requests"""
    return _load_promotions()

@router.post("/promotions")
def submit_promotion(req: PromotionRequest):
    """Assure: submit a request to become Agent"""
    promos = _load_promotions()
    existing = [p for p in promos if p["ontology_id"] == req.ontology_id and p["status"] == "pending"]
    if existing:
        raise HTTPException(status_code=409, detail="Une demande est deja en cours pour cet utilisateur")
    import time
    entry = {
        "id": f"promo_{int(time.time())}",
        "ontology_id": req.ontology_id,
        "current_name": req.current_name,
        "requested_role": req.requested_role,
        "message": req.message,
        "status": "pending",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    }
    promos.append(entry)
    _save_promotions(promos)
    return {"status": "submitted", "id": entry["id"]}

@router.patch("/promotions/{promo_id}/approve")
def approve_promotion(promo_id: str):
    """Admin: approve a promotion request"""
    promos = _load_promotions()
    promo = next((p for p in promos if p["id"] == promo_id), None)
    if not promo:
        raise HTTPException(status_code=404, detail="Demande non trouvee")
    promo["status"] = "approved"
    _save_promotions(promos)
    try:
        ontology_service.change_role_personne(promo["ontology_id"], promo["requested_role"])
        auth_service.update_user_role(promo["ontology_id"], promo["requested_role"])
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur lors du changement de role: {e}")
    return {"status": "approved", "new_role": promo["requested_role"]}

@router.patch("/promotions/{promo_id}/reject")
def reject_promotion(promo_id: str):
    """Admin: reject a promotion request"""
    promos = _load_promotions()
    promo = next((p for p in promos if p["id"] == promo_id), None)
    if not promo:
        raise HTTPException(status_code=404, detail="Demande non trouvee")
    promo["status"] = "rejected"
    _save_promotions(promos)
    return {"status": "rejected"}
