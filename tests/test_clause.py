"""
Tests unitaires pour le module Clauses (Montaha Trabelsi).
Vérifie le CRUD complet, le cas ClauseFranchise et la gestion des erreurs HTTP (400, 404).
"""

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_get_clauses_list():
    """Test de récupération de la liste des clauses."""
    response = client.get("/api/clauses/")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)


def test_crud_clause_lifecycle():
    """Cycle de vie complet : Création -> Lecture -> Mise à jour -> Suppression."""
    # 1. Création d'une ClauseExclusion
    new_clause = {
        "type_clause": "ClauseExclusion",
        "texte_clause": "Exclusion formelle des dommages causés par acte de guerre ou terrorisme",
        "description": "Clause générale d'exclusion contractuelle",
        "contrat_id": "Contrat1",
    }
    create_res = client.post("/api/clauses/", json=new_clause)
    assert create_res.status_code == 201
    created_data = create_res.json()
    assert "id" in created_data
    clause_id = created_data["id"]

    # 2. Lecture par ID
    get_res = client.get(f"/api/clauses/{clause_id}")
    assert get_res.status_code == 200
    clause_detail = get_res.json()
    assert clause_detail["id"] == clause_id
    assert "guerre" in clause_detail["texte_clause"]

    # 3. Mise à jour
    update_payload = {
        "texte_clause": "Exclusion formelle révisée incluant vandalisme en période d'émeute",
        "description": "Clause d'exclusion révisée 2026",
    }
    put_res = client.put(f"/api/clauses/{clause_id}", json=update_payload)
    assert put_res.status_code == 200

    # Vérification mise à jour
    get_updated = client.get(f"/api/clauses/{clause_id}")
    assert get_updated.status_code == 200
    assert "révisée" in get_updated.json()["texte_clause"]

    # 4. Suppression
    del_res = client.delete(f"/api/clauses/{clause_id}")
    assert del_res.status_code == 200

    # 5. Vérification 404
    get_deleted = client.get(f"/api/clauses/{clause_id}")
    assert get_deleted.status_code == 404


def test_create_clause_franchise():
    """Vérifie la création et mise à jour d'une ClauseFranchise avec tauxFranchise."""
    franchise_clause = {
        "type_clause": "ClauseFranchise",
        "texte_clause": "Franchise conventionnelle de 10% sur tout sinistre bris de glace",
        "taux_franchise": 10.0,
        "description": "Franchise standard bris de glace",
        "contrat_id": "Contrat2",
    }
    res = client.post("/api/clauses/", json=franchise_clause)
    assert res.status_code == 201
    cl_id = res.json()["id"]

    # Vérification
    get_res = client.get(f"/api/clauses/{cl_id}")
    assert get_res.status_code == 200
    data = get_res.json()
    assert data["taux_franchise"] == 10.0

    # Nettoyage
    del_res = client.delete(f"/api/clauses/{cl_id}")
    assert del_res.status_code == 200


def test_clause_not_found():
    """Test cas d'erreur 404 : clause inexistante."""
    res_get = client.get("/api/clauses/ClauseInexistante999")
    assert res_get.status_code == 404

    res_put = client.put("/api/clauses/ClauseInexistante999", json={"texte_clause": "Test"})
    assert res_put.status_code == 404

    res_del = client.delete("/api/clauses/ClauseInexistante999")
    assert res_del.status_code == 404


def test_create_clause_invalid_type():
    """Test cas d'erreur 400 : type de clause invalide."""
    bad_clause = {
        "type_clause": "ClauseFantaisisteNonDefinie",
        "texte_clause": "Texte quelconque",
    }
    res = client.post("/api/clauses/", json=bad_clause)
    assert res.status_code == 400
