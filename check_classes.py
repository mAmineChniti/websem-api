from app.services.ontology_service import ontology_service

# 1. Toutes les classes qui contiennent "habitation" (casse insensible)
print("=== Classes contenant 'habitation' ===")
r = ontology_service.execute_sparql(
    "SELECT DISTINCT ?c WHERE { ?x a ?c. FILTER(CONTAINS(LCASE(STR(?c)), 'habitation')) }"
)
for row in r["results"]:
    print(" ", row)

# 2. Toutes les classes contenant "maison", "villa", "appartement", "studio"
print("\n=== Classes contenant 'maison'/'villa'/'appartement'/'studio' ===")
r2 = ontology_service.execute_sparql(
    """SELECT DISTINCT ?c WHERE {
      ?x a ?c.
      FILTER(
        CONTAINS(LCASE(STR(?c)), 'maison') ||
        CONTAINS(LCASE(STR(?c)), 'villa') ||
        CONTAINS(LCASE(STR(?c)), 'appartement') ||
        CONTAINS(LCASE(STR(?c)), 'studio')
      )
    }"""
)
for row in r2["results"]:
    print(" ", row)

# 3. Individus Maison/Villa/Appartement/Studio dans le graphe
print("\n=== Individus Maison/Villa/Appartement/Studio ===")
r3 = ontology_service.execute_sparql(
    """PREFIX ont: <http://www.semanticweb.org/asus/ontologies/2026/8/untitled-ontology-5#>
    SELECT ?x ?type WHERE {
      ?x a ?type.
      VALUES ?type { ont:Maison ont:Villa ont:Appartement ont:Studio }
    }"""
)
print(f"  {len(r3['results'])} habitation(s) trouvée(s)")
for row in r3["results"]:
    print(" ", row)
