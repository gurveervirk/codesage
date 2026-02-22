from typing import Optional, List, Dict
from collections import defaultdict
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
                query = """
                    SELECT
                        e.name,
                        COALESCE(array_agg(DISTINCT v.version_text) FILTER (WHERE v.version_text IS NOT NULL), '{}') AS versions
                    FROM entities e
                    LEFT JOIN entity_versions ev ON ev.entity_id = e.id
                    LEFT JOIN versions v ON v.id = ev.version_id
                    WHERE (
                        'DISTRIBUTION_PACKAGE' = ANY(e.types)
                        OR 'IMPORT_PACKAGE' = ANY(e.types)
                    )
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
                
                query += " GROUP BY e.name ORDER BY e.name LIMIT 100"
                
                cur.execute(query, params)
                rows = cur.fetchall()
                
                libraries = []
                for r in rows:
                    libraries.append({"name": r[0], "versions": r[1]})
                
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
        page_size: int = 10,
        include_inherited: bool = False,
        base_versions: Optional[Dict[str, str]] = None,
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
            include_inherited: If True, CLASS results are expanded with their inherited members.
            base_versions: Optional mapping of root package name -> version for inherited member
                resolution. Unspecified direct dependencies use the best matching version from
                the package's declared requirements; transitive deps use latest available.
        """
        if isinstance(search_terms, str):
            terms = [t.strip() for t in search_terms.split(',') if t.strip()]
        else:
            terms = search_terms or []
            
        if not terms:
            return dict_to_xml_string({"error": "No search terms provided"}, "error")

        symbols = [t.split('.')[-1] for t in terms]

        limit = page_size
        offset = (page - 1) * page_size
        
        conn = self.store._get_connection()
        try:
            with conn.cursor() as cur:
                dot_term_suffixes = [f"%.{t}" for t in terms]
                dot_symbol_suffixes = [f"%.{s}" for s in symbols]
                symbol_suffixes = [f"%{s}" for s in symbols]
                like_terms = [f"%{t}%" for t in terms]
                like_symbols = [f"%{s}%" for s in symbols]

                version_clause = ""
                version_params: List = []
                if version:
                    version_clause = "AND v.version_text = %s"
                    version_params = [version]

                cte_sql = f"""
                WITH candidates AS (
                    SELECT 
                        e.id AS entity_id,
                        e.name AS fqn,
                        e.types,
                        a.alias AS matched_alias
                    FROM aliases a
                    JOIN entities e ON e.id = a.entity_id
                    UNION ALL
                    SELECT
                        e.id AS entity_id,
                        e.name AS fqn,
                        e.types,
                        NULL::text AS matched_alias
                    FROM entities e
                ),
                ranked_matches AS (
                    SELECT
                        c.entity_id,
                        c.fqn,
                        c.types,
                        MIN(
                            CASE 
                                WHEN COALESCE(c.matched_alias, c.fqn) = ANY(%s) OR c.fqn = ANY(%s) THEN 10
                                WHEN c.fqn ILIKE ANY(%s) THEN 20
                                WHEN c.fqn = ANY(%s) OR c.fqn ILIKE ANY(%s) THEN 30
                                WHEN c.fqn ILIKE ANY(%s) THEN 40
                                ELSE 50
                            END
                        ) AS score
                    FROM candidates c
                    JOIN entity_versions ev ON ev.entity_id = c.entity_id
                    JOIN versions v ON v.id = ev.version_id
                    WHERE (
                        COALESCE(c.matched_alias, c.fqn) = ANY(%s)
                        OR COALESCE(c.matched_alias, c.fqn) ILIKE ANY(%s)
                        OR COALESCE(c.matched_alias, c.fqn) = ANY(%s)
                        OR COALESCE(c.matched_alias, c.fqn) ILIKE ANY(%s)
                        OR c.fqn = ANY(%s)
                        OR c.fqn ILIKE ANY(%s)
                        OR c.fqn = ANY(%s)
                        OR c.fqn ILIKE ANY(%s)
                    )
                    {version_clause}
                    GROUP BY c.entity_id, c.fqn, c.types
                )
                """

                query_params = [
                    terms,
                    terms,
                    dot_term_suffixes,
                    symbols,
                    dot_symbol_suffixes,
                    symbol_suffixes,
                    terms,
                    like_terms,
                    symbols,
                    like_symbols,
                    terms,
                    like_terms,
                    symbols,
                    like_symbols,
                ] + version_params
                
                cur.execute(cte_sql + "SELECT COUNT(*) FROM ranked_matches", query_params)
                total = cur.fetchone()[0]
                
                cur.execute(
                    cte_sql + "SELECT fqn, types FROM ranked_matches ORDER BY score ASC, fqn ASC LIMIT %s OFFSET %s",
                    query_params + [limit, offset],
                )
                
                rows = cur.fetchall()
                definitions = [{"fqn": r[0], "labels": r[1]} for r in rows]

                if include_inherited:
                    class_fqns = [d["fqn"] for d in definitions if "CLASS" in d["labels"]]
                    for class_fqn in class_fqns:
                        inherited = self._get_inherited_members_raw(class_fqn, version, base_versions)
                        for d in definitions:
                            if d["fqn"] == class_fqn:
                                d["inherited_members"] = inherited
                                break

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

    def _resolve_base_versions(
        self,
        cur,
        entity_name: str,
        version: Optional[str],
        explicit_versions: Optional[Dict[str, str]],
    ) -> Dict[str, str]:
        result: Dict[str, str] = {}
        if explicit_versions:
            result.update({k.lower().replace("-", "_"): v for k, v in explicit_versions.items()})

        pkg_root = entity_name.split(".")[0].lower().replace("-", "_")
        cur.execute(
            """
            SELECT e.id, v.id
            FROM entities e
            JOIN entity_versions ev ON ev.entity_id = e.id
            JOIN versions v ON v.id = ev.version_id
            WHERE e.name = %s
              AND 'DISTRIBUTION_PACKAGE' = ANY(e.types)
              AND (%s IS NULL OR v.version_text = %s)
            ORDER BY v.id DESC
            LIMIT 1
            """,
            (pkg_root, version, version),
        )
        row = cur.fetchone()
        if not row:
            return result
        pkg_entity_id, ver_id = row

        cur.execute(
            """
            SELECT dependency_name, version_spec
            FROM package_dependencies
            WHERE package_entity_id = %s AND version_id = %s
            ORDER BY
                CASE WHEN marker IS NULL THEN 0 ELSE 1 END,
                id
            """,
            (pkg_entity_id, ver_id),
        )
        dep_specs: Dict[str, Optional[str]] = {}
        for dep_name_row, ver_spec_row in cur.fetchall():
            if dep_name_row not in dep_specs:
                dep_specs[dep_name_row] = ver_spec_row
        if not dep_specs:
            return result

        cur.execute(
            """
            SELECT e.name, v.version_text
            FROM entities e
            JOIN entity_versions ev ON ev.entity_id = e.id
            JOIN versions v ON v.id = ev.version_id
            WHERE e.name = ANY(%s) AND 'DISTRIBUTION_PACKAGE' = ANY(e.types)
            ORDER BY e.name, v.id DESC
            """,
            (list(dep_specs.keys()),),
        )
        avail: Dict[str, List[str]] = defaultdict(list)
        for dep_name_row, ver_text in cur.fetchall():
            avail[dep_name_row].append(ver_text)

        try:
            from packaging.specifiers import SpecifierSet
            from packaging.version import Version, InvalidVersion
            has_packaging = True
        except ImportError:
            has_packaging = False

        for dep_name, spec_str in dep_specs.items():
            if dep_name in result:
                continue
            versions_for_dep = avail.get(dep_name, [])
            if not versions_for_dep:
                continue
            if not spec_str or not has_packaging:
                result[dep_name] = versions_for_dep[0]
                continue
            spec_set = SpecifierSet(spec_str, prereleases=False)
            for ver_text in versions_for_dep:
                try:
                    if spec_set.contains(Version(ver_text)):
                        result[dep_name] = ver_text
                        break
                except InvalidVersion:
                    continue
            if dep_name not in result:
                result[dep_name] = versions_for_dep[0]

        return result

    _MRO_CTE = """
        WITH RECURSIVE mro AS (
            SELECT
                r.to_entity_id AS base_entity_id,
                r.to_entity_name AS unresolved_name,
                (r.attributes->>'mro_index')::int AS mro_index,
                (r.attributes->>'resolvable')::boolean AS resolvable,
                ARRAY[e.id] AS visited,
                1 AS depth
            FROM entities e
            JOIN entity_versions ev ON ev.entity_id = e.id
            JOIN versions v ON v.id = ev.version_id
            JOIN relations r ON r.from_entity_id = e.id
            WHERE e.name = %s
              AND (%s IS NULL OR v.version_text = %s)
              AND r.rel_type IN ('INTERNAL_INHERITS', 'EXTERNAL_INHERITS')

            UNION ALL

            SELECT
                child_r.to_entity_id,
                child_r.to_entity_name,
                (child_r.attributes->>'mro_index')::int,
                (child_r.attributes->>'resolvable')::boolean,
                mro.visited || mro.base_entity_id,
                mro.depth + 1
            FROM mro
            JOIN relations child_r ON child_r.from_entity_id = mro.base_entity_id
            WHERE mro.base_entity_id IS NOT NULL
              AND NOT (mro.base_entity_id = ANY(mro.visited))
              AND child_r.rel_type IN ('INTERNAL_INHERITS', 'EXTERNAL_INHERITS')
        )
    """

    def get_class_mro(self, entity_name: str, version: Optional[str] = None) -> str:
        """
        Return the full MRO chain for a class entity via recursive traversal of
        INTERNAL_INHERITS and EXTERNAL_INHERITS edges.

        Args:
            entity_name: FQN of the class.
            version: Optional version to identify the correct entity_versions row.
        """
        conn = self.store._get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    self._MRO_CTE +
                    """
                    SELECT
                        COALESCE(b.name, mro.unresolved_name) AS base_fqn,
                        b.name IS NOT NULL AS is_resolved,
                        mro.mro_index,
                        mro.resolvable,
                        mro.depth
                    FROM mro
                    LEFT JOIN entities b ON b.id = mro.base_entity_id
                    ORDER BY mro.depth, mro.mro_index NULLS LAST
                    """,
                    (entity_name, version, version),
                )
                rows = cur.fetchall()
                chain = [
                    {
                        "base_fqn": r[0],
                        "is_resolved": r[1],
                        "mro_index": r[2],
                        "resolvable": r[3],
                        "depth": r[4],
                    }
                    for r in rows
                ]
                data = {"class": entity_name, "version": version, "mro_chain": chain}
                return dict_to_xml_string(data, "get_class_mro_response")
        finally:
            conn.close()

    def _get_inherited_members_raw(
        self,
        entity_name: str,
        version: Optional[str],
        base_versions: Optional[Dict[str, str]],
    ) -> List[Dict]:
        conn = self.store._get_connection()
        try:
            with conn.cursor() as cur:
                resolved = self._resolve_base_versions(cur, entity_name, version, base_versions)

                cur.execute(
                    self._MRO_CTE +
                    """
                    SELECT
                        b.id AS base_id,
                        b.name AS base_fqn,
                        split_part(b.name, '.', 1) AS pkg_root,
                        mro.resolvable,
                        mro.depth,
                        mro.mro_index
                    FROM mro
                    JOIN entities b ON b.id = mro.base_entity_id
                    ORDER BY mro.depth, mro.mro_index NULLS LAST
                    """,
                    (entity_name, version, version),
                )
                mro_rows = cur.fetchall()
                if not mro_rows:
                    return []

                cur.execute(
                    """
                    SELECT split_part(e.name, '.', -1)
                    FROM relations r
                    JOIN entities e ON e.id = r.to_entity_id
                    JOIN entities parent ON parent.id = r.from_entity_id
                    WHERE parent.name = %s
                      AND r.rel_type IN ('HAS_METHOD', 'HAS_FUNCTION', 'HAS_CLASS')
                    """,
                    (entity_name,),
                )
                seen_members: set = {row[0] for row in cur.fetchall()}

                inherited: List[Dict] = []
                for base_id, base_fqn, pkg_root, resolvable, depth, mro_index in mro_rows:
                    if not resolvable:
                        continue
                    pkg_root_norm = pkg_root.lower().replace("-", "_")
                    base_ver = resolved.get(pkg_root_norm)

                    if base_ver:
                        cur.execute(
                            """
                            SELECT e.name, e.types
                            FROM relations r
                            JOIN relation_versions rv ON rv.relation_id = r.id
                            JOIN versions bv ON bv.id = rv.version_id AND bv.version_text = %s
                            JOIN entities e ON e.id = r.to_entity_id
                            WHERE r.from_entity_id = %s
                              AND r.rel_type IN ('HAS_METHOD', 'HAS_FUNCTION', 'HAS_CLASS')
                            """,
                            (base_ver, base_id),
                        )
                    else:
                        cur.execute(
                            """
                            SELECT e.name, e.types
                            FROM relations r
                            JOIN entities e ON e.id = r.to_entity_id
                            WHERE r.from_entity_id = %s
                              AND r.rel_type IN ('HAS_METHOD', 'HAS_FUNCTION', 'HAS_CLASS')
                            """,
                            (base_id,),
                        )

                    for member_name, member_types in cur.fetchall():
                        simple = member_name.split(".")[-1]
                        if simple.startswith("__") and not simple.endswith("__"):
                            continue
                        if simple in seen_members:
                            continue
                        seen_members.add(simple)
                        inherited.append(
                            {
                                "fqn": f"{entity_name}.{simple}",
                                "canonical_fqn": member_name,
                                "types": member_types,
                                "inherited_from": base_fqn,
                                "depth": depth,
                            }
                        )

                return inherited
        finally:
            conn.close()

    def get_inherited_members(
        self,
        entity_name: str,
        version: Optional[str] = None,
        base_versions: Optional[Dict[str, str]] = None,
    ) -> str:
        """
        Return inherited members for a class entity, ordered by MRO with first-occurrence wins.
        Cross-package bases are version-resolved using the package's declared dependencies;
        unspecified transitive dependencies fall back to the latest available version.

        Args:
            entity_name: FQN of the class.
            version: Optional version of the class's own package.
            base_versions: Optional mapping of root package name -> version string to override
                automatic version resolution for base packages.
        """
        inherited = self._get_inherited_members_raw(entity_name, version, base_versions)
        data = {
            "class": entity_name,
            "version": version,
            "inherited_members": inherited,
        }
        return dict_to_xml_string(data, "get_inherited_members_response")

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
                query = """
                    WITH version_filter AS (
                        SELECT id AS version_id
                        FROM versions
                        WHERE (%s IS NULL) OR (version_text = %s)
                    ),
                    module_rows AS (
                        SELECT DISTINCT ON (e.id)
                            e.id AS entity_id,
                            e.name,
                            e.types,
                            ms.source_code AS full_source,
                            ms.docstring AS module_docstring,
                            ms.file_path,
                            NULL::int AS start_line,
                            NULL::int AS end_line,
                            NULL::int AS docstring_start_line,
                            NULL::int AS docstring_end_line,
                            NULL::int AS signature_start_line,
                            NULL::int AS signature_end_line,
                            msv.version_id
                        FROM entities e
                        JOIN module_sources ms ON ms.module_entity_id = e.id
                        JOIN module_source_versions msv ON msv.module_source_id = ms.id
                        JOIN version_filter vf ON vf.version_id = msv.version_id
                        WHERE e.name = ANY(%s)
                          AND 'MODULE' = ANY(e.types)
                        ORDER BY e.id, msv.version_id DESC, ms.id DESC
                    ),
                    definition_rows AS (
                        SELECT DISTINCT ON (e.id)
                            e.id AS entity_id,
                            e.name,
                            e.types,
                            ms.source_code AS full_source,
                            NULL::text AS module_docstring,
                            ms.file_path,
                            loc.start_line,
                            loc.end_line,
                            loc.docstring_start_line,
                            loc.docstring_end_line,
                            loc.signature_start_line,
                            loc.signature_end_line,
                            loc.version_id
                        FROM entities e
                        JOIN entity_definitions ed ON ed.entity_id = e.id
                        JOIN entity_definition_locations loc ON loc.definition_id = ed.id
                        JOIN module_sources ms ON ms.id = loc.module_source_id
                        JOIN version_filter vf ON vf.version_id = loc.version_id
                        WHERE e.name = ANY(%s)
                          AND 'MODULE' <> ALL(e.types)
                        ORDER BY e.id, loc.version_id DESC, ed.id DESC
                    )
                    SELECT
                        x.name,
                        x.types,
                        x.full_source,
                        x.module_docstring,
                        x.file_path,
                        x.start_line,
                        x.end_line,
                        x.docstring_start_line,
                        x.docstring_end_line,
                        x.signature_start_line,
                        x.signature_end_line
                    FROM (
                        SELECT * FROM module_rows
                        UNION ALL
                        SELECT * FROM definition_rows
                    ) x
                    ORDER BY x.name
                """

                cur.execute(query, [version, version, entity_names, entity_names])
                rows = cur.fetchall()
                
                results = []
                for r in rows:
                    (
                        name,
                        types,
                        full_curr_source,
                        module_doc,
                        path,
                        start,
                        end,
                        doc_start,
                        doc_end,
                        sig_start,
                        sig_end,
                    ) = r

                    final_source = ""
                    final_doc = module_doc
                    final_signature = None

                    if full_curr_source and start is not None and end is not None:
                        lines = full_curr_source.splitlines(keepends=True)
                        s_idx = max(0, start - 1)
                        e_idx = min(len(lines), end)
                        final_source = "".join(lines[s_idx:e_idx])

                        if doc_start is not None and doc_end is not None:
                            ds_idx = max(0, doc_start - 1)
                            de_idx = min(len(lines), doc_end)
                            final_doc = "".join(lines[ds_idx:de_idx]).strip()

                        if sig_start is not None and sig_end is not None:
                            ss_idx = max(0, sig_start - 1)
                            se_idx = min(len(lines), sig_end)
                            final_signature = "".join(lines[ss_idx:se_idx]).strip()
                    elif full_curr_source:
                        final_source = full_curr_source

                    results.append(
                        {
                            "name": name,
                            "type": types,
                            "source": final_source,
                            "docstring": final_doc,
                            "signature": final_signature,
                            "file_path": path,
                            "lines": f"{start}-{end}" if start is not None and end is not None else None,
                        }
                    )

                data = {
                    "definitions": results,
                    "system_message": f"Retrieved {len(results)} definitions.",
                }
                return dict_to_xml_string(data, "get_definitions_response")
        finally:
            conn.close()
