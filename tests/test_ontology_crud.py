import os
import shutil
import tempfile

from rdflib import RDF

from app.services.ontology_service import AS, UNT, OntologyService


def _service_copy():
    tmp = tempfile.NamedTemporaryFile(suffix=".rdf", delete=False)
    tmp.close()
    shutil.copyfile("assurance.rdf", tmp.name)
    return OntologyService(tmp.name), tmp.name


def test_personne_crud():
    svc, path = _service_copy()
    try:
        pid = svc.add_personne(
            {
                "role": "Assure",
                "nom": "Test",
                "prenom": "Unit",
                "cin": "123",
                "telephone": "000",
                "adresse": "Here",
            }
        )
        assert any(p["personne"] == pid for p in svc.get_personnes())
        assert svc.update_personne(pid, {"nom": "Updated"}) is True
        assert svc.delete_personne(pid) is True
    finally:
        os.unlink(path)


def test_contrat_crud():
    svc, path = _service_copy()
    try:
        cid = svc.add_contrat(
            {
                "type": "ContratProprietaire",
                "numeroContrat": "C-TEST",
                "dateDebut": "2026-01-01T00:00:00",
                "dateFin": "2026-12-31T00:00:00",
                "montantPrime": 123.0,
                "assure": "Assure1",
            }
        )
        assert any(c["contrat"] == cid for c in svc.get_contrats())
        assert svc.update_contrat(cid, {"montantPrime": 999.0}) is True
        assert svc.delete_contrat(cid) is True
    finally:
        os.unlink(path)


def test_habitation_crud():
    svc, path = _service_copy()
    try:
        hid = svc.add_habitation(
            {
                "type": "Appartement",
                "adresse": "bardo",
                "superficie": 12000,
                "valeurBien": 125000,
            }
        )["id"]
        habitation = svc.get_habitation(hid)
        assert habitation["adresse"] == "bardo"
        assert habitation["superficie"] == "12000.0"
        assert svc.update_habitation(hid, {"adresse": "Tunis", "valeurBien": 150000}) is True
        assert svc.get_habitation(hid)["adresse"] == "Tunis"
        assert svc.delete_habitation(hid) is True
    finally:
        os.unlink(path)


def test_sinistre_document_dommage_garantie_crud():
    svc, path = _service_copy()
    try:
        sid = svc.add_sinistre(
            {
                "type": "SinistreIncendie",
                "dateSinistre": "2026-02-02T00:00:00",
                "lieuSinistre": "Tunis",
                "descriptionSinistre": "Test",
                "contrat": "Contrat1",
                "statut": "En cours",
                "causeSinistre": "Test cause",
            }
        )["id"]
        assert any(s["sinistre"] == sid for s in svc.get_all_sinistres())
        assert svc.update_sinistre(sid, {"lieuSinistre": "Sousse", "statut": "Acceptée"}) is True

        gid = svc.add_garantie(
            {
                "type": "GarantieIncendie",
                "nomGarantie": "Test garantie",
                "plafondGarantie": 10.0,
                "franchise": 1.0,
            }
        )["id"]
        assert any(g["garantie"] == gid for g in svc.get_all_garanties())
        assert svc.update_garantie(gid, {"nomGarantie": "Updated"}) is True
        assert svc.delete_garantie(gid) is True

        did = svc.add_document(
            {"type": "RapportExpertise", "nomFichier": "test.pdf", "associeSinistre": sid}
        )["id"]
        assert any(d["document"] == did for d in svc.get_all_documents())
        assert svc.update_document(did, {"nomFichier": "updated.pdf"}) is True
        assert svc.delete_document(did) is True

        mid = svc.add_dommage(
            {"type": "DommageMateriel", "description": "Test dommage", "associeSinistre": sid}
        )["id"]
        assert any(m["dommage"] == mid for m in svc.get_all_dommages())
        assert svc.update_dommage(mid, {"description": "Updated"}) is True
        assert svc.delete_dommage(mid) is True

        assert svc.delete_sinistre(sid) is True
    finally:
        os.unlink(path)


def test_sparql_update_on_copy():
    svc, path = _service_copy()
    try:
        svc.execute_sparql(
            "INSERT DATA { <http://www.semanticweb.org/asus/ontologies/2026/8/"
            "Assuarnce_et_Gestion_des_Sinistres#TestPersonne> a <http://www.semanticweb.org/"
            "asus/ontologies/2026/8/untitled-ontology-5#Personne> }"
        )
        rows = svc.execute_sparql(
            "SELECT ?x WHERE { ?x a <http://www.semanticweb.org/"
            "asus/ontologies/2026/8/untitled-ontology-5#Personne> }"
        )["results"]
        assert any(r["x"] == "TestPersonne" for r in rows)
        svc.execute_sparql(
            "DELETE DATA { <http://www.semanticweb.org/asus/ontologies/2026/8/"
            "Assuarnce_et_Gestion_des_Sinistres#TestPersonne> a <http://www.semanticweb.org/"
            "asus/ontologies/2026/8/untitled-ontology-5#Personne> }"
        )
    finally:
        os.unlink(path)


def test_single_resource_queries_and_ontology_types():
    svc, path = _service_copy()
    try:
        assert svc.get_sinistre("Sinistre1")["sinistre"] == "Sinistre1"
        assert svc.get_garantie("GarantieIncendie1")["garantie"] == "GarantieIncendie1"
        assert svc.get_document("Document1")["document"] == "Document1"
        assert svc.get_dommage("Dommage1")["dommage"] == "Dommage1"

        dommage_id = svc.add_dommage({"type": "DommageMateriel"})["id"]
        assert (AS[dommage_id], RDF.type, UNT.DommageMateriel) in svc.graph
    finally:
        os.unlink(path)


def test_invalid_ontology_values_are_rejected():
    svc, path = _service_copy()
    try:
        try:
            svc.change_role_personne("Assure1", "Bogus")
            raise AssertionError("invalid roles must be rejected")
        except ValueError:
            pass

        try:
            svc.add_personne({"role": "Bogus"})
            raise AssertionError("invalid person classes must be rejected")
        except ValueError:
            pass
    finally:
        os.unlink(path)
