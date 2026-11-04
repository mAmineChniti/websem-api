import rdflib
from rdflib import RDF, RDFS, Namespace, Literal

AS = Namespace("http://www.semanticweb.org/asus/ontologies/2026/8/Assuarnce_et_Gestion_des_Sinistres#")
ONT = Namespace("http://www.semanticweb.org/asus/ontologies/2026/8/untitled-ontology-5#")

g = rdflib.Graph()
g.parse("assurance.rdf", format="xml")

print("--- INDIVIDUS WIEM ---")
for s in sorted(set(g.subjects())):
    s_str = str(s)
    if "Wiem" in s_str:
        types = [str(t).split("#")[-1] for t in g.objects(s, RDF.type) if "NamedIndividual" not in str(t)]
        labels = [str(l) for l in g.objects(s, RDFS.label)]
        adresse = [str(a) for a in g.objects(s, AS.adresseBien)]
        concerne = [str(c).split("#")[-1] for c in g.objects(s, AS.concerneHabitation)]
        print(f"ID: {s_str.split('#')[-1]}")
        print(f"  Types: {types}")
        print(f"  Labels: {labels}")
        print(f"  Adresse: {adresse}")
        print(f"  Concerne: {concerne}")
