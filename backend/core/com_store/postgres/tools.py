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

    def _search_definitions_raw(
        self,
        search_terms: str,
        version: Optional[str] = None,
        page: int = 1,
        page_size: int = 10,
        include_inherited: bool = False,
        base_versions: Optional[Dict[str, str]] = None,
        search_aliases: bool = True,
        search_fqn: bool = True,
        use_regex: bool = False,
        exact_match: bool = False,
        match_case: bool = False,
        kinds: Optional[List[str]] = None,
    ) -> dict:
        if not search_aliases and not search_fqn:
            return {"error": "At least one of search_aliases or search_fqn must be true"}

        if isinstance(search_terms, str):
            terms = [t.strip() for t in search_terms.split(',') if t.strip()]
        else:
            terms = search_terms or []

        if not terms:
            return {"error": "No search terms provided"}

        import re as _re

        if use_regex:
            try:
                flags = 0 if match_case else _re.IGNORECASE
                [_re.compile(t, flags) for t in terms]
            except _re.error as exc:
                return {"error": f"Invalid regex pattern: {exc}"}

        if kinds:
            invalid = [k for k in kinds if k not in self._VALID_KINDS]
            if invalid:
                return {"error": f"Invalid entity kind(s): {invalid}. Valid values: {sorted(self._VALID_KINDS)}"}

        kinds_db_types: List[str] = []
        if kinds:
            for k in kinds:
                if k == "module":    kinds_db_types.append("MODULE")
                elif k == "class":   kinds_db_types.append("CLASS")
                elif k == "function":kinds_db_types.append("FUNCTION")
                elif k == "method":  kinds_db_types.append("METHOD")
                elif k == "package": kinds_db_types.extend(["DISTRIBUTION_PACKAGE", "IMPORT_PACKAGE"])
            kinds_db_types = list(dict.fromkeys(kinds_db_types))
        if kinds_db_types:
            parts = " OR ".join(f"'{t}' = ANY(e.types)" for t in kinds_db_types)
            kinds_where = f"WHERE ({parts})"
        else:
            kinds_where = ""

        symbols = [t.split('.')[-1] for t in terms]
        lower_terms = [t.lower() for t in terms]
        lower_symbols = [s.lower() for s in symbols]

        limit = page_size
        offset = (page - 1) * page_size

        conn = self.store._get_connection()
        try:
            with conn.cursor() as cur:
                dot_term_suffixes = [f"%.{t}" for t in terms]
                dot_symbol_suffixes = [f"%.{s}" for s in symbols]
                symbol_suffixes = [f"%{s}" for s in symbols]
                like_terms = [f"%{t}%" for t in terms]

                version_clause = ""
                version_params: List = []
                alias_version_clause = ""
                alias_version_params: List = []
                if version:
                    version_clause = "AND v.version_text = %s"
                    version_params = [version]
                    alias_version_clause = """
                    JOIN alias_versions av_filter ON av_filter.alias_id = a.id
                    JOIN versions av_ver ON av_ver.id = av_filter.version_id AND av_ver.version_text = %s
                    """
                    alias_version_params = [version]

                alias_branch = f"""
                    SELECT
                        e.id AS entity_id,
                        e.name AS fqn,
                        e.types,
                        a.alias AS matched_alias
                    FROM aliases a
                    JOIN entities e ON e.id = a.entity_id
                    {alias_version_clause}
                    {kinds_where}
                """ if search_aliases else ""

                fqn_branch = f"""
                    SELECT
                        e.id AS entity_id,
                        e.name AS fqn,
                        e.types,
                        NULL::text AS matched_alias
                    FROM entities e
                    {kinds_where}
                """ if search_fqn else ""

                if alias_branch and fqn_branch:
                    candidates_sql = f"({alias_branch} UNION ALL {fqn_branch})"
                elif alias_branch:
                    candidates_sql = f"({alias_branch})"
                else:
                    candidates_sql = f"({fqn_branch})"

                if use_regex:
                    regex_op = "~" if match_case else "~*"
                    score_cases = f"""
                        CASE
                            WHEN c.matched_alias IS NOT NULL AND c.matched_alias {regex_op} ANY(%s) THEN 20
                            WHEN c.matched_alias IS NULL     AND c.fqn             {regex_op} ANY(%s) THEN 20
                            ELSE 50
                        END
                    """
                    where_filter = f"""
                        (c.matched_alias IS NOT NULL AND c.matched_alias {regex_op} ANY(%s))
                        OR (c.fqn {regex_op} ANY(%s))
                    """
                    score_params = [terms, terms]
                    where_params = [terms, terms]
                elif exact_match:
                    if match_case:
                        score_cases = """
                            CASE
                                WHEN c.matched_alias IS NOT NULL AND c.matched_alias = ANY(%s) THEN 5
                                WHEN c.matched_alias IS NULL     AND c.fqn             = ANY(%s) THEN 10
                                ELSE 50
                            END
                        """
                        where_filter = """
                            (c.matched_alias IS NOT NULL AND c.matched_alias = ANY(%s))
                            OR c.fqn = ANY(%s)
                        """
                        score_params = [terms, terms]
                        where_params = [terms, terms]
                    else:
                        score_cases = """
                            CASE
                                WHEN c.matched_alias IS NOT NULL AND lower(c.matched_alias) = ANY(%s) THEN 5
                                WHEN c.matched_alias IS NULL     AND lower(c.fqn)             = ANY(%s) THEN 10
                                ELSE 50
                            END
                        """
                        where_filter = """
                            (c.matched_alias IS NOT NULL AND lower(c.matched_alias) = ANY(%s))
                            OR lower(c.fqn) = ANY(%s)
                        """
                        score_params = [lower_terms, lower_terms]
                        where_params = [lower_terms, lower_terms]
                else:
                    if match_case:
                        score_cases = """
                            CASE
                                WHEN c.matched_alias IS NOT NULL AND c.matched_alias = ANY(%s) THEN 5
                                WHEN c.matched_alias IS NULL     AND c.fqn = ANY(%s) THEN 10
                                WHEN c.matched_alias IS NOT NULL AND c.matched_alias LIKE ANY(%s) THEN 15
                                WHEN c.matched_alias IS NULL     AND c.fqn LIKE ANY(%s) THEN 20
                                WHEN c.matched_alias IS NOT NULL AND (c.matched_alias = ANY(%s) OR c.matched_alias LIKE ANY(%s)) THEN 25
                                WHEN c.matched_alias IS NULL     AND (c.fqn = ANY(%s) OR c.fqn LIKE ANY(%s)) THEN 30
                                WHEN c.matched_alias IS NOT NULL AND c.matched_alias LIKE ANY(%s) THEN 35
                                WHEN c.matched_alias IS NULL     AND c.fqn LIKE ANY(%s) THEN 40
                                ELSE 50
                            END
                        """
                        where_filter = """
                            (c.matched_alias IS NOT NULL AND (
                                c.matched_alias = ANY(%s)
                                OR c.matched_alias LIKE ANY(%s)
                                OR c.matched_alias = ANY(%s)
                                OR c.matched_alias LIKE ANY(%s)
                                OR c.matched_alias LIKE ANY(%s)
                                OR c.matched_alias LIKE ANY(%s)
                            ))
                            OR (
                                c.fqn = ANY(%s)
                                OR c.fqn LIKE ANY(%s)
                                OR c.fqn = ANY(%s)
                                OR c.fqn LIKE ANY(%s)
                                OR c.fqn LIKE ANY(%s)
                                OR c.fqn LIKE ANY(%s)
                            )
                        """
                        score_params = [
                            terms, terms,
                            dot_term_suffixes, dot_term_suffixes,
                            symbols, dot_symbol_suffixes,
                            symbols, dot_symbol_suffixes,
                            symbol_suffixes, symbol_suffixes,
                        ]
                        where_params = [
                            terms, dot_term_suffixes, symbols, dot_symbol_suffixes, symbol_suffixes, like_terms,
                            terms, dot_term_suffixes, symbols, dot_symbol_suffixes, symbol_suffixes, like_terms,
                        ]
                    else:
                        score_cases = """
                            CASE
                                WHEN c.matched_alias IS NOT NULL AND lower(c.matched_alias) = ANY(%s) THEN 5
                                WHEN c.matched_alias IS NULL     AND lower(c.fqn) = ANY(%s) THEN 10
                                WHEN c.matched_alias IS NOT NULL AND c.matched_alias ILIKE ANY(%s) THEN 15
                                WHEN c.matched_alias IS NULL     AND c.fqn ILIKE ANY(%s) THEN 20
                                WHEN c.matched_alias IS NOT NULL AND (lower(c.matched_alias) = ANY(%s) OR c.matched_alias ILIKE ANY(%s)) THEN 25
                                WHEN c.matched_alias IS NULL     AND (lower(c.fqn) = ANY(%s) OR c.fqn ILIKE ANY(%s)) THEN 30
                                WHEN c.matched_alias IS NOT NULL AND c.matched_alias ILIKE ANY(%s) THEN 35
                                WHEN c.matched_alias IS NULL     AND c.fqn ILIKE ANY(%s) THEN 40
                                ELSE 50
                            END
                        """
                        where_filter = """
                            (c.matched_alias IS NOT NULL AND (
                                lower(c.matched_alias) = ANY(%s)
                                OR c.matched_alias ILIKE ANY(%s)
                                OR lower(c.matched_alias) = ANY(%s)
                                OR c.matched_alias ILIKE ANY(%s)
                                OR c.matched_alias ILIKE ANY(%s)
                                OR c.matched_alias ILIKE ANY(%s)
                            ))
                            OR (
                                lower(c.fqn) = ANY(%s)
                                OR c.fqn ILIKE ANY(%s)
                                OR lower(c.fqn) = ANY(%s)
                                OR c.fqn ILIKE ANY(%s)
                                OR c.fqn ILIKE ANY(%s)
                                OR c.fqn ILIKE ANY(%s)
                            )
                        """
                        score_params = [
                            lower_terms, lower_terms,
                            dot_term_suffixes, dot_term_suffixes,
                            lower_symbols, dot_symbol_suffixes,
                            lower_symbols, dot_symbol_suffixes,
                            symbol_suffixes, symbol_suffixes,
                        ]
                        where_params = [
                            lower_terms, dot_term_suffixes, lower_symbols, dot_symbol_suffixes, symbol_suffixes, like_terms,
                            lower_terms, dot_term_suffixes, lower_symbols, dot_symbol_suffixes, symbol_suffixes, like_terms,
                        ]

                cte_sql = f"""
                WITH candidates AS {candidates_sql},
                scored_candidates AS (
                    SELECT
                        c.entity_id,
                        c.fqn,
                        c.types,
                        COALESCE(c.matched_alias, c.fqn) AS matched_name,
                        CASE WHEN c.matched_alias IS NOT NULL THEN 'alias' ELSE 'fqn' END AS match_kind,
                        {score_cases} AS score
                    FROM candidates c
                    JOIN entity_versions ev ON ev.entity_id = c.entity_id
                    JOIN versions v ON v.id = ev.version_id
                    WHERE ({where_filter})
                    AND score < 50
                    {version_clause}
                ),
                best_per_entity AS (
                    SELECT DISTINCT ON (entity_id)
                        entity_id, fqn, types, matched_name, match_kind, score
                    FROM scored_candidates
                    ORDER BY entity_id, score ASC, match_kind ASC
                ),
                ranked_matches AS (
                    SELECT entity_id, fqn, types, matched_name, match_kind, score
                    FROM best_per_entity
                )
                """

                query_params = alias_version_params + score_params + where_params + version_params

                cur.execute(cte_sql + "SELECT COUNT(*) FROM ranked_matches", query_params)
                total = cur.fetchone()[0]

                cur.execute(
                    cte_sql + "SELECT entity_id, fqn, types, matched_name, match_kind FROM ranked_matches ORDER BY score ASC, fqn ASC LIMIT %s OFFSET %s",
                    query_params + [limit, offset],
                )
                rows = cur.fetchall()

                entity_ids = [r[0] for r in rows]
                fqn_map: Dict[int, str] = {r[0]: r[1] for r in rows}
                types_map: Dict[int, list] = {r[0]: r[2] for r in rows}
                primary_map: Dict[int, dict] = {r[0]: {"name": r[3], "kind": r[4]} for r in rows}

                aliases_map: Dict[int, List[str]] = {eid: [] for eid in entity_ids}
                if entity_ids:
                    if version:
                        cur.execute(
                            """
                            SELECT a.entity_id, a.alias
                            FROM aliases a
                            JOIN alias_versions av ON av.alias_id = a.id
                            JOIN versions v ON v.id = av.version_id
                            WHERE a.entity_id = ANY(%s)
                              AND v.version_text = %s
                            ORDER BY a.alias
                            """,
                            (entity_ids, version),
                        )
                    else:
                        cur.execute(
                            "SELECT entity_id, alias FROM aliases WHERE entity_id = ANY(%s) ORDER BY alias",
                            (entity_ids,),
                        )
                    for eid, alias in cur.fetchall():
                        if eid in aliases_map:
                            aliases_map[eid].append(alias)

                terms_set = set(lower_terms)
                definitions = []
                for eid in entity_ids:
                    fqn = fqn_map[eid]
                    primary = primary_map[eid]
                    raw_aliases = aliases_map[eid]

                    all_members = [{"name": fqn, "kind": "fqn"}] + [{"name": a, "kind": "alias"} for a in raw_aliases]
                    members = [m for m in all_members if m["name"] != primary["name"]]
                    members.sort(key=lambda m: (0 if m["name"].lower() in terms_set else 1, len(m["name"])))

                    definition = {
                        "labels": types_map[eid],
                        "primary": primary,
                        "members": members,
                    }

                    if include_inherited and "CLASS" in types_map[eid]:
                        inherited = self._get_inherited_members_raw(fqn, version, base_versions)
                        definition["inherited_members"] = inherited

                    definitions.append(definition)

                data = {
                    "definitions": definitions,
                    "current_page": page,
                    "total_results": total,
                    "next_page": page + 1 if (offset + limit) < total else None,
                    "system_message": f"Found {total} matches for terms {terms}"
                }
                return data
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
        search_aliases: bool = True,
        search_fqn: bool = True,
        use_regex: bool = False,
        exact_match: bool = False,
        match_case: bool = False,
        kinds: Optional[List[str]] = None,
    ) -> str:
        """
        Search for definitions by aliases or FQNs.

        Ranking tiers (normal mode):
        1. Exact alias match (5) or exact FQN match (10)
        2. Dot-suffix alias (15) or FQN (20): 'pandas.DataFrame' matches 'core.frame.DataFrame'
        3. Symbol exact/dot-symbol alias (25) or FQN (30)
        4. Suffix alias (35) or FQN (40): 'DataFrame' matches 'MyDataFrame'
        5. Partial match (50, excluded)

        Results are grouped as communities: each entity's best-scoring alias/FQN is the
        primary result; all other aliases and the FQN are returned as members tagged with kind.

        Args:
            search_terms: Comma-separated list of search terms (aliases, FQNs, or symbol names).
            version: Optional version to filter by.
            page: Page number (1-indexed).
            page_size: Number of results per page.
            include_inherited: If True, CLASS results are expanded with their inherited members.
            base_versions: Optional mapping of root package name -> version for inherited member
                resolution.
            search_aliases: Include alias-based matching (default True).
            search_fqn: Include FQN-based matching (default True).
            use_regex: Treat terms as regex patterns; replaces tiered scoring with a flat score.
            exact_match: Only exact equality matches; disables suffix/partial tiers.
            match_case: Case-sensitive matching (default False).
        """
        data = self._search_definitions_raw(
            search_terms, version, page, page_size, include_inherited, base_versions,
            search_aliases, search_fqn, use_regex, exact_match, match_case, kinds,
        )
        if "error" in data:
            return dict_to_xml_string(data, "error")
        return dict_to_xml_string(data, "search_definitions_response")

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

    _VALID_KINDS = frozenset({"module", "class", "function", "method", "package"})
    _VALID_FIELDS = frozenset({"source", "signature", "docstring", "file_info"})

    def _get_definitions_raw(
        self,
        entity_names: List[str],
        version: Optional[str] = None,
        context_lines: int = 20,
        include_full_source: bool = False,
        fields: Optional[List[str]] = None,
    ) -> List[Dict]:
        if isinstance(entity_names, str):
            entity_names = [entity_names]

        if fields is None:
            fields = ["source"]
        fields_set = set(fields) & self._VALID_FIELDS

        want_source    = "source"    in fields_set
        want_signature = "signature" in fields_set
        want_docstring = "docstring" in fields_set
        want_file_info = "file_info" in fields_set

        source_col    = "ms.source_code" if want_source    else "NULL::text"
        docstring_col = "ms.docstring"   if want_docstring else "NULL::text"
        file_path_col = "ms.file_path"   if want_file_info else "NULL::text"
        start_col     = "loc.start_line" if want_file_info else "NULL::int"
        end_col       = "loc.end_line"   if want_file_info else "NULL::int"
        doc_s_col     = "loc.docstring_start_line" if want_docstring else "NULL::int"
        doc_e_col     = "loc.docstring_end_line"   if want_docstring else "NULL::int"
        sig_s_col     = "loc.signature_start_line" if want_signature else "NULL::int"
        sig_e_col     = "loc.signature_end_line"   if want_signature else "NULL::int"

        conn = self.store._get_connection()
        try:
            with conn.cursor() as cur:
                query = f"""
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
                            {source_col}      AS full_source,
                            {docstring_col}   AS module_docstring,
                            {file_path_col}   AS file_path,
                            NULL::int         AS start_line,
                            NULL::int         AS end_line,
                            NULL::int         AS docstring_start_line,
                            NULL::int         AS docstring_end_line,
                            NULL::int         AS signature_start_line,
                            NULL::int         AS signature_end_line,
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
                        SELECT DISTINCT ON (e.id, ed.id)
                            e.id AS entity_id,
                            e.name,
                            e.types,
                            {source_col}  AS full_source,
                            NULL::text    AS module_docstring,
                            {file_path_col} AS file_path,
                            {start_col}   AS start_line,
                            {end_col}     AS end_line,
                            {doc_s_col}   AS docstring_start_line,
                            {doc_e_col}   AS docstring_end_line,
                            {sig_s_col}   AS signature_start_line,
                            {sig_e_col}   AS signature_end_line,
                            loc.version_id
                        FROM entities e
                        JOIN entity_definitions ed ON ed.entity_id = e.id
                        JOIN entity_definition_locations loc ON loc.definition_id = ed.id
                        JOIN module_sources ms ON ms.id = loc.module_source_id
                        JOIN version_filter vf ON vf.version_id = loc.version_id
                        WHERE e.name = ANY(%s)
                          AND 'MODULE' <> ALL(e.types)
                        ORDER BY e.id, ed.id, loc.version_id DESC
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
                    final_doc = module_doc if want_docstring else None
                    final_signature = None

                    context_source = None
                    context_start_line = None
                    context_end_line = None

                    if want_source and full_curr_source and start is not None and end is not None:
                        lines = full_curr_source.splitlines(keepends=True)
                        s_idx = max(0, start - 1)
                        e_idx = min(len(lines), end)
                        final_source = "".join(lines[s_idx:e_idx])

                        ctx_s_idx = max(0, start - 1 - context_lines)
                        ctx_e_idx = min(len(lines), end + context_lines)
                        context_source = "".join(lines[ctx_s_idx:ctx_e_idx])
                        context_start_line = ctx_s_idx + 1
                        context_end_line = ctx_e_idx

                        if want_docstring and doc_start is not None and doc_end is not None:
                            ds_idx = max(0, doc_start - 1)
                            de_idx = min(len(lines), doc_end)
                            final_doc = "".join(lines[ds_idx:de_idx]).strip()

                        if want_signature and sig_start is not None and sig_end is not None:
                            ss_idx = max(0, sig_start - 1)
                            se_idx = min(len(lines), sig_end)
                            final_signature = "".join(lines[ss_idx:se_idx]).strip()
                    elif want_source and full_curr_source:
                        final_source = full_curr_source

                    results.append(
                        {
                            "name": name,
                            "type": types,
                            "source": final_source,
                            "docstring": final_doc,
                            "signature": final_signature,
                            "file_path": path,
                            "lines": (f"{start}-{end}" if start is not None and end is not None else None) if want_file_info else None,
                            "context_source": context_source,
                            "context_start_line": context_start_line,
                            "context_end_line": context_end_line,
                            "entity_start_line": start if want_file_info else None,
                            "entity_end_line": end if want_file_info else None,
                            "full_source": full_curr_source if include_full_source and want_source and start is not None else None,
                        }
                    )

                return results
        finally:
            conn.close()

    def get_definitions(self, entity_names: List[str], version: Optional[str] = None, fields: Optional[List[str]] = None) -> str:
        """
        Get source details for specific entities.

        Args:
            entity_names: List of FQNs.
            version: Preferred version. If entity has multiple versions, tries to find the code for THIS version.
            fields: List of fields to include in the response. Supported: 'source', 'signature',
                'docstring', 'file_info'. Defaults to ['source'].
        """
        results = self._get_definitions_raw(entity_names, version, fields=fields)
        data = {
            "definitions": results,
            "system_message": f"Retrieved {len(results)} definitions.",
        }
        return dict_to_xml_string(data, "get_definitions_response")

    def get_module_symbols(
        self,
        module_name: str,
        version: Optional[str] = None,
        reexports_only: bool = False,
    ) -> str:
        """
        Get all symbols defined or re-exported by a module.

        Args:
            module_name: FQN of the module entity.
            version: Optional version filter.
            reexports_only: If True, only return symbols marked as re-exports.
        """
        conn = self.store._get_connection()
        try:
            with conn.cursor() as cur:
                query = """
                    SELECT
                        ms.symbol_name,
                        ms.origin,
                        e.name AS entity_fqn,
                        ms.source_fqn,
                        ms.condition,
                        ms.line_no,
                        ms.parent_block_start_line,
                        ms.is_reexport
                    FROM module_symbols ms
                    JOIN entities mod_e ON mod_e.id = ms.module_entity_id
                    JOIN module_symbol_versions msv ON msv.module_symbol_id = ms.id
                    JOIN versions v ON v.id = msv.version_id
                    LEFT JOIN entities e ON e.id = ms.entity_id
                    WHERE mod_e.name = %s
                      AND (%s IS NULL OR v.version_text = %s)
                """
                params: List = [module_name, version, version]

                if reexports_only:
                    query += " AND ms.is_reexport = TRUE"

                query += " ORDER BY ms.symbol_name"

                cur.execute(query, params)
                rows = cur.fetchall()

                symbols = [
                    {
                        "symbol_name": r[0],
                        "origin": r[1],
                        "entity_fqn": r[2],
                        "source_fqn": r[3],
                        "condition": r[4],
                        "line_no": r[5],
                        "parent_block_start_line": r[6],
                        "is_reexport": r[7],
                    }
                    for r in rows
                ]

                data = {
                    "module": module_name,
                    "version": version,
                    "symbols": symbols,
                    "system_message": f"Found {len(symbols)} symbols for module '{module_name}'.",
                }
                return dict_to_xml_string(data, "get_module_symbols_response")
        finally:
            conn.close()

    def get_decorator_details(
        self,
        entity_name: str,
        version: Optional[str] = None,
    ) -> str:
        """
        Get decorator details for a specific entity.

        Args:
            entity_name: FQN of the entity.
            version: Optional version filter.
        """
        conn = self.store._get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT dd.details
                    FROM decorator_details dd
                    JOIN entities e ON e.id = dd.entity_id
                    JOIN decorator_detail_versions ddv ON ddv.decorator_detail_id = dd.id
                    JOIN versions v ON v.id = ddv.version_id
                    WHERE e.name = %s
                      AND (%s IS NULL OR v.version_text = %s)
                    ORDER BY v.id DESC
                    LIMIT 1
                    """,
                    (entity_name, version, version),
                )
                row = cur.fetchone()
                details = row[0] if row else None

                data = {
                    "entity": entity_name,
                    "version": version,
                    "decorator_details": details,
                }
                return dict_to_xml_string(data, "get_decorator_details_response")
        finally:
            conn.close()

    def get_alias_hops(
        self,
        entity_name: str,
        alias: str,
        version: Optional[str] = None,
    ) -> str:
        """
        Get the alias resolution chain (hops) for a given alias pointing to an entity.

        Args:
            entity_name: FQN of the canonical entity the alias refers to.
            alias: The alias string.
            version: Optional version filter.
        """
        conn = self.store._get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        ah.hop_order,
                        ms.file_path,
                        ah.line_no,
                        te.name AS target_entity_fqn,
                        ah.target_entity_name
                    FROM alias_hops ah
                    JOIN aliases a ON a.id = ah.alias_id
                    JOIN entities canonical_e ON canonical_e.id = a.entity_id
                    LEFT JOIN module_sources ms ON ms.id = ah.module_source_id
                    LEFT JOIN entities te ON te.id = ah.target_entity_id
                    JOIN alias_hop_versions ahv ON ahv.alias_hop_id = ah.id
                    JOIN versions v ON v.id = ahv.version_id
                    WHERE canonical_e.name = %s
                      AND a.alias = %s
                      AND (%s IS NULL OR v.version_text = %s)
                    ORDER BY ah.hop_order
                    """,
                    (entity_name, alias, version, version),
                )
                rows = cur.fetchall()

                hops = [
                    {
                        "hop_order": r[0],
                        "file_path": r[1],
                        "line_no": r[2],
                        "target_entity_fqn": r[3],
                        "target_entity_name": r[4],
                    }
                    for r in rows
                ]

                data = {
                    "entity": entity_name,
                    "alias": alias,
                    "version": version,
                    "hops": hops,
                    "system_message": f"Found {len(hops)} hop(s) for alias '{alias}'.",
                }
                return dict_to_xml_string(data, "get_alias_hops_response")
        finally:
            conn.close()
