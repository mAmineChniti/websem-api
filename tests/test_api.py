from fastapi.testclient import TestClient
from rdflib import Graph

from app.main import app
from app.services.ontology_service import ontology_service

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
    data = response.json()
    assert data["total"] == 33
    ids = {intent["id"] for intent in data["intents"]}
    assert {
        "LIST_GARANTIES",
        "LIST_GARANTIES_INCENDIE",
        "LIST_GARANTIES_VOL",
        "LIST_SINISTRES",
        "LIST_SINISTRES_INCENDIE",
        "LIST_SINISTRES_VOL",
        "LIST_SINISTRES_DEGAT_EAUX",
        "LIST_SINISTRES_BRIS_DE_GLACE",
        "LIST_SINISTRES_CATASTROPHE_NATURELLE",
        "LIST_CLAUSES",
        "LIST_DOCUMENTS",
        "LIST_DOMMAGES",
    } <= ids


def test_nlp_ask():
    response = client.post("/api/ontology/nlp/ask", json={"question": "Liste les assurés"})
    assert response.status_code == 200
    data = response.json()
    assert data["intent"] == "LIST_ASSURES"
    assert data["count"] >= 1
    assert "sparql_query" in data
    assert "pipeline" in data
    assert "step4_slots" in data["pipeline"]


def test_nlp_garantie_and_sinistre_modules():
    """Le NLP couvre bien les modules garantie et sinistre (pas de faux positifs)."""
    incendie = client.post(
        "/api/ontology/nlp/ask", json={"question": "Liste les sinistres incendie"}
    ).json()
    assert incendie["intent"] == "LIST_SINISTRES_INCENDIE"
    assert incendie["count"] == 1
    assert all("Sinistre" in row["typeSinistre"] for row in incendie["results"])

    vol = client.post(
        "/api/ontology/nlp/ask", json={"question": "Liste les sinistres de vol"}
    ).json()
    assert vol["intent"] == "LIST_SINISTRES_VOL"
    assert vol["count"] == 0

    garantie = client.post(
        "/api/ontology/nlp/ask", json={"question": "liste les garanties incendie"}
    ).json()
    assert garantie["intent"] == "LIST_GARANTIES_INCENDIE"
    assert garantie["count"] == 1
    assert garantie["results"][0]["garantie"] == "GarantieIncendie1"

    experts = client.post("/api/ontology/nlp/ask", json={"question": "liste les experts"}).json()
    assert experts["intent"] == "LIST_EXPERTS"
    assert experts["count"] == 1
    assert experts["results"][0]["expert"] == "Expert1"

    degat_garantie = client.post(
        "/api/ontology/nlp/ask", json={"question": "Liste les garanties dégât des eaux"}
    ).json()
    assert degat_garantie["intent"] == "LIST_GARANTIES_DEGAT_EAUX"

    degat_sinistre = client.post(
        "/api/ontology/nlp/ask", json={"question": "Liste les sinistres dégât des eaux"}
    ).json()
    assert degat_sinistre["intent"] == "LIST_SINISTRES_DEGAT_EAUX"


def test_nlp_indemnisation_uses_ontology_property():
    data = client.post(
        "/api/ontology/nlp/ask", json={"question": "liste les indemnisations"}
    ).json()
    assert data["intent"] == "LIST_INDEMNISATIONS"
    assert data["count"] == 1
    assert "as:montantIndemnise" in data["sparql_query"]
    assert data["results"][0]["montant"] == "45000.0"


def test_nlp_slot_filters():
    amount = client.post(
        "/api/ontology/nlp/ask",
        json={"question": "contrats dont la prime dépasse 700 dinars"},
    ).json()
    assert amount["intent"] == "LIST_ALL_CONTRATS"
    assert amount["count"] >= 1
    assert "FILTER(?montantPrime > 700)" in amount["sparql_query"]
    assert amount["pipeline"]["step4_slots"]["slots"]["amount"] == "700"

    accepted = client.post(
        "/api/ontology/nlp/ask", json={"question": "Déclarations acceptées"}
    ).json()
    assert accepted["intent"] == "LIST_DECLARATIONS"
    assert accepted["count"] == 1
    assert "accept" in accepted["sparql_query"]

    rejected = client.post(
        "/api/ontology/nlp/ask", json={"question": "Déclarations rejetées"}
    ).json()
    assert rejected["intent"] == "LIST_DECLARATIONS"
    assert rejected["count"] == 0

    located = client.post(
        "/api/ontology/nlp/ask", json={"question": "liste les habitations à Sousse"}
    ).json()
    assert located["intent"] == "LIST_HABITATIONS"
    assert located["count"] >= 1
    assert "adresseBien" in located["sparql_query"]

    person = client.post(
        "/api/ontology/nlp/ask", json={"question": "Qui est l'assuré BenAli ?"}
    ).json()
    assert person["intent"] == "LIST_ASSURES"
    assert person["count"] == 1
    assert person["results"][0]["nom"] == "BenAli"


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


def test_habitation_endpoints(monkeypatch, tmp_path):
    graph = Graph()
    graph.parse("assurance.rdf", format="xml")
    monkeypatch.setattr(ontology_service, "graph", graph)
    monkeypatch.setattr(ontology_service, "rdf_path", str(tmp_path / "assurance.rdf"))

    created = client.post(
        "/api/ontology/habitations",
        json={"type": "Appartement", "adresse": "Tunis", "superficie": 90, "valeurBien": 250000},
    )
    assert created.status_code == 200
    habitation_id = created.json()["id"]

    listed = client.get("/api/ontology/habitations")
    assert listed.status_code == 200
    assert any(h["habitation"] == habitation_id for h in listed.json())

    detail = client.get(f"/api/ontology/habitations/{habitation_id}")
    assert detail.status_code == 200
    assert detail.json()["adresse"] == "Tunis"
    assert detail.json()["valeurBien"] == "250000.0"

    updated = client.put(
        f"/api/ontology/habitations/{habitation_id}",
        json={"type": "Villa", "adresse": "Sousse"},
    )
    assert updated.status_code == 200
    assert (
        client.get(f"/api/ontology/habitations/{habitation_id}").json()["typeHabitation"] == "Villa"
    )

    assert client.delete(f"/api/ontology/habitations/{habitation_id}").status_code == 200
    assert client.get(f"/api/ontology/habitations/{habitation_id}").status_code == 404

    assert client.post("/api/ontology/habitations", json={"type": "Chateau"}).status_code == 400
    assert client.get("/api/ontology/habitations/invalid%20id").status_code == 400
    assert client.get("/api/ontology/habitations/Contrat1").status_code == 404
    assert client.delete("/api/ontology/habitations/Contrat1").status_code == 404
