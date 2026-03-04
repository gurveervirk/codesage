import os
import re
import json
import logging
from typing import List, Dict, Optional, Tuple
from ...com_extractor import Entity

try:
    import psycopg2
    from psycopg2.extras import Json, execute_values
except ImportError:
    psycopg2 = None
    Json = None
    execute_values = None

logger = logging.getLogger(__name__)

_LTREE_LABEL_RE = re.compile(r'[^A-Za-z0-9_]')
_DEP_NAME_RE = re.compile(r'^([A-Za-z0-9]([A-Za-z0-9._-]*[A-Za-z0-9])?)', re.ASCII)


def _name_to_ltree(name: str) -> Optional[str]:
    if not name:
        return None
    parts = name.split('.')
    sanitized = [_LTREE_LABEL_RE.sub('_', p) or '_' for p in parts]
    return '.'.join(sanitized)


def _parse_dep(dep_str: str) -> Tuple[Optional[str], Optional[str]]:
    dep_str = dep_str.split(';')[0].strip()
    m = _DEP_NAME_RE.match(dep_str)
    if not m:
        return None, None
    pkg_name = m.group(1).strip().lower().replace('-', '_').replace('.', '_')
    spec = dep_str[m.end():].strip() or None
    return pkg_name, spec

class PostgresCOMStore:
    """Postgres (Supabase) storage implementation for Code Object Model."""

    def __init__(self, connection_string: str = None):
        self.connection_string = connection_string or os.getenv("SUPABASE_DB_URL")
        if not self.connection_string:
            raise ValueError("Postgres connection string is required.")

        if not psycopg2:
            raise ImportError("psycopg2 is required. Install with `pip install psycopg2-binary`")

    def _get_connection(self):
        return psycopg2.connect(self.connection_string)

    def _read_schema_sql(self) -> str:
        schema_path = os.path.join(os.path.dirname(__file__), "schema.sql")
        if not os.path.exists(schema_path):
            raise FileNotFoundError(f"Schema file not found at {schema_path}")
        with open(schema_path, "r") as f:
            return f.read()

    def _non_destructive_schema_sql(self, schema_sql: str) -> str:
        return re.sub(
            r"DROP\s+TABLE\s+IF\s+EXISTS\s+.*?\s+CASCADE\s*;",
            "",
            schema_sql,
            flags=re.IGNORECASE | re.DOTALL,
        )

    def _idempotent_schema_sql(self, schema_sql: str) -> str:
        schema_sql = re.sub(
            r"\bCREATE\s+TABLE\s+([a-zA-Z_][a-zA-Z0-9_]*)",
            r"CREATE TABLE IF NOT EXISTS \1",
            schema_sql,
            flags=re.IGNORECASE,
        )
        schema_sql = re.sub(
            r"\bCREATE\s+UNIQUE\s+INDEX\s+([a-zA-Z_][a-zA-Z0-9_]*)",
            r"CREATE UNIQUE INDEX IF NOT EXISTS \1",
            schema_sql,
            flags=re.IGNORECASE,
        )
        schema_sql = re.sub(
            r"\bCREATE\s+INDEX\s+([a-zA-Z_][a-zA-Z0-9_]*)",
            r"CREATE INDEX IF NOT EXISTS \1",
            schema_sql,
            flags=re.IGNORECASE,
        )
        return schema_sql

    def _is_source_entity(self, name: str, labels: List[str]) -> bool:
        return name.endswith("::SOURCE") or "SOURCE" in labels

    def init_schema(self):
        """Initialize schema without destructive drop/reset."""
        try:
            schema_sql = self._idempotent_schema_sql(
                self._non_destructive_schema_sql(self._read_schema_sql())
            )

            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(schema_sql)
                conn.commit()
                logger.info("Initialized Postgres schema (non-destructive).")
        except Exception as e:
            if psycopg2 and isinstance(e, psycopg2.Error) and getattr(e, "pgcode", None) in {"42P07", "42710"}:
                logger.info("Postgres schema already exists; continuing without reset.")
                return
            logger.error(f"Failed to initialize schema: {e}")
            raise

    def reset_schema(self) -> None:
        """Perform full schema reset (drop + recreate) using schema.sql."""
        try:
            schema_sql = self._read_schema_sql()

            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(schema_sql)
                conn.commit()
                logger.warning("Reset Postgres schema (drop + recreate).")
        except Exception as e:
            logger.error(f"Failed to reset Postgres schema: {e}")
            raise

    def purge_all_data(self) -> None:
        """Backward-compatible alias for full reset behavior."""
        self.reset_schema()

    def _hash_to_bytes(self, value: Optional[str]) -> bytes:
        if not value:
            return b""
        try:
            return bytes.fromhex(value)
        except ValueError:
            return value.encode("utf-8", errors="ignore")

    def _to_int_or_none(self, value):
        if value is None:
            return None
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            cleaned = value.strip()
            if not cleaned:
                return None
            try:
                return int(cleaned)
            except ValueError:
                return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _get_version_id(self, cur, version_text: str) -> int:
        cur.execute(
            """
            INSERT INTO versions (version_text)
            VALUES (%s)
            ON CONFLICT (version_text) DO UPDATE SET version_text = EXCLUDED.version_text
            RETURNING id
            """,
            (version_text,),
        )
        return cur.fetchone()[0]

    def _upsert_entities(self, cur, entity_rows: List[Dict]) -> Dict[str, int]:
        if not entity_rows:
            return {}
        values = [(r["name"], r["types"], r["meta_labels"], _name_to_ltree(r["name"])) for r in entity_rows]
        execute_values(
            cur,
            """
            INSERT INTO entities (name, types, meta_labels, path)
            VALUES %s
            ON CONFLICT (name) DO UPDATE SET
                types = COALESCE(
                    (SELECT array_agg(DISTINCT t) FROM unnest(entities.types || EXCLUDED.types) t),
                    '{}'::text[]
                ),
                meta_labels = COALESCE(
                    (SELECT array_agg(DISTINCT l) FROM unnest(entities.meta_labels || EXCLUDED.meta_labels) l),
                    '{}'::text[]
                ),
                path = COALESCE(EXCLUDED.path, entities.path)
            """,
            values,
        )

        cur.execute("SELECT id, name FROM entities WHERE name = ANY(%s)", ([r["name"] for r in entity_rows],))
        return {name: entity_id for entity_id, name in cur.fetchall()}

    def _upsert_entity_versions(self, cur, rows: List[Tuple[int, int]]):
        if not rows:
            return
        execute_values(
            cur,
            """
            INSERT INTO entity_versions (entity_id, version_id)
            VALUES %s
            ON CONFLICT (entity_id, version_id) DO NOTHING
            """,
            rows,
        )

    def _upsert_module_sources(self, cur, rows: List[Dict]) -> None:
        if not rows:
            return
        values = [
            (
                r["module_entity_id"],
                r["source_hash"],
                r.get("source_code"),
                r.get("docstring"),
                r.get("file_path"),
            )
            for r in rows
        ]
        execute_values(
            cur,
            """
            INSERT INTO module_sources (module_entity_id, source_hash, source_code, docstring, file_path)
            VALUES %s
            ON CONFLICT (module_entity_id, source_hash) DO NOTHING
            """,
            values,
        )

    def _upsert_module_source_versions(self, cur, rows: List[Tuple[int, bytes, int]]):
        if not rows:
            return
        execute_values(
            cur,
            """
            INSERT INTO module_source_versions (module_source_id, version_id)
            SELECT ms.id, t.version_id
            FROM (VALUES %s) AS t(module_entity_id, source_hash, version_id)
            JOIN module_sources ms
              ON ms.module_entity_id = t.module_entity_id
             AND ms.source_hash = t.source_hash
            ON CONFLICT (module_source_id, version_id) DO NOTHING
            """,
            rows,
        )

    def _upsert_entity_definitions(self, cur, rows: List[Dict]) -> None:
        if not rows:
            return
        values = [(r["entity_id"], r["source_hash"]) for r in rows]
        execute_values(
            cur,
            """
            INSERT INTO entity_definitions (entity_id, source_hash)
            VALUES %s
            ON CONFLICT (entity_id, source_hash) DO NOTHING
            """,
            values,
        )

    def _upsert_entity_definition_versions(self, cur, rows: List[Tuple[int, bytes, int]]):
        if not rows:
            return
        execute_values(
            cur,
            """
            INSERT INTO entity_definition_versions (definition_id, version_id)
            SELECT ed.id, t.version_id
            FROM (VALUES %s) AS t(entity_id, source_hash, version_id)
            JOIN entity_definitions ed
              ON ed.entity_id = t.entity_id
             AND ed.source_hash = t.source_hash
            ON CONFLICT (definition_id, version_id) DO NOTHING
            """,
            rows,
        )

    def _upsert_entity_definition_locations(self, cur, rows: List[Tuple]):
        if not rows:
            return
        execute_values(
            cur,
            """
            INSERT INTO entity_definition_locations (
                definition_id,
                version_id,
                module_source_id,
                start_line,
                end_line,
                docstring_start_line,
                docstring_end_line,
                signature_start_line,
                signature_end_line
            )
            SELECT
                ed.id,
                t.version_id,
                ms.id,
                t.start_line::integer,
                t.end_line::integer,
                t.docstring_start_line::integer,
                t.docstring_end_line::integer,
                t.signature_start_line::integer,
                t.signature_end_line::integer
            FROM (VALUES %s) AS t(
                entity_id,
                definition_hash,
                module_entity_id,
                module_source_hash,
                version_id,
                start_line,
                end_line,
                docstring_start_line,
                docstring_end_line,
                signature_start_line,
                signature_end_line
            )
            JOIN entity_definitions ed
              ON ed.entity_id = t.entity_id
             AND ed.source_hash = t.definition_hash
            JOIN module_sources ms
              ON ms.module_entity_id = t.module_entity_id
             AND ms.source_hash = t.module_source_hash
            ON CONFLICT (definition_id, version_id) DO UPDATE SET
                start_line = CASE WHEN entity_definition_locations.start_line IS NULL
                                  THEN EXCLUDED.start_line
                                  ELSE entity_definition_locations.start_line END,
                end_line = CASE WHEN entity_definition_locations.end_line IS NULL
                                THEN EXCLUDED.end_line
                                ELSE entity_definition_locations.end_line END,
                signature_start_line = CASE WHEN entity_definition_locations.signature_start_line IS NULL
                                            THEN EXCLUDED.signature_start_line
                                            ELSE entity_definition_locations.signature_start_line END,
                signature_end_line = CASE WHEN entity_definition_locations.signature_end_line IS NULL
                                          THEN EXCLUDED.signature_end_line
                                          ELSE entity_definition_locations.signature_end_line END,
                docstring_start_line = CASE WHEN entity_definition_locations.docstring_start_line IS NULL
                                            THEN EXCLUDED.docstring_start_line
                                            ELSE entity_definition_locations.docstring_start_line END,
                docstring_end_line = CASE WHEN entity_definition_locations.docstring_end_line IS NULL
                                          THEN EXCLUDED.docstring_end_line
                                          ELSE entity_definition_locations.docstring_end_line END
            """,
            rows,
        )

    def _upsert_relations(self, cur, rows: List[Dict]) -> None:
        if not rows:
            return

        internal = []
        external = []
        for r in rows:
            if r.get("to_entity_id") is not None:
                internal.append((r["from_entity_id"], r["to_entity_id"], r["rel_type"], Json(r.get("attributes", {}))))
            else:
                external.append((r["from_entity_id"], r["to_entity_name"], r["rel_type"], Json(r.get("attributes", {}))))

        if internal:
            execute_values(
                cur,
                """
                INSERT INTO relations (from_entity_id, to_entity_id, rel_type, attributes)
                VALUES %s
                ON CONFLICT (from_entity_id, to_entity_id, rel_type)
                WHERE to_entity_id IS NOT NULL
                DO UPDATE SET attributes = relations.attributes || EXCLUDED.attributes
                """,
                internal,
            )

        if external:
            execute_values(
                cur,
                """
                INSERT INTO relations (from_entity_id, to_entity_name, rel_type, attributes)
                VALUES %s
                ON CONFLICT (from_entity_id, to_entity_name, rel_type)
                WHERE to_entity_id IS NULL
                DO UPDATE SET attributes = relations.attributes || EXCLUDED.attributes
                """,
                external,
            )

    def _upsert_relation_versions(self, cur, rows: List[Tuple]):
        if not rows:
            return
        execute_values(
            cur,
            """
            INSERT INTO relation_versions (relation_id, version_id)
            SELECT r.id, t.version_id::bigint
            FROM (VALUES %s) AS t(from_entity_id, to_entity_id, to_entity_name, rel_type, version_id)
            JOIN relations r
                ON r.from_entity_id = t.from_entity_id::bigint
                AND r.rel_type = t.rel_type::text
             AND (
                (t.to_entity_id IS NOT NULL AND r.to_entity_id = t.to_entity_id::bigint)
                OR (t.to_entity_id IS NULL AND r.to_entity_id IS NULL AND r.to_entity_name = t.to_entity_name::text)
             )
            ON CONFLICT (relation_id, version_id) DO NOTHING
            """,
            rows,
        )

    def _upsert_aliases(self, cur, rows: List[Tuple[int, str]]) -> None:
        if not rows:
            return
        execute_values(
            cur,
            """
            INSERT INTO aliases (entity_id, alias)
            VALUES %s
            ON CONFLICT (entity_id, alias) DO NOTHING
            """,
            rows,
        )

    def _upsert_alias_versions(self, cur, rows: List[Tuple[int, str, int]]) -> None:
        if not rows:
            return
        execute_values(
            cur,
            """
            INSERT INTO alias_versions (alias_id, version_id)
            SELECT a.id, t.version_id
            FROM (VALUES %s) AS t(entity_id, alias, version_id)
            JOIN aliases a ON a.entity_id = t.entity_id AND a.alias = t.alias
            ON CONFLICT (alias_id, version_id) DO NOTHING
            """,
            rows,
        )

    def _upsert_module_symbols(self, cur, rows: List[Tuple]) -> None:
        if not rows:
            return
        execute_values(
            cur,
            """
            INSERT INTO module_symbols
              (module_entity_id, symbol_name, origin, entity_id, source_fqn, condition, line_no, parent_block_start_line, is_reexport)
            VALUES %s
            ON CONFLICT (module_entity_id, symbol_name, COALESCE(condition, '')) DO NOTHING
            """,
            rows,
        )

    def _upsert_module_symbol_versions(self, cur, rows: List[Tuple]) -> None:
        if not rows:
            return
        execute_values(
            cur,
            """
            INSERT INTO module_symbol_versions (module_symbol_id, version_id)
            SELECT ms.id, t.version_id
            FROM (VALUES %s) AS t(module_entity_id, symbol_name, condition, version_id)
            JOIN module_symbols ms
              ON ms.module_entity_id = t.module_entity_id::bigint
             AND ms.symbol_name = t.symbol_name
             AND COALESCE(ms.condition, '') = COALESCE(t.condition, '')
            ON CONFLICT (module_symbol_id, version_id) DO NOTHING
            """,
            rows,
        )

    def _upsert_alias_hops(self, cur, rows: List[Tuple]) -> None:
        if not rows:
            return
        execute_values(
            cur,
            """
            INSERT INTO alias_hops
              (alias_id, hop_order, module_source_id, line_no, target_entity_id, target_entity_name)
            SELECT a.id, t.hop_order, t.module_source_id::bigint, t.line_no,
                   t.target_entity_id::bigint, t.target_entity_name
            FROM (VALUES %s) AS t(entity_id, alias_text, hop_order,
                                  module_source_id, line_no, target_entity_id, target_entity_name)
            JOIN aliases a ON a.entity_id = t.entity_id::bigint AND a.alias = t.alias_text
            ON CONFLICT (alias_id, hop_order) DO NOTHING
            """,
            rows,
        )

    def _upsert_alias_hop_versions(self, cur, rows: List[Tuple]) -> None:
        if not rows:
            return
        execute_values(
            cur,
            """
            INSERT INTO alias_hop_versions (alias_hop_id, version_id)
            SELECT ah.id, t.version_id
            FROM (VALUES %s) AS t(entity_id, alias_text, hop_order, version_id)
            JOIN aliases a ON a.entity_id = t.entity_id::bigint AND a.alias = t.alias_text
            JOIN alias_hops ah ON ah.alias_id = a.id AND ah.hop_order = t.hop_order::integer
            ON CONFLICT (alias_hop_id, version_id) DO NOTHING
            """,
            rows,
        )

    def _upsert_package_dependencies(self, cur, rows: List[Tuple]) -> None:        
        if not rows:
            return
        execute_values(
            cur,
            """
            INSERT INTO package_dependencies (package_entity_id, version_id, dependency_name, version_spec, marker, extras)
            VALUES %s
            ON CONFLICT (package_entity_id, version_id, dependency_name, COALESCE(marker, '')) DO UPDATE SET
                version_spec = EXCLUDED.version_spec,
                extras = EXCLUDED.extras
            """,
            rows,
        )

    def _upsert_decorator_details(self, cur, rows: List[Tuple[int, bytes, Dict]]) -> None:
        if not rows:
            return
        execute_values(
            cur,
            """
            INSERT INTO decorator_details (entity_id, source_hash, details)
            VALUES %s
            ON CONFLICT (entity_id, source_hash) DO UPDATE SET details = EXCLUDED.details
            """,
            [(entity_id, source_hash, Json(details)) for entity_id, source_hash, details in rows],
        )

    def _upsert_decorator_detail_versions(self, cur, rows: List[Tuple[int, bytes, int]]) -> None:
        if not rows:
            return
        execute_values(
            cur,
            """
            INSERT INTO decorator_detail_versions (decorator_detail_id, version_id)
            SELECT d.id, t.version_id
            FROM (VALUES %s) AS t(entity_id, source_hash, version_id)
            JOIN decorator_details d
              ON d.entity_id = t.entity_id
             AND d.source_hash IS NOT DISTINCT FROM t.source_hash
            ON CONFLICT (decorator_detail_id, version_id) DO NOTHING
            """,
            rows,
        )

    def _fetch_existing_module_sources(self, cur, pairs: List[Tuple]) -> set:
        if not pairs:
            return set()
        results = execute_values(
            cur,
            """
            SELECT ms.module_entity_id, ms.source_hash
            FROM module_sources ms
            JOIN (VALUES %s) AS t(module_entity_id, source_hash)
              ON ms.module_entity_id = t.module_entity_id::bigint
             AND ms.source_hash = t.source_hash::bytea
            """,
            pairs,
            fetch=True,
        )
        return {(row[0], bytes(row[1])) for row in results}

    def upsert_to_postgres(
        self,
        entities: List[Entity],
        other_relations: Dict[str, List[Tuple]],
        aliases: Dict[str, List[str]],
        version: Optional[str] = None,
        symbol_maps: Optional[Dict[str, List[Dict]]] = None,
        alias_hops: Optional[Dict[str, List[Dict]]] = None,
    ) -> None:
        """Upsert extraction results into Postgres using ID + version mapping schema."""
        if not version:
            logger.warning("No version provided. Defaulting to 'latest'.")
            version = "latest"

        KNOWN_TYPES = {"MODULE", "CLASS", "FUNCTION", "METHOD", "DISTRIBUTION_PACKAGE", "IMPORT_PACKAGE", "VARIABLE"}

        entity_rows_map: Dict[str, Dict] = {}
        type_map: Dict[str, set] = {}

        for ent in entities:
            if "::" in ent.name or not ent.labels:
                continue
            t_types = {l for l in ent.labels if l in KNOWN_TYPES}
            if t_types:
                type_map[ent.name] = t_types

        for ent in entities:
            name = ent.name
            labels = ent.labels
            non_version_labels = [l for l in labels if not l.startswith("version_")]
            found_types = {l for l in non_version_labels if l in KNOWN_TYPES}
            meta_labels = {l for l in non_version_labels if l not in KNOWN_TYPES}
            if not found_types:
                found_types = {"UNKNOWN"}
            if name not in entity_rows_map:
                entity_rows_map[name] = {"types": set(), "meta_labels": set()}
            entity_rows_map[name]["types"].update(found_types)
            entity_rows_map[name]["meta_labels"].update(meta_labels)

        entity_rows = [
            {"name": name, "types": sorted(list(data["types"])), "meta_labels": sorted(list(data["meta_labels"]))}
            for name, data in entity_rows_map.items()
            if "::" not in name
        ]

        with self._get_connection() as conn:
            with conn.cursor() as cur:
                version_id = self._get_version_id(cur, version)

                entity_id_map = self._upsert_entities(cur, entity_rows)
                self._upsert_entity_versions(cur, [(entity_id, version_id) for entity_id in entity_id_map.values()])

                pkg_dep_rows = []
                for ent in entities:
                    if "DISTRIBUTION_PACKAGE" not in ent.labels:
                        continue
                    ent_id = entity_id_map.get(ent.name)
                    if not ent_id:
                        continue
                    raw_deps = ent.properties.get("dependencies")
                    if not raw_deps:
                        continue
                    if isinstance(raw_deps, str):
                        try:
                            raw_deps = json.loads(raw_deps)
                        except Exception:
                            continue
                    for dep_item in (raw_deps if isinstance(raw_deps, list) else []):
                        if isinstance(dep_item, dict):
                            raw_name = dep_item.get("name")
                            if not raw_name:
                                continue
                            dep_name = raw_name.strip().lower().replace('-', '_').replace('.', '_')
                            dep_spec = dep_item.get("specifier") or None
                            dep_marker = dep_item.get("marker") or None
                            dep_extras = dep_item.get("extras") or None
                        elif isinstance(dep_item, str):
                            dep_name, dep_spec = _parse_dep(dep_item)
                            dep_marker = None
                            dep_extras = None
                        else:
                            continue
                        if dep_name:
                            pkg_dep_rows.append((ent_id, version_id, dep_name, dep_spec, dep_marker, dep_extras))
                seen_deps: dict = {}
                for row in pkg_dep_rows:
                    key = (row[0], row[1], row[2], row[4] or '')
                    if key not in seen_deps:
                        seen_deps[key] = row
                pkg_dep_rows = list(seen_deps.values())
                self._upsert_package_dependencies(cur, pkg_dep_rows)

                raw_module_sources = []
                raw_entity_defs = []
                raw_decorators = []

                fqn_to_content_hash = {
                    ent.name: self._hash_to_bytes(ent.content_hash)
                    for ent in entities
                    if "::" not in ent.name
                }

                stub_module_fqn_by_entity = {
                    ent.name: ent.properties["_stub_module_fqn"]
                    for ent in entities
                    if "::" not in ent.name and "_stub_module_fqn" in ent.properties
                }

                for ent in entities:
                    name = ent.name
                    labels = ent.labels or []
                    props = ent.properties
                    content_hash = self._hash_to_bytes(ent.content_hash)
                    source = props.get("text", props.get("source", props.get("code")))

                    target_name = name.split("::")[0] if "::" in name else name
                    source_types = type_map.get(target_name, set())
                    is_module = "MODULE" in source_types or "IMPORT_PACKAGE" in source_types
                    is_source_entity = self._is_source_entity(name, labels)

                    if "DECORATOR_DETAILS" in labels and "value" in props and target_name in entity_id_map:
                        dec_value = props["value"]
                        if isinstance(dec_value, str):
                            try:
                                dec_value = json.loads(dec_value)
                            except Exception:
                                dec_value = {"raw": dec_value}
                        parent_hash = fqn_to_content_hash.get(target_name)
                        if parent_hash is not None:
                            raw_decorators.append((entity_id_map[target_name], parent_hash, dec_value))

                    start_line = self._to_int_or_none(props.get("lineno") or props.get("line_start"))
                    end_line = self._to_int_or_none(props.get("end_lineno") or props.get("line_end"))

                    # Skip non-SOURCE :: property entities (e.g. ::DECORATOR_DETAILS).
                    # They have their own computed content_hash and no line numbers, which
                    # would create spurious entity_definition_locations rows with NULL lines.
                    if "::" in name and not is_source_entity:
                        continue

                    if is_module and target_name in entity_id_map:
                        if not is_source_entity:
                            continue
                        code_content = props.get("code") or props.get("source_code") or (
                            source if len(str(source or "")) > 255 or "\n" in str(source or "") else None
                        )
                        f_path = props.get("file_path") or (source if not code_content else None)
                        raw_module_sources.append(
                            {
                                "module_entity_id": entity_id_map[target_name],
                                "source_hash": content_hash,
                                "source_code": code_content,
                                "docstring": props.get("docstring"),
                                "file_path": f_path,
                            }
                        )
                    elif target_name in entity_id_map:
                        module_name = None
                        parts = target_name.split(".")
                        for i in range(len(parts), 0, -1):
                            candidate = ".".join(parts[:i])
                            if candidate in type_map and (
                                "MODULE" in type_map[candidate] or "IMPORT_PACKAGE" in type_map[candidate]
                            ):
                                module_name = candidate
                                break
                        if not module_name and len(parts) > 1:
                            module_name = ".".join(parts[:-1])

                        raw_entity_defs.append(
                            {
                                "entity_id": entity_id_map[target_name],
                                "source_hash": content_hash,
                                "module_name": module_name,
                                "start_line": start_line,
                                "end_line": end_line,
                                "docstring_start_line": self._to_int_or_none(props.get("docstring_start_line")),
                                "docstring_end_line": self._to_int_or_none(props.get("docstring_end_line")),
                                "signature_start_line": self._to_int_or_none(props.get("signature_start_line")),
                                "signature_end_line": self._to_int_or_none(props.get("signature_end_line")),
                                "stub_module_name": stub_module_fqn_by_entity.get(target_name),
                            }
                        )

                final_module_sources = {}
                for row in raw_module_sources:
                    key = (row["module_entity_id"], row["source_hash"])
                    if key not in final_module_sources:
                        final_module_sources[key] = row
                    else:
                        existing = final_module_sources[key]
                        if not existing.get("source_code") and row.get("source_code"):
                            existing["source_code"] = row["source_code"]
                        if not existing.get("file_path") and row.get("file_path"):
                            existing["file_path"] = row["file_path"]
                        if not existing.get("docstring") and row.get("docstring"):
                            existing["docstring"] = row["docstring"]

                module_source_rows = list(final_module_sources.values())
                existing_module_source_keys = self._fetch_existing_module_sources(
                    cur, [(r["module_entity_id"], r["source_hash"]) for r in module_source_rows]
                )
                new_module_source_rows = [
                    r for r in module_source_rows
                    if (r["module_entity_id"], bytes(r["source_hash"])) not in existing_module_source_keys
                ]
                logger.info(
                    "Pre-check module_sources: %d/%d new (skipping %d existing)",
                    len(new_module_source_rows), len(module_source_rows),
                    len(module_source_rows) - len(new_module_source_rows),
                )
                self._upsert_module_sources(cur, new_module_source_rows)
                module_source_hash_by_entity = {}
                module_source_rank_by_entity = {}
                for row in module_source_rows:
                    module_entity_id = row["module_entity_id"]
                    source_hash = row["source_hash"]
                    quality_rank = 0
                    if row.get("source_code"):
                        quality_rank += 2
                    if row.get("file_path"):
                        quality_rank += 1
                    if row.get("docstring"):
                        quality_rank += 1
                    if (
                        module_entity_id not in module_source_rank_by_entity
                        or quality_rank > module_source_rank_by_entity[module_entity_id]
                    ):
                        module_source_rank_by_entity[module_entity_id] = quality_rank
                        module_source_hash_by_entity[module_entity_id] = source_hash
                stub_module_source_hash_by_entity = {
                    row["module_entity_id"]: row["source_hash"]
                    for row in module_source_rows
                    if (row.get("file_path") or "").endswith(".pyi")
                }
                self._upsert_module_source_versions(
                    cur,
                    [
                        (row["module_entity_id"], row["source_hash"], version_id)
                        for row in module_source_rows
                    ],
                )

                final_entity_defs = {}
                for row in raw_entity_defs:
                    key = (row["entity_id"], row["source_hash"])
                    if key not in final_entity_defs:
                        final_entity_defs[key] = row
                    else:
                        existing = final_entity_defs[key]
                        if existing.get("start_line") is None and row.get("start_line") is not None:
                            existing["start_line"] = row["start_line"]
                            existing["end_line"] = row["end_line"]
                        if existing.get("docstring_start_line") is None and row.get("docstring_start_line") is not None:
                            existing["docstring_start_line"] = row["docstring_start_line"]
                        if existing.get("docstring_end_line") is None and row.get("docstring_end_line") is not None:
                            existing["docstring_end_line"] = row["docstring_end_line"]
                        if existing.get("signature_start_line") is None and row.get("signature_start_line") is not None:
                            existing["signature_start_line"] = row["signature_start_line"]
                        if existing.get("signature_end_line") is None and row.get("signature_end_line") is not None:
                            existing["signature_end_line"] = row["signature_end_line"]

                entity_def_rows = list(final_entity_defs.values())
                self._upsert_entity_definitions(cur, entity_def_rows)
                self._upsert_entity_definition_versions(
                    cur,
                    [(row["entity_id"], row["source_hash"], version_id) for row in entity_def_rows],
                )

                location_rows = []
                for row in entity_def_rows:
                    stub_module_name = row.get("stub_module_name")
                    module_name = stub_module_name or row.get("module_name")
                    if not module_name:
                        continue
                    module_entity_id = entity_id_map.get(module_name)
                    if not module_entity_id:
                        continue

                    if stub_module_name:
                        module_source_hash = stub_module_source_hash_by_entity.get(module_entity_id) or module_source_hash_by_entity.get(module_entity_id)
                    else:
                        module_source_hash = module_source_hash_by_entity.get(module_entity_id)
                    if module_source_hash is None:
                        continue

                    start_line = self._to_int_or_none(row.get("start_line"))
                    end_line = self._to_int_or_none(row.get("end_line"))
                    docstring_start_line = self._to_int_or_none(row.get("docstring_start_line"))
                    docstring_end_line = self._to_int_or_none(row.get("docstring_end_line"))
                    signature_start_line = self._to_int_or_none(row.get("signature_start_line"))
                    signature_end_line = self._to_int_or_none(row.get("signature_end_line"))

                    location_rows.append(
                        (
                            row["entity_id"],
                            row["source_hash"],
                            module_entity_id,
                            module_source_hash,
                            version_id,
                            start_line,
                            end_line,
                            docstring_start_line,
                            docstring_end_line,
                            signature_start_line,
                            signature_end_line,
                        )
                    )

                self._upsert_entity_definition_locations(cur, location_rows)

                decorator_rows = []
                seen_dec = set()
                for entity_id, source_hash, details in raw_decorators:
                    key = (entity_id, source_hash)
                    if key in seen_dec:
                        continue
                    seen_dec.add(key)
                    decorator_rows.append((entity_id, source_hash, details))

                self._upsert_decorator_details(cur, decorator_rows)
                self._upsert_decorator_detail_versions(
                    cur,
                    [(entity_id, source_hash, version_id) for entity_id, source_hash, _ in decorator_rows],
                )

                relation_rows = []
                hash_to_name = {}
                for e in entities:
                    if "::" in e.name:
                        continue
                    if e.content_hash not in hash_to_name:
                        hash_to_name[e.content_hash] = e.name
                for rel_type, items in other_relations.items():
                    for c_hash, target_ref in items:
                        src_name = hash_to_name.get(c_hash)
                        if not src_name:
                            continue
                        src_id = entity_id_map.get(src_name)
                        if not src_id:
                            continue

                        attrs = dict(target_ref.attributes) if target_ref.attributes else {}
                        if target_ref.alias:
                            attrs["alias"] = target_ref.alias
                        if target_ref.version:
                            attrs["target_version"] = target_ref.version

                        to_id = entity_id_map.get(target_ref.name)
                        if to_id is not None:
                            relation_rows.append(
                                {
                                    "from_entity_id": src_id,
                                    "to_entity_id": to_id,
                                    "to_entity_name": None,
                                    "rel_type": rel_type,
                                    "attributes": attrs,
                                }
                            )
                        else:
                            relation_rows.append(
                                {
                                    "from_entity_id": src_id,
                                    "to_entity_id": None,
                                    "to_entity_name": target_ref.name,
                                    "rel_type": rel_type,
                                    "attributes": attrs,
                                }
                            )

                dedup = {}
                for row in relation_rows:
                    key = (
                        row["from_entity_id"],
                        row["to_entity_id"],
                        row["to_entity_name"],
                        row["rel_type"],
                    )
                    if key not in dedup:
                        dedup[key] = row
                    else:
                        dedup[key]["attributes"].update(row.get("attributes", {}))
                relation_rows = list(dedup.values())

                self._upsert_relations(cur, relation_rows)
                self._upsert_relation_versions(
                    cur,
                    [
                        (
                            r["from_entity_id"],
                            r.get("to_entity_id"),
                            r.get("to_entity_name"),
                            r["rel_type"],
                            version_id,
                        )
                        for r in relation_rows
                    ],
                )

                alias_rows = []
                for entity_name, alias_list in aliases.items():
                    entity_id = entity_id_map.get(entity_name)
                    if not entity_id:
                        continue
                    for alias in alias_list:
                        if alias == entity_name:
                            continue
                        alias_rows.append((entity_id, alias))

                seen_alias = set()
                alias_rows = [a for a in alias_rows if not (a in seen_alias or seen_alias.add(a))]

                self._upsert_aliases(cur, alias_rows)
                self._upsert_alias_versions(cur, [(entity_id, alias, version_id) for entity_id, alias in alias_rows])

                sym_rows: List[Tuple] = []
                sym_ver_rows: List[Tuple] = []
                if symbol_maps:
                    for module_fqn, sym_list in symbol_maps.items():
                        module_entity_id = entity_id_map.get(module_fqn)
                        if not module_entity_id:
                            continue
                        for sym in sym_list:
                            sym_entity_id = entity_id_map.get(sym.get("entity_fqn")) if sym.get("entity_fqn") else None
                            sym_rows.append((
                                module_entity_id,
                                sym.get("name"),
                                sym.get("origin"),
                                sym_entity_id,
                                sym.get("source_fqn"),
                                sym.get("condition"),
                                sym.get("line_no"),
                                sym.get("parent_block_start_line"),
                                bool(sym.get("is_reexport", False)),
                            ))
                            sym_ver_rows.append((
                                module_entity_id,
                                sym.get("name"),
                                sym.get("condition"),
                                version_id,
                            ))
                self._upsert_module_symbols(cur, sym_rows)
                self._upsert_module_symbol_versions(cur, sym_ver_rows)

                hop_rows: List[Tuple] = []
                hop_ver_rows: List[Tuple] = []
                if alias_hops:
                    for key, hops in alias_hops.items():
                        if "::" not in key:
                            continue
                        canonical_fqn, alias_fqn = key.split("::", 1)
                        canonical_entity_id = entity_id_map.get(canonical_fqn)
                        if not canonical_entity_id:
                            continue
                        for hop_order, hop in enumerate(hops):
                            hop_module_fqn = hop.get("module_fqn")
                            hop_module_entity_id = entity_id_map.get(hop_module_fqn) if hop_module_fqn else None
                            hop_source_hash = module_source_hash_by_entity.get(hop_module_entity_id) if hop_module_entity_id else None
                            hop_source_id = None
                            if hop_module_entity_id and hop_source_hash:
                                cur.execute(
                                    "SELECT id FROM module_sources WHERE module_entity_id = %s AND source_hash = %s",
                                    (hop_module_entity_id, hop_source_hash),
                                )
                                row = cur.fetchone()
                                hop_source_id = row[0] if row else None
                            next_hop_fqn = hop.get("next_hop_fqn")
                            target_entity_id = entity_id_map.get(next_hop_fqn) if next_hop_fqn else None
                            target_entity_name = next_hop_fqn if (next_hop_fqn and not target_entity_id) else None
                            hop_rows.append((
                                canonical_entity_id,
                                alias_fqn,
                                hop_order,
                                hop_source_id,
                                hop.get("line_no"),
                                target_entity_id,
                                target_entity_name,
                            ))
                            hop_ver_rows.append((
                                canonical_entity_id,
                                alias_fqn,
                                hop_order,
                                version_id,
                            ))
                self._upsert_alias_hops(cur, hop_rows)
                self._upsert_alias_hop_versions(cur, hop_ver_rows)

                conn.commit()

                logger.info(
                    "Completed Postgres upload: entities=%d, module_sources=%d uploaded/%d total, entity_definitions=%d, "
                    "decorator_details=%d, relations(other_relations)=%d, aliases=%d, module_symbols=%d, alias_hops=%d",
                    len(entity_rows),
                    len(new_module_source_rows),
                    len(module_source_rows),
                    len(entity_def_rows),
                    len(decorator_rows),
                    len(relation_rows),
                    len(alias_rows),
                    len(sym_rows),
                    len(hop_rows),
                )
