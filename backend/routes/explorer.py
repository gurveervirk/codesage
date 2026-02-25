from typing import Optional
from fastapi import APIRouter, HTTPException, Query, Request

explorer_router = APIRouter()


@explorer_router.get("/search")
async def search_definitions(
    request: Request,
    q: str = Query(..., description="Comma-separated search terms (aliases, FQNs, or symbol names)"),
    version: Optional[str] = Query(None, description="Filter by version"),
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(10, ge=1, le=100, description="Results per page"),
):
    pg_tools = request.app.state.pg_tools
    data = pg_tools._search_definitions_raw(
        search_terms=q,
        version=version or None,
        page=page,
        page_size=page_size,
    )
    if "error" in data:
        raise HTTPException(status_code=400, detail=data["error"])
    return data


@explorer_router.get("/definitions")
async def get_definitions(
    request: Request,
    names: str = Query(..., description="Comma-separated FQNs to retrieve"),
    version: Optional[str] = Query(None, description="Preferred version"),
    context_lines: int = Query(20, ge=0, description="Extra lines of context above/below each entity"),
    include_full_source: bool = Query(False, description="Include the full module source file"),
):
    entity_names = [n.strip() for n in names.split(",") if n.strip()]
    if not entity_names:
        raise HTTPException(status_code=400, detail="No entity names provided")
    pg_tools = request.app.state.pg_tools
    results = pg_tools._get_definitions_raw(
        entity_names=entity_names,
        version=version or None,
        context_lines=context_lines,
        include_full_source=include_full_source,
    )
    return {"definitions": results}
