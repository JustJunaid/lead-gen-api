"""Main API router aggregating all v1 endpoints."""

from fastapi import APIRouter

from leadgen.api.v1 import leads, jobs, scraping, verification

api_router = APIRouter()

# Include sub-routers
api_router.include_router(leads.router, prefix="/leads", tags=["Leads"])
api_router.include_router(jobs.router, prefix="/jobs", tags=["Jobs"])
api_router.include_router(scraping.router, prefix="/scraping", tags=["Scraping"])
api_router.include_router(verification.router, prefix="/verification", tags=["Verification"])
# api_router.include_router(enrichment.router, prefix="/enrichment", tags=["Enrichment"])
# api_router.include_router(ai.router, prefix="/ai", tags=["AI"])
# api_router.include_router(imports.router, prefix="/imports", tags=["Imports"])
