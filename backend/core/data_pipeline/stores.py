import logging
import traceback
from dataclasses import dataclass
from typing import Dict, List, Optional
import os

logger = logging.getLogger(__name__)

try:
    from core.com_store.graph.main import COMStore as _GraphStore
except ImportError:
    _GraphStore = None

try:
    from core.com_store.postgres.main import PostgresCOMStore as _PostgresStore
except ImportError:
    _PostgresStore = None

if not _GraphStore and not _PostgresStore:
    logger.warning("Neither GraphStore nor PostgresStore could be imported.")

_stores: Dict = {}


@dataclass
class StoreConfig:
    neo4j_username: str = "neo4j"
    neo4j_password: str = ""
    neo4j_url: str = "bolt://localhost:7687"
    neo4j_database: str = "neo4j"
    embed_nodes: bool = False
    postgres_url: Optional[str] = None
    batch_size: Optional[int] = None

    @classmethod
    def from_env(cls) -> "StoreConfig":
        return cls(
            neo4j_username=os.getenv("NEO4J_USER", "neo4j"),
            neo4j_password=os.getenv("NEO4J_PASSWORD", ""),
            neo4j_url=os.getenv("NEO4J_URI", "bolt://localhost:7687"),
            neo4j_database=os.getenv("NEO4J_DATABASE", "neo4j"),
            embed_nodes=os.getenv("EMBED_NODES", "false").lower() == "true",
            postgres_url=os.getenv("SUPABASE_DB_URL") or os.getenv("POSTGRES_URL"),
        )

    def to_dict(self) -> Dict:
        return {
            "neo4j_username": self.neo4j_username,
            "neo4j_password": self.neo4j_password,
            "neo4j_url": self.neo4j_url,
            "neo4j_database": self.neo4j_database,
            "embed_nodes": self.embed_nodes,
            "postgres_url": self.postgres_url,
            "batch_size": self.batch_size,
        }


def init_stores(config: Dict, targets: List[str] = None) -> Dict:
    global _stores
    targets = targets or ["neo4j"]

    if "neo4j" in targets and _GraphStore:
        if "neo4j" not in _stores:
            logger.info(f"Initializing Neo4j COMStore connection to {config.get('neo4j_url')}")
            init_kwargs = {
                "username": config.get("neo4j_username", "neo4j"),
                "password": config.get("neo4j_password", "password"),
                "url": config.get("neo4j_url", "bolt://localhost:7687"),
                "database": config.get("neo4j_database", "neo4j"),
            }
            if config.get("batch_size"):
                init_kwargs["batch_size"] = config["batch_size"]
            _stores["neo4j"] = _GraphStore(**init_kwargs)

    if "postgres" in targets and _PostgresStore:
        if "postgres" not in _stores:
            logger.info("Initializing Postgres COMStore")
            conn_str = config.get("postgres_url")
            if not conn_str:
                logger.warning("Postgres URL not provided, skipping Postgres initialization")
            else:
                pg_store = _PostgresStore(connection_string=conn_str)
                try:
                    logger.info("Ensuring Postgres schema exists...")
                    pg_store.init_schema()
                except Exception as e:
                    logger.warning(f"Could not initialize Postgres schema: {e}")
                _stores["postgres"] = pg_store

    return _stores


def close_stores() -> None:
    global _stores
    if "neo4j" in _stores:
        logger.info("Closing Neo4j connection")
        try:
            _stores["neo4j"]._driver.close()
        except Exception:
            pass
    _stores = {}


def check_version_exists(
    library: str,
    version: str,
    config: Dict,
    targets: List[str],
) -> bool:
    stores = init_stores(config, targets)
    exists_all = True

    if "neo4j" in stores:
        try:
            version_label = f"version_{version.replace('.', '_').replace(':', '_').replace('-', '_')}"
            check_query = """
            MATCH (root:DISTRIBUTION_PACKAGE {name: $library_name})
            WHERE $version_label IN labels(root)
            RETURN count(root) > 0 AS exists
            """
            result = stores["neo4j"].structured_query(check_query, {
                "library_name": library,
                "version_label": version_label,
            })
            if not (result and result[0]["exists"]):
                exists_all = False
        except Exception as e:
            logger.error(f"Error checking neo4j for {library}=={version}: {e}")
            exists_all = False

    if "postgres" in stores:
        try:
            pg_store = stores["postgres"]
            with pg_store._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT 1
                        FROM entities e
                        JOIN entity_versions ev ON ev.entity_id = e.id
                        JOIN versions v ON v.id = ev.version_id
                        WHERE e.name = %s
                          AND 'DISTRIBUTION_PACKAGE' = ANY(e.types)
                          AND v.version_text = %s
                        LIMIT 1
                        """,
                        (library, version),
                    )
                    if not cur.fetchone():
                        exists_all = False
        except Exception as e:
            logger.error(f"Error checking postgres for {library}=={version}: {e}")
            exists_all = False

    return exists_all and len(stores) > 0


def upload_to_stores(
    entities: List,
    relations: List,
    other_relations: Dict,
    aliases: Dict,
    library: str,
    version: str,
    config: Dict,
    targets: List[str],
    symbol_maps: Optional[Dict] = None,
    alias_hops: Optional[Dict] = None,
) -> bool:
    stores = init_stores(config, targets)
    success = True

    if "neo4j" in stores:
        try:
            logger.info(f"Uploading to Neo4j for {library}=={version}")
            stores["neo4j"].upsert_to_neo4j(
                module_name=library,
                entities=entities,
                relations=relations,
                other_relations=other_relations,
            )
        except Exception as e:
            logger.error(f"Failed to upload to Neo4j: {e}")
            traceback.print_exc()
            success = False

    if "postgres" in stores:
        try:
            logger.info(f"Uploading entities + other_relations + aliases to Postgres for {library}=={version}")
            stores["postgres"].upsert_to_postgres(
                entities=entities,
                other_relations=other_relations,
                aliases=aliases,
                version=version,
                symbol_maps=symbol_maps,
                alias_hops=alias_hops,
            )
        except Exception as e:
            logger.error(f"Failed to upload to Postgres: {e}")
            traceback.print_exc()
            success = False

    return success
