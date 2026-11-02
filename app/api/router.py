from fastapi import APIRouter

from app.api.routes import clause, dommage, health, ontology

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(ontology.router)

# Module Montaha Trabelsi : Dommages
api_router.include_router(dommage.router)
api_router.include_router(dommage.router, prefix="/ontology")

# Module Montaha Trabelsi : Clauses
api_router.include_router(clause.router)
api_router.include_router(clause.router, prefix="/ontology")
