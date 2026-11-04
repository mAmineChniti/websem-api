import json
import os
from pathlib import Path

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from app.services.auth_service import auth_service
from app.services.nlp_sparql import nlp_translator
from app.services.ontology_service import ontology_service

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
    habitation: str | None = "Maison"
    garanties: str | None = "Incendie"
    beneficiaire: str | None = None
    franchise: float | None = 150.0


class ContratUpdateRequest(BaseModel):
    type: str | None = None
    numeroContrat: str | None = None
    dateDebut: str | None = None
    dateFin: str | None = None
    montantPrime: float | None = None
    assure: str | None = None
    habitation: str | None = None
    garanties: str | None = None
    beneficiaire: str | None = None
    franchise: float | None = None


class SPARQLQueryRequest(BaseModel):
    query: str


class NLPQuestionRequest(BaseModel):
    question: str


class HabitationCreateRequest(BaseModel):
    type: str = "Appartement"
    adresse: str = ""
    superficie: float | None = None
    valeurBien: float | None = None


class HabitationUpdateRequest(BaseModel):
    type: str | None = None
    adresse: str | None = None
    superficie: float | None = None
    valeurBien: float | None = None


# ── 0. RECHARGEMENT ONTOLOGIE (après modification Protégé) ─────────────────────
@router.post("/reload")
def reload_ontology():
    """Recharge l'ontologie depuis le fichier assurance.rdf (après modification dans Protégé)."""
    try:
        result = ontology_service.reload_graph()
        return {"message": "Ontologie rechargée avec succès", **result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


# ── 1. AUTHENTIFICATION ───────────────────────────────────────────────────────
@router.post("/auth/register")
def register(req: RegisterRequest):
    try:
        safe_data = req.model_dump()
        safe_data["role"] = "Assure"
        res = auth_service.register(safe_data)
        ontology_service.add_personne(
            {
                "id": res["user"]["ontology_id"],
                "role": "Assure",
                "nom": req.nom,
                "prenom": req.prenom,
                "cin": req.cin,
                "telephone": req.telephone,
                "adresse": req.adresse,
            }
        )
        return res
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/auth/login")
def login(req: LoginRequest):
    try:
        return auth_service.login(req.email, req.password)
    except Exception as e:
        raise HTTPException(status_code=401, detail=str(e)) from e


@router.get("/auth/me")
def get_current_user(authorization: str | None = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail="Token manquant")
    token = authorization.replace("Bearer ", "")
    user = auth_service.get_current_user(token)
    if not user:
        raise HTTPException(status_code=401, detail="Session invalide ou expirée")
    return user


# ── 2. MODULE HIBA : PERSONNES ────────────────────────────────────────────────
@router.get("/personnes")
def get_personnes(role: str | None = None):
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
            raise HTTPException(
                status_code=404, detail=f"Personne {personne_id} non trouvee dans l'ontologie"
            )
        return {"status": "success", "message": f"Personne {personne_id} mise a jour"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


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
        raise HTTPException(status_code=400, detail=str(e)) from e


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
        raise HTTPException(status_code=400, detail=str(e)) from e


# ── 3. MODULE HIBA : CONTRATS ─────────────────────────────────────────────────
@router.get("/contrats")
def get_contrats(type_filter: str | None = None):
    return ontology_service.get_contrats(type_filter)


@router.post("/contrats")
def create_contrat(req: ContratCreateRequest):
    c_id = ontology_service.add_contrat(req.model_dump())
    return {"status": "success", "message": f"Contrat {c_id} créé dans l'ontologie", "id": c_id}


@router.put("/contrats/{contrat_id}")
def update_contrat(contrat_id: str, req: ContratUpdateRequest):
    try:
        success = ontology_service.update_contrat(contrat_id, req.model_dump(exclude_unset=True))
        if not success:
            raise HTTPException(
                status_code=404, detail=f"Contrat {contrat_id} non trouvé dans l'ontologie"
            )
        return {"status": "success", "message": f"Contrat {contrat_id} mis à jour avec succès"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.delete("/contrats/{contrat_id}")
def delete_contrat(contrat_id: str):
    success = ontology_service.delete_contrat(contrat_id)
    if not success:
        raise HTTPException(status_code=404, detail="Contrat non trouvé dans l'ontologie")
    return {"status": "success", "message": f"Contrat {contrat_id} supprimé de l'ontologie"}


# ── 3b. MODULE HIBA : HABITATIONS ─────────────────────────────────────────
@router.post("/habitations")
def create_habitation(req: HabitationCreateRequest):
    try:
        return ontology_service.add_habitation(req.model_dump())
    except (TypeError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/habitations")
def list_habitations():
    return ontology_service.get_all_habitations()


@router.get("/habitations/{habitation_id}")
def get_habitation(habitation_id: str):
    try:
        result = ontology_service.get_habitation(habitation_id)
    except (TypeError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if not result:
        raise HTTPException(status_code=404, detail="Habitation non trouvée dans l'ontologie")
    return result


@router.put("/habitations/{habitation_id}")
def update_habitation(habitation_id: str, req: HabitationUpdateRequest):
    try:
        success = ontology_service.update_habitation(
            habitation_id, req.model_dump(exclude_none=True)
        )
        if not success:
            raise HTTPException(status_code=404, detail="Habitation non trouvée dans l'ontologie")
        return {"status": "success", "message": "Habitation mise à jour avec succès"}
    except HTTPException:
        raise
    except (TypeError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.delete("/habitations/{habitation_id}")
def delete_habitation(habitation_id: str):
    try:
        deleted = ontology_service.delete_habitation(habitation_id)
    except (TypeError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if not deleted:
        raise HTTPException(status_code=404, detail="Habitation non trouvée dans l'ontologie")
    return {"status": "success", "message": "Habitation supprimée de l'ontologie"}


# ── 4. STATS ──────────────────────────────────────────────────────────────────
@router.get("/stats")
def get_stats():
    return ontology_service.get_stats()


# ── 4b. RECHERCHE TEXTUELLE ──────────────────────────────────────────────────
@router.get("/search")
def search_ontology(q: str, limit: int = 100):
    """Recherche textuelle dans les individus et leurs propriétés (SPARQL)."""
    try:
        return ontology_service.search(q, limit=limit)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


# ── 5. SPARQL DIRECT ─────────────────────────────────────────────────────────
@router.post("/sparql")
def execute_sparql(req: SPARQLQueryRequest):
    try:
        return ontology_service.execute_sparql(req.query)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/sparql/examples")
def get_sparql_examples():
    """Retourne la bibliothèque de requêtes SPARQL exemples (12 requêtes commentées)."""
    return ontology_service.get_sparql_examples()


# ── 6. NLP / TALN ─────────────────────────────────────────────────────────────
@router.post("/nlp/ask")
def ask_nlp(req: NLPQuestionRequest):
    """
    Traduit une question en langage naturel français en requête SPARQL.
    Pipeline : NLTK tokenisation → spaCy NER → Intent matching → Slots/FILTER → SPARQL
    """
    try:
        return nlp_translator.translate_to_sparql(req.question)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


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
            "Étape 4 — Slots : spaCy NER + regex → filtres "
            "SPARQL (montant, lieu, personne, date, statut)",
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


# ── 7b. ENTITÉS MANQUANTES DE L'ONTOLOGIE (Sinistre, Garantie, Document, Dommage…) ─────
class SinistreCreateRequest(BaseModel):
    type: str = "SinistreIncendie"
    dateSinistre: str
    lieuSinistre: str = ""
    descriptionSinistre: str = ""
    montantDomage: float | None = None
    contrat: str = ""
    statut: str = "Declara"
    causeSinistre: str | None = None


class SinistreUpdateRequest(BaseModel):
    type: str | None = None
    typeSinistre: str | None = None
    dateSinistre: str | None = None
    lieuSinistre: str | None = None
    descriptionSinistre: str | None = None
    montantDomage: float | None = None
    contrat: str | None = None
    statut: str | None = None
    causeSinistre: str | None = None


@router.post("/sinistres")
def create_sinistre(req: SinistreCreateRequest):
    """Crée un sinistre dans l'ontologie."""
    try:
        data = {
            "type": req.type,
            "dateSinistre": req.dateSinistre,
            "lieuSinistre": req.lieuSinistre,
            "descriptionSinistre": req.descriptionSinistre,
            "montantDomage": req.montantDomage,
            "contrat": req.contrat,
            "statut": req.statut,
            "causeSinistre": req.causeSinistre,
        }
        res = ontology_service.add_sinistre(data)
        return res
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/sinistres")
def list_sinistres(
    type: str | None = None,
    statut: str | None = None,
    lieu: str | None = None,
    assure: str | None = None,
):
    """Liste tous les sinistres de l'ontologie, avec filtres optionnels."""
    return ontology_service.get_all_sinistres(
        type_filter=type, statut=statut, lieu=lieu, assure=assure
    )


@router.get("/sinistres/{ontology_id}")
def get_sinistre(ontology_id: str):
    """Récupère un sinistre par son identifiant."""
    result = ontology_service.get_sinistre(ontology_id)
    if not result:
        raise HTTPException(status_code=404, detail="Sinistre non trouvé dans l'ontologie")
    return result


@router.put("/sinistres/{ontology_id}")
def update_sinistre(ontology_id: str, req: SinistreUpdateRequest):
    """Met à jour un sinistre."""
    try:
        updates = {k: v for k, v in req.model_dump(exclude_none=True).items()}
        res = ontology_service.update_sinistre(ontology_id, updates)
        return res
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.delete("/sinistres/{ontology_id}")
def delete_sinistre(ontology_id: str):
    """Supprime un sinistre de l'ontologie."""
    try:
        res = ontology_service.delete_sinistre(ontology_id)
        return res
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


# Garantie routes
@router.post("/garanties")
def create_garantie(req: dict):
    """Crée une garantie dans l'ontologie."""
    try:
        res = ontology_service.add_garantie(req)
        return res
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/garanties")
def read_garanties():
    """Liste toutes les garanties de l'ontologie."""
    return ontology_service.get_all_garanties()


@router.get("/garanties/{ontology_id}")
def read_garantie(ontology_id: str):
    """Récupère une garantie par son identifiant."""
    result = ontology_service.get_garantie(ontology_id)
    if not result:
        raise HTTPException(status_code=404, detail="Garantie non trouvée dans l'ontologie")
    return result


@router.put("/garanties/{ontology_id}")
def update_garantie(ontology_id: str, req: dict):
    """Met à jour une garantie."""
    try:
        updates = {k: v for k, v in req.items() if v is not None}
        res = ontology_service.update_garantie(ontology_id, updates)
        return res
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.delete("/garanties/{ontology_id}")
def delete_garantie(ontology_id: str):
    """Supprime une garantie de l'ontologie."""
    try:
        res = ontology_service.delete_garantie(ontology_id)
        return res
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


# Document routes
@router.post("/documents")
def create_document(req: dict):
    """Ajoute un document à l'ontologie."""
    try:
        res = ontology_service.add_document(req)
        return res
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/documents")
def read_documents():
    """Liste tous les documents de l'ontologie."""
    return ontology_service.get_all_documents()


@router.get("/documents/{ontology_id}")
def read_document(ontology_id: str):
    """Récupère un document par son identifiant."""
    result = ontology_service.get_document(ontology_id)
    if not result:
        raise HTTPException(status_code=404, detail="Document non trouvé dans l'ontologie")
    return result


@router.put("/documents/{ontology_id}")
def update_document(ontology_id: str, req: dict):
    """Met à jour un document."""
    try:
        updates = {k: v for k, v in req.items() if v is not None}
        res = ontology_service.update_document(ontology_id, updates)
        return res
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.delete("/documents/{ontology_id}")
def delete_document(ontology_id: str):
    """Supprime un document de l'ontologie."""
    try:
        res = ontology_service.delete_document(ontology_id)
        return res
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


# Dommage routes
@router.post("/dommages")
def create_dommage(req: dict):
    """Crée un dommage dans l'ontologie."""
    try:
        res = ontology_service.add_dommage(req)
        return res
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/dommages")
def read_dommages():
    """Liste tous les dommages de l'ontologie."""
    return ontology_service.get_all_dommages()


@router.get("/dommages/{ontology_id}")
def read_dommage(ontology_id: str):
    """Récupère un dommage par son identifiant."""
    result = ontology_service.get_dommage(ontology_id)
    if not result:
        raise HTTPException(status_code=404, detail="Dommage non trouvé dans l'ontologie")
    return result


@router.put("/dommages/{ontology_id}")
def update_dommage(ontology_id: str, req: dict):
    """Met à jour un dommage."""
    try:
        updates = {k: v for k, v in req.items() if v is not None}
        res = ontology_service.update_dommage(ontology_id, updates)
        return res
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.delete("/dommages/{ontology_id}")
def delete_dommage(ontology_id: str):
    """Supprime un dommage de l'ontologie."""
    try:
        res = ontology_service.delete_dommage(ontology_id)
        return res
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


PROMOTIONS_FILE = str(Path(__file__).resolve().parent.parent.parent.parent / "promotions.json")


def _load_promotions():
    if os.path.exists(PROMOTIONS_FILE):
        with open(PROMOTIONS_FILE, encoding="utf-8") as _f:
            return json.load(_f)
    return []


def _save_promotions(data):
    with open(PROMOTIONS_FILE, "w", encoding="utf-8") as _f:
        json.dump(data, _f, ensure_ascii=False, indent=2)


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
    existing = [
        p for p in promos if p["ontology_id"] == req.ontology_id and p["status"] == "pending"
    ]
    if existing:
        raise HTTPException(
            status_code=409, detail="Une demande est deja en cours pour cet utilisateur"
        )
    import time

    entry = {
        "id": f"promo_{int(time.time())}",
        "ontology_id": req.ontology_id,
        "current_name": req.current_name,
        "requested_role": req.requested_role,
        "message": req.message,
        "status": "pending",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
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
        raise HTTPException(
            status_code=500, detail=f"Erreur lors du changement de role: {e}"
        ) from e
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
