from typing import Optional, List
from fastapi import APIRouter, HTTPException, Query, Request

explorer_router = APIRouter()


@explorer_router.get("/search")
async def search_definitions(
    request: Request,
    q: str = Query(..., description="Comma-separated search terms (aliases, FQNs, or symbol names)"),
    version: Optional[str] = Query(None, description="Filter by version"),
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(10, ge=1, le=100, description="Results per page"),
    search_aliases: bool = Query(True, description="Include alias-based matching"),
    search_fqn: bool = Query(True, description="Include FQN-based matching"),
    use_regex: bool = Query(False, description="Treat terms as regex patterns"),
    exact_match: bool = Query(False, description="Only exact equality matches"),
    match_case: bool = Query(False, description="Case-sensitive matching"),
    kinds: Optional[str] = Query(None, description="Comma-separated entity kinds to filter by: module, class, function, method, package"),
):
    pg_tools = request.app.state.pg_tools
    parsed_kinds: Optional[List[str]] = [k.strip() for k in kinds.split(",") if k.strip()] if kinds else None
    data = pg_tools._search_definitions_raw(
        search_terms=q,
        version=version or None,
        page=page,
        page_size=page_size,
        search_aliases=search_aliases,
        search_fqn=search_fqn,
        use_regex=use_regex,
        exact_match=exact_match,
        match_case=match_case,
        kinds=parsed_kinds,
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
    fields: Optional[str] = Query(None, description="Comma-separated fields to include: source, signature, docstring, file_info. Defaults to 'source'"),
):
    entity_names = [n.strip() for n in names.split(",") if n.strip()]
    if not entity_names:
        raise HTTPException(status_code=400, detail="No entity names provided")
    parsed_fields: Optional[List[str]] = [f.strip() for f in fields.split(",") if f.strip()] if fields else None
    pg_tools = request.app.state.pg_tools
    results = pg_tools._get_definitions_raw(
        entity_names=entity_names,
        version=version or None,
        context_lines=context_lines,
        include_full_source=include_full_source,
        fields=parsed_fields,
    )
    return {"definitions": results}
