"""
This module is an integration of COM logic with the Neo4jPropertyGraphStore class.
"""
from llama_index.graph_stores.neo4j import Neo4jPropertyGraphStore
from llama_index.core.bridge.pydantic import PrivateAttr
from llama_index.core.graph_stores.types import (
    EntityNode
)
from llama_index.core import Settings
from typing import Any, Dict, List, Optional, Tuple
from ..com_extractor import Entity, Relationship
from .utils import check_if_not_null
import logging
import neo4j
import json

logging.basicConfig(level=logging.INFO)
BASE_ENTITY_LABEL = "__Entity__"
BASE_NODE_LABEL = "__Node__"

FULL_TEXT_FULL_NAME_SEARCH_TEMPLATE = """
Best matches for the entity {entity_name}:
{matches}
"""

class COMStore(Neo4jPropertyGraphStore):
    """
    COM stands for Code Object Model.
    This class is a subclass of Neo4jPropertyGraphStore and is used to store and retrieve code entities and their relationships in a Neo4j database.
    It provides ways to create, update, and query entities and relationships in the database. The database stores the Python Modular Tree structure in the form of nodes and relationships.

    Schema:
    - Nodes: MODULE, CLASS, METHOD
    - Relationships: HAS_CLASS, HAS_METHOD, INHERITS, IMPORTS
    """
    stores_text: bool = True
    flat_metadata: bool = True
    distance_strategy: str
    index_name: str
    keyword_index_name: str
    hybrid_search: bool
    node_label: str
    embedding_node_property: str
    text_node_property: str
    retrieval_query: str
    _support_metadata_filter: bool = PrivateAttr()
    _is_enterprise: bool = PrivateAttr()
    custom_fts_indices: Any = []

    _root_modules: List[Dict] = PrivateAttr()
    _children: List[Dict] = PrivateAttr()
    _root_modules_index: int = PrivateAttr()
    _children_index: int = PrivateAttr()
    _last_root_modules_query: Dict = PrivateAttr()
    _last_children_query: Dict = PrivateAttr()

    def __init__(
        self,
        username: str,
        password: str,
        url: str,
        database: Optional[str] = "neo4j",
        index_name: str = "entity",
        keyword_index_name: str = "keyword",
        node_label: str = "__Node__",
        embedding_node_property: str = "embedding",
        text_node_property: str = "source",
        retrieval_query: str = "",
        refresh_schema: bool = True,
        sanitize_query_output: bool = True,
        enhanced_schema: bool = False,
        **neo4j_kwargs: Any,
    ) -> None:
        self.index_name = index_name
        self.keyword_index_name = keyword_index_name
        self.node_label = node_label
        self.embedding_node_property = embedding_node_property
        self.text_node_property = text_node_property
        self.retrieval_query = retrieval_query
        self.database = database
        super().__init__(
            username,
            password,
            url,
            database,
            refresh_schema,
            sanitize_query_output,
            enhanced_schema,
            **neo4j_kwargs,
        )
        check_if_not_null(
            [
                "index_name",
                "node_label",
                "embedding_node_property",
                "text_node_property",
            ],
            [index_name, node_label, embedding_node_property, text_node_property],
        )
        self.create_required_indices()
        self._root_modules = []
        self._children = []
        self._root_modules_index = 0
        self._children_index = 0
        self._last_root_modules_query = {}
        self._last_children_query = {}

    def create_required_indices(self) -> None:
        """
        This method constructs Cypher queries and executes them to create:
        1. 5 full-text indices in Neo4j:
            - one for ROOT_MODULE entities on 'name' and 'source' properties.
            - one for MODULE entities on 'name' and 'source' properties.
            - one for FUNCTION entities on 'name' and 'source' properties.
            - one for CLASS entities on 'name' and 'source' properties.
            - one for METHOD entities on 'name' and 'source' properties.
        2. 5 vector indices:
            - one for ROOT_MODULE entities on the 'embedding' property.
            - one for FUNCTION entities on the 'embedding' property.
            - one for MODULE entities on the 'embedding' property.
            - one for CLASS entities on the 'embedding' property.
            - one for METHOD entities on the 'embedding' property.

        It uses the IF NOT EXISTS clause to avoid errors if the indices already exist.
        """

        # Create full-text indices
        root_module_index_query = """
        CREATE FULLTEXT INDEX root_module_index IF NOT EXISTS FOR (n:`ROOT_MODULE`) ON EACH [n.`name`]
        """
        self.database_query(root_module_index_query)

        function_index_query = """
        CREATE FULLTEXT INDEX function_index IF NOT EXISTS FOR (n:`FUNCTION`) ON EACH [n.`name`]
        """
        self.database_query(function_index_query)

        module_index_query = """
        CREATE FULLTEXT INDEX module_index IF NOT EXISTS FOR (n:`MODULE`) ON EACH [n.`name`]
        """
        self.database_query(module_index_query)

        class_index_query = """
        CREATE FULLTEXT INDEX class_index IF NOT EXISTS FOR (n:`CLASS`) ON EACH [n.`name`]
        """
        self.database_query(class_index_query)

        method_index_query = """
        CREATE FULLTEXT INDEX method_index IF NOT EXISTS FOR (n:`METHOD`) ON EACH [n.`name`]
        """
        self.database_query(method_index_query)

        # Create vector indices
        root_module_vector_index_query = """
        CREATE VECTOR INDEX root_module_vector_index IF NOT EXISTS
        FOR (m:`ROOT_MODULE`)
        ON (m.`embedding`)
        OPTIONS {indexConfig: {
            `vector.dimensions`: 1024,
            `vector.similarity_function`: 'cosine'
        }}
        """
        self.database_query(root_module_vector_index_query)

        function_vector_index_query = """
        CREATE VECTOR INDEX function_vector_index IF NOT EXISTS
        FOR (f:`FUNCTION`)
        ON (f.`embedding`)
        OPTIONS {indexConfig: {
            `vector.dimensions`: 1024,
            `vector.similarity_function`: 'cosine'
        }}
        """
        self.database_query(function_vector_index_query)

        module_vector_index_query = """
        CREATE VECTOR INDEX module_vector_index IF NOT EXISTS
        FOR (m:`MODULE`)
        ON (m.`embedding`)
        OPTIONS {indexConfig: {
            `vector.dimensions`: 1024,
            `vector.similarity_function`: 'cosine'
        }}
        """
        self.database_query(module_vector_index_query)

        class_vector_index_query = """
        CREATE VECTOR INDEX class_vector_index IF NOT EXISTS
        FOR (c:`CLASS`)
        ON (c.`embedding`)
        OPTIONS {indexConfig: {
            `vector.dimensions`: 1024,
            `vector.similarity_function`: 'cosine'
        }}
        """
        self.database_query(class_vector_index_query)

        method_vector_index_query = """
        CREATE VECTOR INDEX method_vector_index IF NOT EXISTS
        FOR (m:`METHOD`)
        ON (m.`embedding`)
        OPTIONS {indexConfig: {
            `vector.dimensions`: 1024,
            `vector.similarity_function`: 'cosine'
        }}
        """
        self.database_query(method_vector_index_query)

        general_fts_query = """
        CREATE FULLTEXT INDEX general_fts_index IF NOT EXISTS FOR (n:__Entity__) ON EACH [n.name]
        """
        self.database_query(general_fts_query)

    def query_vector_index(
        self, index_name: str, query: str | List[float], top_k: int = 10,
        **kwargs: Any
    ) -> List[Dict]:
        """
        Query a vector index.

        Args:
            index_name (str): The name of the vector index, restricted to `method_vector_index`, `class_vector_index` and `module_vector_index`.
            query (str or List[float]): The query or query vector embedding.
            top_k (int): The number of results to return. Defaults to 10.

        Returns:
            List[Dict]: A list of dictionaries containing the query results.
        """
        query_vector = None

        if isinstance(query, str):
            query_vector = Settings.embed_model.get_query_embedding(query)
        else:
            query_vector = query

        return_fields = ["name", "summary", "source"]
        return_fields_str = ", ".join([f"n.{field} AS {field}" for field in return_fields])

        query_str = f"""
        CALL db.index.vector.queryNodes($index_name, $top_k, $query_vector)
        YIELD node AS n, score
        RETURN {return_fields_str}, score, labels(n) as labels
        """
        query_params = {
            "index_name": index_name,
            "top_k": top_k,
            "query_vector": query_vector,
        }

        try:
            records = self.database_query(query_str, query_params)
            return records
        except Exception as e:
            logging.error(f"Error querying vector index '{index_name}': {e}")
            return []

    def query_fulltext_index(
        self, index_name: str, query: str,
        **kwargs: Any
    ) -> List[Dict]:
        """
        Query a full-text index.

        Args:
            index_name (str): The name of the full-text index, restricted to `module_index`, `class_index` and `method_index`.
            query (str): The query string.
        Returns:
            List[Dict]: A list of dictionaries containing the query results.
        """
        return_fields = ["name", "source"]
        return_fields_str = ", ".join([f"n.{field} AS {field}" for field in return_fields])

        query_str = f"""
        CALL db.index.fulltext.queryNodes($index_name, $query)
        YIELD node AS n, score
        RETURN {return_fields_str}, score
        """
        query_params = {
            "index_name": index_name,
            "query": query,
        }

        try:
            records = self.database_query(query_str, query_params)
            return records
        except Exception as e:
            logging.error(f"Error querying full-text index '{index_name}': {e}")
            return []

    def similarity_search_without_index(
        self,
        labels: List[str],
        query: str | List[float],
        top_k: int = 10,
        **kwargs: Any,
    ) -> List[Dict]:
        """
        Perform a similarity search without using an index.

        Args:
            labels (List[str]): A list of labels to query (e.g., ["MODULE", "CLASS", "METHOD"]).
            query (str or List[float]): The query or query vector embedding.
            top_k (int): The number of results to return. Defaults to 10.

        Returns:
            List[Dict]: A list of dictionaries containing the query results.
        """
        query_vector = None
        if isinstance(query, str):
            query_vector = Settings.embed_model.get_query_embedding(query)
        else:
            query_vector = query
        return_fields = ["name", "source"]
        return_fields_str = ", ".join([f"n.{field} AS {field}" for field in return_fields])

        query_str = f"""
        MATCH (n)
        WHERE any(label in labels(n) WHERE label IN $labels)
        AND n.{self.embedding_node_property} IS NOT NULL
        WITH n,
        vector.similarity.cosine(n.{self.embedding_node_property}, $query_vector) AS similarity
        ORDER BY similarity DESC
        LIMIT $top_k
        RETURN {return_fields_str}, labels(n) AS all_labels, similarity AS score
        """

        query_params = {
            "labels": labels,
            "query_vector": query_vector,
            "top_k": top_k,
        }

        try:
            records = self.database_query(query_str, query_params)
            return records
        except Exception as e:
            logging.error(f"Error performing similarity search: {e}")
            return []

    def database_query(
        self,
        query: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> Any:
        """
        Execute a cypher query in the Neo4j database.

        Args:
            query (str): The query string.
            params (Optional[Dict[str, Any]]): A dictionary of parameters to pass to the query.
        """
        params = params or {}
        try:
            data, _, _ = self._driver.execute_query(
                query, database_=self.database, parameters_=params
            )
            return [r.data() for r in data]
        except neo4j.exceptions.Neo4jError as e:
            if not (
                (
                    (  # isCallInTransactionError
                        e.code == "Neo.DatabaseError.Statement.ExecutionFailed"
                        or e.code
                        == "Neo.DatabaseError.Transaction.TransactionStartFailed"
                    )
                    and "in an implicit transaction" in e.message
                )
                or (  # isPeriodicCommitError
                    e.code == "Neo.ClientError.Statement.SemanticError"
                    and (
                        "in an open transaction is not possible" in e.message
                        or "tried to execute in an explicit transaction" in e.message
                    )
                )
            ):
                raise
        # Fallback to allow implicit transactions
        with self._driver.session(database=self.database) as session:
            data = session.run(neo4j.Query(text=query), params)
            return [r.data() for r in data]
    
    def upsert_nodes(self, nodes: List[Entity]) -> None:
        """
        Override parent's upsert_nodes to work directly with Entity models.
        This method uses name and content_hash for MERGE operations.
        Entity already has content_hash computed and labels sanitized.
        
        Args:
            nodes: List of Entity objects to upsert
        """
        CHUNK_SIZE = 1000
        
        def _serialize_nested_collections(properties: Dict[str, Any]) -> Dict[str, Any]:
            serialized_props = {}
            for key, value in properties.items():
                if value is None:
                    continue
                elif isinstance(value, (list, tuple)):
                    if not value:
                        serialized_props[key] = None
                    elif any(isinstance(item, (list, tuple, dict)) for item in value):
                        serialized_props[key] = json.dumps(value)
                    else:
                        serialized_props[key] = value
                else:
                    serialized_props[key] = value
            return {k: v for k, v in serialized_props.items() if v is not None}
        
        entity_dicts: List[dict] = []
        
        for entity in nodes:
            # Use content_hash from Entity (already computed in com_extractor)
            c_hash = entity.content_hash
            
            # Prepare properties with content_hash
            properties = dict(entity.properties or {})
            properties["content_hash"] = c_hash
            properties = _serialize_nested_collections(properties)
            
            # Labels are already sanitized in Entity model
            sanitized_labels = entity.labels
            
            entity_dicts.append({
                "name": entity.name,
                "labels": sanitized_labels,  # All labels from entity.labels (already sanitized)
                "properties": properties
            })
        
        if entity_dicts:
            for index in range(0, len(entity_dicts), CHUNK_SIZE):
                chunked_params = entity_dicts[index : index + CHUNK_SIZE]
                self.structured_query(
                    """
                    UNWIND $data AS row
                    // Use name and content_hash for MERGE to support versioning
                    MERGE (e {name: row.name, content_hash: row.properties.content_hash})
                    // Set all properties
                    SET e += apoc.map.clean(row.properties, [], [])
                    SET e.name = row.name
                    WITH e, row
                    // Add all labels from the entity
                    CALL apoc.create.addLabels(e, row.labels)
                    YIELD node
                    RETURN count(node)
                    """,
                    param_map={"data": chunked_params},
                )
    
    def upsert_relations(self, relations: List[Relationship]) -> None:
        """
        Override parent's upsert_relations to work directly with Relationship models.
        Matches nodes by name, version label, and content_hash.
        
        Args:
            relations: List of Relationship objects to upsert
        """
        CHUNK_SIZE = 1000
        
        def _serialize_nested_collections(properties: Dict[str, Any]) -> Dict[str, Any]:
            serialized_props = {}
            for key, value in properties.items():
                if value is None:
                    continue
                elif isinstance(value, (list, tuple)):
                    if not value:
                        serialized_props[key] = None
                    elif any(isinstance(item, (list, tuple, dict)) for item in value):
                        serialized_props[key] = json.dumps(value)
                    else:
                        serialized_props[key] = value
                else:
                    serialized_props[key] = value
            return {k: v for k, v in serialized_props.items() if v is not None}
        
        def _extract_version_label(labels: List[str]) -> Optional[str]:
            """Extract and sanitize version label from entity labels"""
            for label in labels or []:
                if isinstance(label, str) and label.startswith("version:"):
                    # Sanitize for Neo4j
                    return label.replace(":", "_").replace(".", "_").replace("-", "_")
            return None
        
        params = []
        relation_type_counts = {}
        
        for r in relations:
            # Get source and target entity names directly
            source_name = r.from_entity.name
            target_name = r.to_entity.name
            
            # Use content_hash from Entity (already computed in com_extractor)
            source_content_hash = r.from_entity.content_hash
            target_content_hash = r.to_entity.content_hash
            
            # Extract version labels from entities
            source_version_label = _extract_version_label(r.from_entity.labels)
            target_version_label = _extract_version_label(r.to_entity.labels)
            
            # Serialize properties
            properties = _serialize_nested_collections(r.properties or {})
            
            # Track relationship types for debugging
            relation_type_counts[r.label] = relation_type_counts.get(r.label, 0) + 1
            
            params.append({
                "source_name": source_name,
                "source_content_hash": source_content_hash,
                "source_version_label": source_version_label,
                "target_name": target_name,
                "target_content_hash": target_content_hash,
                "target_version_label": target_version_label,
                "label": r.label,
                "properties": properties
            })
        
        logging.info(f"Upserting {len(params)} relationships: {relation_type_counts}")
        
        for index in range(0, len(params), CHUNK_SIZE):
            chunked_params = params[index : index + CHUNK_SIZE]
            
            try:
                result = self.structured_query(
                    """
                    UNWIND $data AS row
                    
                    // Match source by name, content_hash, and version label
                    // content_hash ensures we match the EXACT entity (critical for overloads)
                    CALL {
                        WITH row
                        MATCH (source {name: row.source_name, content_hash: row.source_content_hash})
                        WHERE row.source_version_label IS NULL OR row.source_version_label IN labels(source)
                        RETURN source
                        LIMIT 1
                    }
                    
                    // Match target by name, content_hash, and version label
                    CALL {
                        WITH row
                        MATCH (target {name: row.target_name, content_hash: row.target_content_hash})
                        WHERE row.target_version_label IS NULL OR row.target_version_label IN labels(target)
                        RETURN target
                        LIMIT 1
                    }
                    
                    // Only proceed if both nodes were found
                    WITH source, target, row
                    WHERE source IS NOT NULL AND target IS NOT NULL
                    
                    // Create or update the relationship
                    CALL apoc.merge.relationship(source, row.label, {}, row.properties, target) 
                    YIELD rel
                    RETURN row.label AS rel_type, count(rel) AS created_count
                    """,
                    param_map={"data": chunked_params},
                )
                
                # Log results for debugging
                if result:
                    for r in result:
                        logging.info(f"Created {r.get('created_count', 0)} {r.get('rel_type', 'unknown')} relationships")
                        
            except Exception as e:
                logging.error(f"Error upserting relationship chunk {index}-{index+CHUNK_SIZE}: {e}")
                # Try to identify which relationships failed
                for param in chunked_params[:5]:  # Log first 5 for debugging
                    logging.error(f"Failed relationship example: {param['label']} from {param['source_name']} to {param['target_name']}")
                raise

    def upsert_to_neo4j(
            self, 
            module_name: str, 
            entities: List[Entity], 
            relations: List[Relationship], 
            other_relations: Dict[str, List[Tuple]],
            embed_nodes: Optional[bool] = False
        ) -> None:
        """
        Upsert entities and relationships into Neo4j.

        Args:
            module_name (str): The name of the module.
            entities (List[Entity]): List of entity nodes to upsert.
            relations (List[Relationship]): List of relationships to upsert.
            other_relations (Dict[str, List[Tuple]]): Dictionary containing other relations.
        """
        # Upsert nodes and relationships directly using our custom Entity/Relationship models
        try:
            logging.info(f"Upserting {len(entities)} nodes and {len(relations)} relationships")
            self.upsert_nodes(entities)
            self.upsert_relations(relations)
        except Exception as e:
            logging.error(f"Error during upsert to Neo4j: {e}")
            raise e

        # Embed the nodes if specified
        if embed_nodes:
            self._embed_nodes()

        # Add INHERITS and IMPORTS relations as properties to the respective nodes
        self._add_other_relations_as_properties(other_relations)

        # Process INHERITS and IMPORTS relations
        self._process_other_relations()

        # Handle inherited methods
        self._handle_inherited_methods()

        # Set the shortest call paths for all nodes in the module
        self._set_shortest_call_paths(module_name)

    def _add_other_relations_as_properties(self, other_relations: Dict[str, List[Tuple]]):
        """
        Add INHERITS, IMPORTS, EXPOSES, and PUBLISHES relations as properties to the respective nodes.
        Now works with (content_hash, ExternalEntityRef) tuples.

        Args:
            other_relations (Dict[str, List[Tuple]]): Dictionary containing INHERITS, IMPORTS, EXPOSES, and PUBLISHES relations.
                Each tuple is (from_content_hash, ExternalEntityRef)
        """
        from ..com_extractor import ExternalEntityRef
        
        inherits_relations = other_relations.get("INHERITS", [])
        imports_relations = other_relations.get("IMPORTS", [])
        exposes_relations = other_relations.get("EXPOSES", [])
        publishes_relations = other_relations.get("PUBLISHES", [])
        
        # Convert (name, ExternalEntityRef) tuples to (name, target_info_dict) for INHERITS
        # INHERITS uses entity name (not content_hash) as key since it's class-level
        inherits_processed = []
        for from_name, to_ref in inherits_relations:
            if isinstance(to_ref, ExternalEntityRef):
                # Store as dict with name, version, and content_hash
                target_info = {
                    "name": to_ref.name,
                    "version": to_ref.version,
                    "content_hash": to_ref.content_hash
                }
                inherits_processed.append((from_name, json.dumps(target_info)))
            else:
                # Legacy format: just name
                inherits_processed.append((from_name, to_ref))
        
        # Convert (content_hash, ExternalEntityRef) tuples to (content_hash, target_info_dict) for IMPORTS/EXPOSES
        imports_processed = []
        for from_hash, to_ref in imports_relations:
            if isinstance(to_ref, ExternalEntityRef):
                target_info = {
                    "name": to_ref.name,
                    "version": to_ref.version,
                    "content_hash": to_ref.content_hash
                }
                imports_processed.append((from_hash, json.dumps(target_info)))
            else:
                imports_processed.append((from_hash, to_ref))
        
        exposes_processed = []
        for from_hash, to_ref in exposes_relations:
            if isinstance(to_ref, ExternalEntityRef):
                target_info = {
                    "name": to_ref.name,
                    "version": to_ref.version,
                    "content_hash": to_ref.content_hash
                }
                exposes_processed.append((from_hash, json.dumps(target_info)))
            else:
                exposes_processed.append((from_hash, to_ref))
        
        publishes_processed = []
        for from_hash, to_ref in publishes_relations:
            if isinstance(to_ref, ExternalEntityRef):
                target_info = {
                    "name": to_ref.name,
                    "version": to_ref.version,
                    "content_hash": to_ref.content_hash
                }
                publishes_processed.append((from_hash, json.dumps(target_info)))
            else:
                publishes_processed.append((from_hash, to_ref))
        
        add_inherits_query = (
            """
            UNWIND $inherits_relations AS rel
            MATCH (c:CLASS {name: rel[0]})
            SET c.INHERITS = apoc.coll.toSet(coalesce(c.INHERITS, []) + [rel[1]])
            """
        )
        add_imports_query = (
            """
            UNWIND $imports_relations AS rel
            MATCH (e {content_hash: rel[0]})
            SET e.IMPORTS = apoc.coll.toSet(coalesce(e.IMPORTS, []) + [rel[1]])
            """
        )
        add_exposes_query = (
            """
            UNWIND $exposes_relations AS rel
            MATCH (m {content_hash: rel[0]})
            SET m.EXPOSES = apoc.coll.toSet(coalesce(m.EXPOSES, []) + [rel[1]])
            """
        )
        add_publishes_query = (
            """
            UNWIND $publishes_relations AS rel
            MATCH (m {content_hash: rel[0]})
            SET m.PUBLISHES = apoc.coll.toSet(coalesce(m.PUBLISHES, []) + [rel[1]])
            """
        )
        self.structured_query(add_inherits_query, {"inherits_relations": inherits_processed})
        self.structured_query(add_imports_query, {"imports_relations": imports_processed})
        self.structured_query(add_exposes_query, {"exposes_relations": exposes_processed})
        self.structured_query(add_publishes_query, {"publishes_relations": publishes_processed})

    def _process_other_relations(self):
        """
        Execute Cypher queries to create relations on existing nodes with INHERITS, IMPORTS and EXPOSES properties.
        Now handles version-aware matching using JSON-encoded target information.
        Clear info from the INHERITS, IMPORTS and EXPOSES property arrays of the nodes if the relations could be created successfully.
        """
        # Process INHERITS with version-aware matching
        process_inherits_query = (
            """
            MATCH (c:CLASS)
            WHERE c.INHERITS IS NOT NULL
            UNWIND c.INHERITS AS parentInfo
            WITH c, parentInfo,
                 CASE WHEN parentInfo STARTS WITH '{' 
                      THEN apoc.convert.fromJsonMap(parentInfo)
                      ELSE {name: parentInfo, version: null, content_hash: null}
                 END AS parentData
            // Try to match parent by name and version label if available
            OPTIONAL MATCH (p:CLASS {name: parentData.name})
            WHERE parentData.version IS NULL 
               OR ('version_' + replace(replace(replace(parentData.version, '.', '_'), ':', '_'), '-', '_')) IN labels(p)
            WITH c, parentInfo, p, parentData
            WHERE p IS NOT NULL
            MERGE (c)-[:INHERITS]->(p)
            WITH c, COLLECT(parentInfo) AS processedParents
            SET c.INHERITS = [info IN c.INHERITS WHERE NOT info IN processedParents]
            SET c.NEW_INHERIT_RELS = processedParents
            """
        )
        
        # Process IMPORTS with version-aware and content_hash matching
        process_imports_query = (
            """
            MATCH (e1)
            WHERE e1.IMPORTS IS NOT NULL
            UNWIND e1.IMPORTS AS importInfo
            WITH e1, importInfo,
                 CASE WHEN importInfo STARTS WITH '{'
                      THEN apoc.convert.fromJsonMap(importInfo)
                      ELSE {name: importInfo, version: null, content_hash: null}
                 END AS importData
            // Try to match by content_hash first (if available), then by name+version
            OPTIONAL MATCH (e2)
            WHERE (importData.content_hash IS NOT NULL AND e2.content_hash = importData.content_hash)
               OR (e2.name = importData.name AND (importData.version IS NULL 
                   OR ('version_' + replace(replace(replace(importData.version, '.', '_'), ':', '_'), '-', '_')) IN labels(e2)))
            WITH e1, importInfo, e2
            WHERE e2 IS NOT NULL
            MERGE (e1)-[:IMPORTS]->(e2)
            WITH e1, COLLECT(importInfo) AS processedImports
            SET e1.IMPORTS = [info IN e1.IMPORTS WHERE NOT info IN processedImports]
            """
        )
        
        # Process EXPOSES with version-aware and content_hash matching
        process_exposes_query = (
            """
            MATCH (m:MODULE|ROOT_MODULE)
            WHERE m.EXPOSES IS NOT NULL
            UNWIND m.EXPOSES AS exposedInfo
            WITH m, exposedInfo,
                 CASE WHEN exposedInfo STARTS WITH '{'
                      THEN apoc.convert.fromJsonMap(exposedInfo)
                      ELSE {name: exposedInfo, version: null, content_hash: null}
                 END AS exposedData
            // Try to match by content_hash first (if available), then by name+version
            OPTIONAL MATCH (e)
            WHERE (exposedData.content_hash IS NOT NULL AND e.content_hash = exposedData.content_hash)
               OR (e.name = exposedData.name AND (exposedData.version IS NULL
                   OR ('version_' + replace(replace(replace(exposedData.version, '.', '_'), ':', '_'), '-', '_')) IN labels(e)))
            WITH m, exposedInfo, e
            WHERE e IS NOT NULL
            MERGE (m)-[:EXPOSES]->(e)
            WITH m, COLLECT(exposedInfo) AS processedExposes
            SET m.EXPOSES = [info IN m.EXPOSES WHERE NOT info IN processedExposes]
            """
        )
        
        # Process PUBLISHES with version-aware and content_hash matching
        process_publishes_query = (
            """
            MATCH (m:MODULE|ROOT_MODULE)
            WHERE m.PUBLISHES IS NOT NULL
            UNWIND m.PUBLISHES AS publishedInfo
            WITH m, publishedInfo,
                 CASE WHEN publishedInfo STARTS WITH '{'
                      THEN apoc.convert.fromJsonMap(publishedInfo)
                      ELSE {name: publishedInfo, version: null, content_hash: null}
                 END AS publishedData
            // Try to match by content_hash first (if available), then by name+version
            OPTIONAL MATCH (e)
            WHERE (publishedData.content_hash IS NOT NULL AND e.content_hash = publishedData.content_hash)
               OR (e.name = publishedData.name AND (publishedData.version IS NULL
                   OR ('version_' + replace(replace(replace(publishedData.version, '.', '_'), ':', '_'), '-', '_')) IN labels(e)))
            WITH m, publishedInfo, e
            WHERE e IS NOT NULL
            MERGE (m)-[:PUBLISHES]->(e)
            WITH m, COLLECT(publishedInfo) AS processedPublishes
            SET m.PUBLISHES = [info IN m.PUBLISHES WHERE NOT info IN processedPublishes]
            """
        )
        
        cleanup_empty_INHERITS_query = (
            """
            MATCH (n)
            WHERE n.INHERITS IS NOT NULL AND size(n.INHERITS) = 0
            REMOVE n.INHERITS
            """
        )
        cleanup_empty_IMPORTS_query = (
            """
            MATCH (n)
            WHERE n.IMPORTS IS NOT NULL AND size(n.IMPORTS) = 0
            REMOVE n.IMPORTS
            """
        )
        cleanup_empty_EXPOSES_query = (
            """
            MATCH (n)
            WHERE n.EXPOSES IS NOT NULL AND size(n.EXPOSES) = 0
            REMOVE n.EXPOSES
            """
        )
        cleanup_empty_PUBLISHES_query = (
            """
            MATCH (n)
            WHERE n.PUBLISHES IS NOT NULL AND size(n.PUBLISHES) = 0
            REMOVE n.PUBLISHES
            """
        )
        add_names_to_EXPOSES_rels_query = (
            """
            MATCH (n)-[r:EXPOSES]->(m)
            WHERE r.name IS NULL
            SET r.name = n.name + "." + m.__name__
            RETURN count(r)
            """
        )
        add_names_to_PUBLISHES_rels_query = (
            """
            MATCH (n)-[r:PUBLISHES]->(m)
            WHERE r.name IS NULL
            SET r.name = n.name + "." + m.__name__
            RETURN count(r)
            """
        )

        self.structured_query(process_inherits_query)
        self.structured_query(process_imports_query)
        self.structured_query(process_exposes_query)
        self.structured_query(process_publishes_query)
        self.structured_query(cleanup_empty_INHERITS_query)
        self.structured_query(cleanup_empty_IMPORTS_query)
        self.structured_query(cleanup_empty_EXPOSES_query)
        self.structured_query(cleanup_empty_PUBLISHES_query)
        self.structured_query(add_names_to_EXPOSES_rels_query)
        self.structured_query(add_names_to_PUBLISHES_rels_query)

    def _set_shortest_call_paths(self, module_name: str):
        """
        Set the shortest call paths for all nodes in the module.

        Args:
            module_name (str): The name of the module.
        """
        # Set the shortest call paths for all nodes in the module tree (recursively)
        set_shortest_call_paths_query = (
            """
// Phase 1: Find all nodes reachable from the root module via structural relationships.
MATCH (end:MODULE|FUNCTION|CLASS|METHOD)<-[:HAS_SUBMODULE|HAS_CLASS|HAS_METHOD|HAS_FUNCTION|EXPOSES|PUBLISHES*]-(root:ROOT_MODULE {name: $module_name})
WITH root, collect(end) AS endNodes

// Phase 2: Use spanningTree to get ordered paths from the root outwards (BFS).
CALL apoc.path.spanningTree(root, {
    relationshipFilter: 'HAS_SUBMODULE>|HAS_CLASS>|HAS_METHOD>|HAS_FUNCTION>|EXPOSES>|PUBLISHES>',
    endNodes: endNodes
})
YIELD path

// Phase 3: Deconstruct the path to get the target and its immediate parent.
WITH nodes(path) AS nodesInPath
// Ensure the path has at least a parent and a child.
WHERE size(nodesInPath) > 1
WITH
    LAST(nodesInPath) AS targetNode,
    nodesInPath[-2] AS parentNode

// Phase 4: Only process nodes that do not have a path set yet.
WHERE targetNode.shortest_call_path IS NULL

// Phase 5: Set the shortest_call_path based on the parent's state.
// This is the core logic implementing your request.
SET targetNode.shortest_call_path =
    // COALESCE returns the first non-null value. This elegantly handles the two cases.
    // Case 1: If the parent has a path, use it.
    // Case 2: If the parent's path is null (i.e., it's the root), use its name property.
    COALESCE(parentNode.shortest_call_path, parentNode.name) + '.' + targetNode.__name__

// Phase 6: Return the count of nodes that were updated.
RETURN count(targetNode) AS numPathsSet
"""
        )
        numPathsSet = self.structured_query(set_shortest_call_paths_query, {"module_name": module_name})[0]["numPathsSet"]
        while numPathsSet > 0:
            numPathsSet = self.structured_query(set_shortest_call_paths_query, {"module_name": module_name})[0]["numPathsSet"]

    def _handle_inherited_methods(self):
        """
        Create HAS_METHOD relations for inherited methods for all classes in the specified module.
        """
        handle_inheritance_query = (
            """
// Phase 1: Find classes marked for an inheritance update.
MATCH (child:CLASS)
WHERE child.NEW_INHERIT_RELS IS NOT NULL
WITH child, child.NEW_INHERIT_RELS AS parentNames

// Clean up the trigger property to prevent re-processing.
REMOVE child.NEW_INHERIT_RELS

// Phase 2: Iterate through all methods from all parents.
// It is CRITICAL that `parentNames` is sorted in the correct Method Resolution Order (MRO).
WITH child, parentNames
UNWIND parentNames AS parentName
MATCH (parent:CLASS {name: parentName})-[:HAS_METHOD]->(member)

// Phase 3: Filter the methods based on the correct inheritance and override rules.
WHERE
    // Rule 1: NEVER inherit private methods.
    // This is the simplest and first check.
    NOT 'PRIVATE' IN labels(member)

    // AND the method must not be overridden according to its type (Dunder vs. Public).
    AND (
        // Rule 2: DUNDER methods are overridden by NAME ONLY.
        // Inherit if it's a Dunder AND the child has no method with the same name.
        (
            'DUNDER' IN labels(member) AND
            NOT EXISTS { MATCH (child)-[:HAS_METHOD]->({__name__: member.__name__}) }
        )
        OR
        // Rule 3: PUBLIC/PROTECTED methods are overridden by NAME AND SIGNATURE.
        // Inherit if it's NOT a Dunder AND the child has no method with the same name and signature.
        (
            NOT 'DUNDER' IN labels(member) AND
            NOT EXISTS { MATCH (child)-[:HAS_METHOD]->({__name__: member.__name__, signature: member.signature}) }
        )
    )

// Phase 4: Collect the valid inheritable methods and create the links.
// The DISTINCT is important to handle cases where multiple parents might offer the same valid method.
// Due to MRO, we will later refine this to only take the first one found.
WITH child, collect(DISTINCT member) AS members
UNWIND members AS member
MERGE (child)-[:HAS_METHOD]->(member)

// Phase 5: Report the results.
WITH DISTINCT child, collect(member) AS members
RETURN child.name AS ChildClass, size(members) AS TotalParentMembersLabeled
            """
        )
        self.structured_query(handle_inheritance_query)

    def _remove_empty_values(self, input_dict):
        """
        Remove entries with empty values from the dictionary.

        Parameters:
        input_dict (dict): The dictionary from which empty values need to be removed.

        Returns:
        dict: A new dictionary with all empty values removed.
        """
        # Create a new dictionary excluding empty values
        return {key: value for key, value in input_dict.items() if value}

    def _embed_nodes(self):
        """
        Embed newly created nodes.
        """
        retrieve_new_nodes = (
            """
            MATCH (e)
            WHERE NOT e:INTERNAL
            AND NOT e:PRIVATE
            AND NOT e:DUNDER
            AND e.embedding IS NULL
            RETURN
            e.id AS name,
            labels(e)[0] AS type,
            properties(e) AS properties
            """
        )
        new_nodes = self.structured_query(retrieve_new_nodes)
        if not new_nodes:
            return
        
        logging.info(f"Found {len(new_nodes)} new nodes to embed.")

        entity_nodes, summaries = [], []
        # Create EntityNode objects for each node
        for node in new_nodes:
            entity_node = EntityNode(
                label=node["type"],
                name=node["name"],
                properties=self._remove_empty_values(node["properties"])
            )
            entity_nodes.append(entity_node)
            summary = entity_node.properties.get("summary", "")
    
            if node["type"] in ("ROOT_MODULE", "MODULE", "CLASS"):
                docstring = self._get_docstring(entity_node.properties.get("source", ""))
                if docstring is not None and len(docstring) > 0:
                    summary += f"\n\nDocstring:\n{docstring}"
        
            summaries.append(summary)

        # Embed the nodes
        embeddings = Settings.embed_model.get_text_embedding_batch(
            summaries,
            show_progress=True
        )

        for i, node in enumerate(entity_nodes):
            node.properties[self.embedding_node_property] = embeddings[i]

        self.upsert_nodes(entity_nodes)
    
    def _fts_full_path_name(self, name: str) -> str:
        """
        Perform a full-text search for the full path name of the entity.

        Args:
            name (str): The name of the entity.

        Returns:
            str: The full path name of the entity if found, otherwise an empty string.
        """
        processed_name = name.replace(".", r".*\.")
        name_till_dotunderscore = processed_name
        if r".*\._" in name_till_dotunderscore:
            name_till_dotunderscore = name_till_dotunderscore.split(r".*\._")[0] + r".*"

        name_till_dotunderscore = f'/{name_till_dotunderscore}/'
        logging.info(f"Processed name for regex search: {processed_name}")
        logging.info(f"Processed name for regex search till ._: {name_till_dotunderscore}")

        # Prepare a Cypher query to search for the name in the database, using FTS with regex first, then direct match
        full_text_search_query = (
            """
            CALL db.index.fulltext.queryNodes($index_name, $name_till_dotunderscore)
            YIELD node AS n, score
            WHERE n.name =~ $name
            RETURN n.name AS name
            """
        )
        records = self.structured_query(full_text_search_query, {
            "index_name": "general_fts_index",
            "name_till_dotunderscore": name_till_dotunderscore,
            "name": processed_name
        })
        if records:
            records_str = "\n\n".join([f"{i + 1}. {record['name']}" for i, record in enumerate(records)])
            result = FULL_TEXT_FULL_NAME_SEARCH_TEMPLATE.format(
                entity_name=name,
                matches=records_str
            )
            return result
        
        return ""