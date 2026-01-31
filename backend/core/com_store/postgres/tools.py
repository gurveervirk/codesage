from typing import Optional, List, Dict
from ..xml_utils import dict_to_xml_string
from .main import PostgresCOMStore
import logging

logger = logging.getLogger(__name__)

class PostgresCOMStoreTools:
    """
    Tool methods for PostgresCOMStore that yield agent-friendly XML responses.
    Optimized for Relational DB + Full Text Search (if enabled) operations.
    """

    def __init__(self, store: PostgresCOMStore):
        self.store = store

    def list_libraries(self, search_terms: Optional[str] = None) -> str:
        """
        List all imported libraries (DISTRIBUTION_PACKAGE / IMPORT_PACKAGE).
        
        Args:
           search_terms: Optional comma-separated string to filter libraries by name (case-insensitive partial match).
        """
        conn = self.store._get_connection()
        try:
            with conn.cursor() as cur:
                # Base query
                query = """
                    SELECT name, versions 
                    FROM entities 
                    WHERE type IN ('DISTRIBUTION_PACKAGE', 'IMPORT_PACKAGE') 
                      -- Heuristic: Top level modules are usually "libraries"
                      -- Or strictly use IMPORT_PACKAGE if extraction creates them reliably.
                """
                params = []
                
                if search_terms:
                    terms = [t.strip() for t in search_terms.split(',')]
                    conditions = []
                    for t in terms:
                        conditions.append("name ILIKE %s")
                        params.append(f"%{t}%")
                    if conditions:
                        query += " AND (" + " OR ".join(conditions) + ")"
                
                query += " ORDER BY name LIMIT 100"
                
                cur.execute(query, params)
                rows = cur.fetchall()
                
                libraries = []
                for r in rows:
                    libraries.append({
                        "name": r[0],
                        "versions": r[1]
                    })
                
                data = {
                    "libraries": libraries,
                    "system_message": f"Found {len(libraries)} libraries matching criteria."
                }
                return dict_to_xml_string(data, "list_libraries_response")
        finally:
            conn.close()

    def search_definitions(
        self,
        search_terms: str,
        version: Optional[str] = None,
        page: int = 1,
        page_size: int = 10
    ) -> str:
        """
        Search for definitions by aliases or FQNs.
        Ranking:
        1. Exact Match (Alias or FQN)
        2. Suffix Match with Dot (e.g. 'pandas.DataFrame' matches 'core.frame.DataFrame')
        3. General Suffix Match (e.g. 'DataFrame' matches 'MyDataFrame')
        4. Partial Match
        
        Args:
            search_terms: Comma-separated list of search terms (aliases, FQNs, or symbol names).
            version: Optional version to filter by.
            page: Page number (1-indexed).
            page_size: Number of results per page.
        """
        if isinstance(search_terms, str):
            terms = [t.strip() for t in search_terms.split(',') if t.strip()]
        else:
            terms = search_terms or []
            
        if not terms:
            return dict_to_xml_string({"error": "No search terms provided"}, "error")

        # Pre-process terms to extract symbols (last identifier in dot path)
        # e.g. "pandas.DataFrame" -> "DataFrame", "read_csv" -> "read_csv"
        symbols = [t.split('.')[-1] for t in terms]

        limit = page_size
        offset = (page - 1) * page_size
        
        conn = self.store._get_connection()
        try:
            with conn.cursor() as cur:
                # Prepare matching patterns
                
                # 1. Full Term Patterns
                # term (exact) - already in 'terms'
                dot_term_suffixes = [f"%.{t}" for t in terms] # e.g. "%.pandas.DataFrame"
                like_terms = [f"%{t}%" for t in terms]      # e.g. "%pandas.DataFrame%"
                
                # 2. Symbol Patterns (Broadest Match)
                # symbol (exact) - in 'symbols'
                dot_symbol_suffixes = [f"%.{s}" for s in symbols] # e.g. "%.DataFrame"
                symbol_suffixes = [f"%{s}" for s in symbols]      # e.g. "%DataFrame" (matches MyDataFrame)
                like_symbols = [f"%{s}%" for s in symbols]        # e.g. "%DataFrame%" (matches DataFrameFactory)
                
                # Query Params Ordering:
                # CASE:
                #   1. Exact Term (10): terms, terms                 (for alias=term or name=term)
                #   2. Term Dot Suffix (20): dot_term_suffixes       (for name like '%.term')
                #   3. Exact Symbol (30): symbols                    (for name=symbol - unlikely for FQN but possible for module)
                #   4. Symbol Dot Suffix (30): dot_symbol_suffixes   (for name like '%.symbol')
                #   5. Symbol Suffix (40): symbol_suffixes           (for name like '%symbol' e.g. MyDataFrame)
                #   ELSE 50
                #
                # WHERE (Broadest possible filter):
                #   alias matches term/symbol patterns
                #   name matches term/symbol patterns
                
                query_params = [
                    # Ranking Params
                    terms, terms,                   # 1. Exact Term
                    dot_term_suffixes,              # 2. Term Dot Suffix
                    symbols,                        # 3. Exact Symbol
                    dot_symbol_suffixes,            # 4. Symbol Dot Suffix
                    symbol_suffixes,                # 5. Symbol Suffix
                    
                    # Filtering Params (Broad)
                    terms, like_terms,              # Alias (Term)
                    symbols, like_symbols,          # Alias (Symbol)
                    terms, like_terms,              # Name (Term)
                    symbols, like_symbols           # Name (Symbol)
                ]
                
                version_clause = ""
                if version:
                    version_clause = "AND a.versions @> %s"
                    query_params.append([version])

                cte_sql = f"""
                WITH ranked_matches AS (
                    SELECT 
                        a.entity_name as fqn,
                        e.type,
                        MIN(
                            CASE 
                                WHEN a.alias = ANY(%s) OR a.entity_name = ANY(%s) THEN 10
                                WHEN a.entity_name ILIKE ANY(%s) THEN 20
                                WHEN a.entity_name = ANY(%s) OR a.entity_name ILIKE ANY(%s) THEN 30
                                WHEN a.entity_name ILIKE ANY(%s) THEN 40
                                ELSE 50
                            END
                        ) as score
                    FROM aliases a
                    JOIN entities e ON a.entity_name = e.name
                    WHERE (
                        a.alias = ANY(%s) OR a.alias ILIKE ANY(%s)
                        OR a.alias = ANY(%s) OR a.alias ILIKE ANY(%s)
                        OR a.entity_name = ANY(%s) OR a.entity_name ILIKE ANY(%s)
                        OR a.entity_name = ANY(%s) OR a.entity_name ILIKE ANY(%s)
                    )
                    {version_clause}
                    GROUP BY a.entity_name, e.type
                )
                """
                
                # Count
                cur.execute(cte_sql + "SELECT COUNT(*) FROM ranked_matches", query_params)
                total = cur.fetchone()[0]
                
                # Fetch
                cur.execute(cte_sql + "SELECT fqn, type FROM ranked_matches ORDER BY score ASC, fqn ASC LIMIT %s OFFSET %s", query_params + [limit, offset])
                
                rows = cur.fetchall()
                definitions = [{"fqn": r[0], "labels": [r[1]]} for r in rows]
                
                data = {
                    "definitions": definitions,
                    "current_page": page,
                    "total_results": total,
                    "next_page": page + 1 if (offset + limit) < total else None,
                    "system_message": f"Found {total} matches for terms {terms}"
                }
                return dict_to_xml_string(data, "search_definitions_response")
        finally:
            conn.close()

    def get_definitions(self, entity_names: List[str], version: Optional[str] = None) -> str:
        """
        Get full source details for specific entities.
        
        Args:
            entity_names: List of FQNs.
            version: Preferred version. If entity has multiple versions, tries to find the code for THIS version.
        """
        if isinstance(entity_names, str):
            entity_names = [entity_names]
            
        conn = self.store._get_connection()
        try:
            with conn.cursor() as cur:
                # Join Entities -> Sources
                # Filter by version if provided in the Source row's versions array
                query = """
                    SELECT 
                        e.name, e.type, 
                        s.source_code, s.docstring, s.signature
                    FROM entities e
                    JOIN sources s ON e.name = s.entity_name
                    WHERE e.name = ANY(%s)
                """
                params = [entity_names]
                
                if version:
                    query += " AND s.versions @> %s"
                    params.append([version])
                
                # If no version specified, we might get multiple rows (one for each unique content state).
                # We should probably limit or group?
                # For now, let's return all matches.
                
                cur.execute(query, params)
                rows = cur.fetchall()
                
                results = []
                for r in rows:
                    results.append({
                        "name": r[0],
                        "type": r[1],
                        "source": r[2],
                        "docstring": r[3],
                        "signature": r[4]
                    })
                
                data = {
                    "definitions": results,
                    "system_message": f"Retrieved {len(results)} definitions."
                }
                return dict_to_xml_string(data, "get_definitions_response")
        finally:
            conn.close()
