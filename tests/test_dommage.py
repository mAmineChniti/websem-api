"""
Tests unitaires pour le module Dommages (Montaha Trabelsi).
Vérifie le CRUD complet et la gestion d'erreurs HTTP (400, 404).
"""

from fastapi.testclient import TestClient
from rdflib import XSD, Graph

from app.main import app
from app.services.ontology_service import AS, ontology_service

client = TestClient(app)


def test_get_dommages_list():
    """Test de récupération de la liste des dommages."""
    response = client.get("/api/dommages/")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)


def test_crud_dommage_lifecycle(monkeypatch, tmp_path):
    """Cycle de vie complet : Création -> Lecture -> Mise à jour -> Suppression."""
    monkeypatch.setattr(ontology_service, "graph", Graph())
    monkeypatch.setattr(ontology_service, "rdf_path", str(tmp_path / "assurance.rdf"))
    # 1. Création
    new_dommage = {
        "type_dommage": "DommageMateriel",
        "description": "Fissures murales suite à infiltration d'eau",
        "montant": 1450.50,
        "gravite": "Moyen",
        "sinistre_id": "Sinistre1",
        "date": "2026-03-15T10:00:00",
        "lieu": "Tunis, Menzah",
    }
    create_res = client.post("/api/dommages/", json=new_dommage)
    assert create_res.status_code == 201
    created_data = create_res.json()
    assert "id" in created_data
    dommage_id = created_data["id"]
    date = next(ontology_service.graph.objects(AS[dommage_id], AS.dateSinistre))
    assert date.datatype == XSD.dateTime

    # 2. Lecture par ID
    get_res = client.get(f"/api/dommages/{dommage_id}")
    assert get_res.status_code == 200
    dom_detail = get_res.json()
    assert dom_detail["id"] == dommage_id
    assert dom_detail["gravite"] == "Moyen"
    assert dom_detail["montant"] == 1450.50

    # 3. Mise à jour
    update_payload = {
        "gravite": "Grave",
        "montant": 2100.0,
        "description": "Fissures murales et effondrement partiel plafond",
        "date": "2026-03-16T12:30:00",
    }
    put_res = client.put(f"/api/dommages/{dommage_id}", json=update_payload)
    assert put_res.status_code == 200
    updated_body = put_res.json()
    assert updated_body["id"] == dommage_id

    # Vérification que la mise à jour est effective
    get_updated = client.get(f"/api/dommages/{dommage_id}")
    assert get_updated.status_code == 200
    assert get_updated.json()["gravite"] == "Grave"
    assert get_updated.json()["montant"] == 2100.0
    updated_date = next(ontology_service.graph.objects(AS[dommage_id], AS.dateSinistre))
    assert updated_date.datatype == XSD.dateTime

    # 4. Suppression
    del_res = client.delete(f"/api/dommages/{dommage_id}")
    assert del_res.status_code == 200

    # 5. Vérification que le dommage supprimé retourne 404
    get_deleted = client.get(f"/api/dommages/{dommage_id}")
    assert get_deleted.status_code == 404


def test_dommage_not_found():
    """Test cas d'erreur 404 : identifiant inexistant."""
    res_get = client.get("/api/dommages/DommageInexistant999")
    assert res_get.status_code == 404

    res_put = client.put("/api/dommages/DommageInexistant999", json={"description": "Test"})
    assert res_put.status_code == 404

    res_del = client.delete("/api/dommages/DommageInexistant999")
    assert res_del.status_code == 404


def test_create_dommage_invalid_data():
    """Test cas d'erreur 400 : type de dommage ou gravité invalide."""
    # Type invalide
    invalid_type = {
        "type_dommage": "TypeInconnuDansOntologie",
        "description": "Test dommage invalide",
        "montant": 500,
        "gravite": "Faible",
    }
    res_bad_type = client.post("/api/dommages/", json=invalid_type)
    assert res_bad_type.status_code == 400

    # Gravité invalide
    invalid_gravite = {
        "type_dommage": "DommageMateriel",
        "description": "Test gravité invalide",
        "montant": 500,
        "gravite": "ExtremeCritiqueInvalide",
    }
    res_bad_gravite = client.post("/api/dommages/", json=invalid_gravite)
    assert res_bad_gravite.status_code == 400
