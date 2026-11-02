import json

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_openapi_available():
    response = client.get("/openapi.json")
    assert response.status_code == 200
    assert "paths" in response.json()


def test_stats():
    response = client.get("/api/ontology/stats")
    assert response.status_code == 200
    data = response.json()
    assert data["classes_count"] == 47
    assert data["personnes_count"] >= 7
    assert data["contrats_count"] == 4


def test_classes_and_properties():
    classes = client.get("/api/ontology/classes").json()
    object_props = client.get("/api/ontology/properties/object").json()
    data_props = client.get("/api/ontology/properties/datatype").json()
    assert len(classes) == 47
    assert len(object_props) == 13
    assert len(data_props) == 25


def test_nlp_intents():
    response = client.get("/api/ontology/nlp/intents")
    assert response.status_code == 200
    assert response.json()["total"] == 20


def test_nlp_ask():
    response = client.post("/api/ontology/nlp/ask", json={"question": "Liste les assurés"})
    assert response.status_code == 200
    data = response.json()
    assert data["intent"] == "LIST_ASSURES"
    assert data["count"] >= 1
    assert "sparql_query" in data
    assert "pipeline" in data


def test_sparql_direct():
    response = client.post(
        "/api/ontology/sparql",
        json={"query": "SELECT ?x WHERE { ?x a owl:Class } LIMIT 1"},
    )
    assert response.status_code == 200
    assert response.json()["count"] >= 1


def test_search():
    response = client.get("/api/ontology/search", params={"q": "sinistre"})
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_sparql_examples_execute():
    examples = client.get("/api/ontology/sparql/examples").json()
    assert len(examples) == 12
    for example in examples:
        response = client.post("/api/ontology/sparql", json={"query": example["query"]})
        assert response.status_code == 200, example["id"]