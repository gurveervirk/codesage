import os
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

    def init_schema(self):
        """Initialize database schema from schema.sql."""
        schema_path = os.path.join(os.path.dirname(__file__), 'schema.sql')
        if not os.path.exists(schema_path):
             logger.error(f"Schema file not found at {schema_path}")
             return

        try:
            with open(schema_path, 'r') as f:
                schema_sql = f.read()
                
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(schema_sql)
                conn.commit()
                logger.info("Initialized Postgres schema.")
        except Exception as e:
            logger.error(f"Failed to initialize schema: {e}")
            raise

    def upsert_to_postgres(
        self, 
        entities: List[Entity], 
        other_relations: Dict[str, List[Tuple]],
        aliases: Dict[str, List[str]],
        version: Optional[str] = None
    ) -> None:
        """Upsert extraction results into Postgres."""
        if not version:
            logger.warning("No version provided. Defaulting to 'latest'.")
            version = "latest"

        entity_rows = []
        source_rows = []
        import_rows = []
        decorator_rows = []
        
        for ent in entities:
            name = ent.name
            props = ent.properties
            content_hash = ent.content_hash
            labels = ent.labels
            
            non_version_labels = [l for l in labels if not l.startswith("version_")]
            entity_type = "UNKNOWN"
            meta_labels = []
            
            KNOWN_TYPES = {"MODULE", "CLASS", "FUNCTION", "METHOD", "DISTRIBUTION_PACKAGE", "IMPORT_PACKAGE"}
            for l in non_version_labels:
                if l in KNOWN_TYPES:
                    entity_type = l
                else:
                    meta_labels.append(l)
            
            entity_rows.append({
                "name": name,
                "type": entity_type,
                "meta_labels": meta_labels
            })
            
            source = props.get("text", props.get("source", props.get("code")))
            attributes = {k: v for k, v in props.items() 
                          if k not in ["name", "label", "text", "source", "code", "docstring", "signature", "content_hash", "imports", "decorator_details"]}
            
            if "imports" in props:
                import_rows.append({
                    "entity_name": name,
                    "content_hash": content_hash,
                    "imports": props["imports"]
                })
            
            if "decorator_details" in props:
                decorator_rows.append({
                    "entity_name": name,
                    "details": props["decorator_details"],
                    "content_hash": content_hash
                })

            source_rows.append({
                "entity_name": name,
                "content_hash": content_hash,
                "source_code": source,
                "docstring": props.get("docstring"),
                "signature": props.get("signature"),
                "attributes": attributes
            })

        relation_rows = []

        hash_to_name = {e.content_hash: e.name for e in entities}
        
        for rel_type, items in other_relations.items():
            for c_hash, target_ref in items:
                src_name = hash_to_name.get(c_hash)
                if not src_name:
                    continue
                
                relation_rows.append({
                    "from": src_name,
                    "to": target_ref.name,
                    "type": rel_type,
                    "attributes": {"alias": target_ref.alias, "target_version": target_ref.version}
                })

        alias_rows = []
        for entity_name, alias_list in aliases.items():
            for alias in alias_list:
                alias_rows.append({
                    "entity_name": entity_name,
                    "alias": alias
                })

        with self._get_connection() as conn:
            with conn.cursor() as cur:
                self._batch_upsert_entities(cur, entity_rows, version)
                self._batch_upsert_sources(cur, source_rows, version)
                self._batch_upsert_imports(cur, import_rows, version)
                self._batch_upsert_decorators(cur, decorator_rows, version)
                self._batch_upsert_relations(cur, relation_rows, version)
                self._batch_upsert_aliases(cur, alias_rows, version)
                conn.commit()

    def _batch_upsert_entities(self, cur, rows: List[Dict], version: str):
        if not rows: return
        execute_values(cur, """
            INSERT INTO entities (name, type, meta_labels, versions)
            VALUES %s
            ON CONFLICT (name) DO UPDATE SET
                versions = (SELECT array_agg(DISTINCT v) FROM unnest(entities.versions || EXCLUDED.versions) v),
                meta_labels = (SELECT array_agg(DISTINCT l) FROM unnest(entities.meta_labels || EXCLUDED.meta_labels) l)
        """, [(r["name"], r["type"], r["meta_labels"], [version]) for r in rows])

    def _batch_upsert_sources(self, cur, rows: List[Dict], version: str):
        if not rows: return
        values = []
        for r in rows:
            values.append((
                r["entity_name"],
                r["content_hash"],
                r.get("source_code"),
                r.get("docstring"),
                r.get("signature"),
                Json(r.get("attributes", {})),
                [version]
            ))
            
        execute_values(cur, """
            INSERT INTO sources (entity_name, content_hash, source_code, docstring, signature, attributes, versions)
            VALUES %s
            ON CONFLICT (content_hash) DO UPDATE SET
                versions = (SELECT array_agg(DISTINCT v) FROM unnest(sources.versions || EXCLUDED.versions) v)
        """, values)

    def _batch_upsert_imports(self, cur, rows: List[Dict], version: str):
        if not rows: return
        values = [(r["entity_name"], r["content_hash"], Json(r["imports"]), [version]) for r in rows]
        
        execute_values(cur, """
            INSERT INTO import_details (entity_name, content_hash, imports, versions)
            VALUES %s
            ON CONFLICT (content_hash) DO UPDATE SET
                versions = (SELECT array_agg(DISTINCT v) FROM unnest(import_details.versions || EXCLUDED.versions) v)
        """, values)

    def _batch_upsert_decorators(self, cur, rows: List[Dict], version: str):
        if not rows: return
        values = [(r["entity_name"], r["content_hash"], Json(r["details"]), [version]) for r in rows]
        
        execute_values(cur, """
            INSERT INTO decorator_details (entity_name, content_hash, details, versions)
            VALUES %s
            ON CONFLICT (content_hash) DO UPDATE SET
                versions = (SELECT array_agg(DISTINCT v) FROM unnest(decorator_details.versions || EXCLUDED.versions) v)
        """, values)

    def _batch_upsert_relations(self, cur, rows: List[Dict], version: str):
        if not rows: return
        values = []
        for r in rows:
            values.append((
                r["from"], 
                r["to"], 
                r["type"], 
                Json(r.get("attributes", {})),
                [version]
            ))
            
        execute_values(cur, """
            INSERT INTO relations (from_entity, to_entity, rel_type, attributes, versions)
            VALUES %s
            ON CONFLICT (from_entity, to_entity, rel_type) DO UPDATE SET
                versions = (SELECT array_agg(DISTINCT v) FROM unnest(relations.versions || EXCLUDED.versions) v),
                attributes = relations.attributes || EXCLUDED.attributes
        """, values)

    def _batch_upsert_aliases(self, cur, rows: List[Dict], version: str):
        if not rows: return
        values = [(r["entity_name"], r["alias"], [version]) for r in rows]
        
        execute_values(cur, """
            INSERT INTO aliases (entity_name, alias, versions)
            VALUES %s
            ON CONFLICT (entity_name, alias) DO UPDATE SET
                versions = (SELECT array_agg(DISTINCT v) FROM unnest(aliases.versions || EXCLUDED.versions) v)
        """, values)