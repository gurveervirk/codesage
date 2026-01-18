"""
This module is an integration of COM logic with the Neo4jPropertyGraphStore class.
"""
from llama_index.graph_stores.neo4j import Neo4jPropertyGraphStore
from llama_index.core.bridge.pydantic import PrivateAttr
from llama_index.core.graph_stores.types import (
    EntityNode
)
from llama_index.core import Settings
from typing import Any, Dict, List, Optional, Tuple, Union
from ..com_extractor import Entity, Relationship
from .utils import check_if_not_null, _escape_regex_special_chars
import logging
import neo4j
import json
from concurrent.futures import ThreadPoolExecutor, as_completed

logging.basicConfig(level=logging.INFO)
BASE_ENTITY_LABEL = "__Entity__"
BASE_NODE_LABEL = "__Node__"

class COMStore(Neo4jPropertyGraphStore):
    """
    COM stands for Code Object Model.
    This class is a subclass of Neo4jPropertyGraphStore and is used to store and retrieve code entities and their relationships in a Neo4j database.
    It provides ways to create, update, and query entities and relationships in the database. The database stores the Python Modular Tree structure in the form of nodes and relationships.

    Schema:
    - Nodes: DISTRIBUTION_PACKAGE, IMPORT_PACKAGE, MODULE, CLASS, METHOD
    - Relationships: PROVIDES, HAS_SUBMODULE, HAS_CLASS, HAS_METHOD, INTERNAL_INHERITS, EXTERNAL_INHERITS, EXPOSES, PUBLISHES, EXPOSES_ALL, PUBLISHES_ALL
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
    batch_size: int = 1000
    _support_metadata_filter: bool = PrivateAttr()
    _is_enterprise: bool = PrivateAttr()
    custom_fts_indices: Any = []

    _distribution_packages: List[Dict] = PrivateAttr()
    _children: List[Dict] = PrivateAttr()
    _distribution_packages_index: int = PrivateAttr()
    _children_index: int = PrivateAttr()
    _last_distribution_packages_query: Dict = PrivateAttr()
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
        max_workers: Optional[int] = None,
        batch_size: Optional[int] = None,
        **neo4j_kwargs: Any,
    ) -> None:
        self.index_name = index_name
        self.keyword_index_name = keyword_index_name
        self.node_label = node_label
        self.embedding_node_property = embedding_node_property
        self.text_node_property = text_node_property
        self.retrieval_query = retrieval_query
        self.database = database
        # Number of worker threads for parallel upserts (None = sequential, 4-8 recommended for parallel)
        self.max_workers = max_workers
        # Batch size for upserting nodes and relationships (default from parent class is 1000)
        if batch_size is not None:
            self.batch_size = batch_size
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
        self._distribution_packages = []
        self._children = []
        self._distribution_packages_index = 0
        self._children_index = 0
        self._last_distribution_packages_query = {}
        self._last_children_query = {}

    def create_required_indices(self) -> None:
        """
        This method constructs Cypher queries and executes them to create:
        1. Uniqueness constraints on content_hash for all entity types - CRITICAL for MERGE performance
        2. Separate indices on name for query performance
        3. Full-text indices on name for text search
        4. Vector indices on embedding property for similarity search

        It uses the IF NOT EXISTS clause to avoid errors if the indices already exist.
        """

        # Create uniqueness constraints on content_hash for MERGE optimization
        # content_hash is the primary unique identifier (includes name + content)
        # Constraints automatically create indexes AND guarantee uniqueness
        hash_constraints = [
            f"CREATE CONSTRAINT entity_base_unique IF NOT EXISTS FOR (n:{BASE_ENTITY_LABEL}) REQUIRE n.content_hash IS UNIQUE",
            "CREATE CONSTRAINT distribution_package_unique IF NOT EXISTS FOR (n:DISTRIBUTION_PACKAGE) REQUIRE n.content_hash IS UNIQUE",
            "CREATE CONSTRAINT import_package_unique IF NOT EXISTS FOR (n:IMPORT_PACKAGE) REQUIRE n.content_hash IS UNIQUE",
            "CREATE CONSTRAINT module_unique IF NOT EXISTS FOR (n:MODULE) REQUIRE n.content_hash IS UNIQUE",
            "CREATE CONSTRAINT function_unique IF NOT EXISTS FOR (n:FUNCTION) REQUIRE n.content_hash IS UNIQUE",
            "CREATE CONSTRAINT class_unique IF NOT EXISTS FOR (n:CLASS) REQUIRE n.content_hash IS UNIQUE",
            "CREATE CONSTRAINT method_unique IF NOT EXISTS FOR (n:METHOD) REQUIRE n.content_hash IS UNIQUE",
            "CREATE CONSTRAINT resolved_signature_unique IF NOT EXISTS FOR (n:RESOLVED_SIGNATURE) REQUIRE n.content_hash IS UNIQUE",
            "CREATE CONSTRAINT source_unique IF NOT EXISTS FOR (n:SOURCE) REQUIRE n.content_hash IS UNIQUE",
            "CREATE CONSTRAINT decorator_details_unique IF NOT EXISTS FOR (n:DECORATOR_DETAILS) REQUIRE n.content_hash IS UNIQUE",
            "CREATE CONSTRAINT import_details_unique IF NOT EXISTS FOR (n:IMPORT_DETAILS) REQUIRE n.content_hash IS UNIQUE",
        ]
        
        for query in hash_constraints:
            self.database_query(query)
        
        # Create separate indices on name for query performance
        name_indices = [
            "CREATE INDEX distribution_package_name_idx IF NOT EXISTS FOR (n:DISTRIBUTION_PACKAGE) ON (n.name)",
            "CREATE INDEX import_package_name_idx IF NOT EXISTS FOR (n:IMPORT_PACKAGE) ON (n.name)",
            "CREATE INDEX module_name_idx IF NOT EXISTS FOR (n:MODULE) ON (n.name)",
            "CREATE INDEX function_name_idx IF NOT EXISTS FOR (n:FUNCTION) ON (n.name)",
            "CREATE INDEX class_name_idx IF NOT EXISTS FOR (n:CLASS) ON (n.name)",
            "CREATE INDEX method_name_idx IF NOT EXISTS FOR (n:METHOD) ON (n.name)",
            "CREATE INDEX resolved_signature_name_idx IF NOT EXISTS FOR (n:RESOLVED_SIGNATURE) ON (n.name)",
            "CREATE INDEX source_name_idx IF NOT EXISTS FOR (n:SOURCE) ON (n.name)",
            "CREATE INDEX decorator_details_name_idx IF NOT EXISTS FOR (n:DECORATOR_DETAILS) ON (n.name)",
            "CREATE INDEX import_details_name_idx IF NOT EXISTS FOR (n:IMPORT_DETAILS) ON (n.name)",
        ]
        
        for query in name_indices:
            self.database_query(query)


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
    
    def _execute_query_in_session(self, query: str, params: Dict[str, Any]) -> Any:
        """
        Thread-safe helper to execute a query in its own session.
        Used for parallel execution where each thread needs its own session.
        
        Args:
            query (str): The Cypher query to execute
            params (Dict[str, Any]): Query parameters
            
        Returns:
            Query results
        """
        with self._driver.session(database=self.database) as session:
            result = session.run(query, params)
            return [r.data() for r in result]
    
    def upsert_nodes(self, nodes: List[Entity]) -> None:
        """
        Override parent's upsert_nodes with 2-stage upsertion strategy:
        Stage 1: Match existing nodes by content_hash and add new labels (lightweight)
        Stage 2: Create missing nodes with full properties (only for non-existent entities)
        
        This approach minimizes data transfer for existing entities.
        Entity already has content_hash computed and labels sanitized.
        Supports optional parallel execution via max_workers parameter.
        
        Args:
            nodes: List of Entity objects to upsert
        """
        CHUNK_SIZE = self.batch_size
        
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
        
        # Helper to extract primary entity type label
        def _extract_entity_type_label(labels: List[str]) -> Optional[str]:
            """Extract primary entity type label (DISTRIBUTION_PACKAGE, IMPORT_PACKAGE, MODULE, CLASS, etc.)"""
            entity_types = {'DISTRIBUTION_PACKAGE', 'IMPORT_PACKAGE', 'MODULE', 'FUNCTION', 'CLASS', 'METHOD', 
                          'RESOLVED_SIGNATURE', 'SOURCE', 
                          'DECORATOR_DETAILS', 'IMPORT_DETAILS'}
            for label in labels or []:
                if label in entity_types:
                    return label
            return None
        
        # Prepare lightweight data for stage 1 (hash + labels + primary label)
        stage1_data: List[dict] = []
        # Prepare full data for stage 2 (everything)
        entity_map: Dict[str, dict] = {}
        
        for entity in nodes:
            c_hash = entity.content_hash
            # Ensure BASE_ENTITY_LABEL is included for FTS
            sanitized_labels = list(set(entity.labels + [BASE_ENTITY_LABEL]))
            primary_label = _extract_entity_type_label(sanitized_labels)
            
            # Stage 1: lightweight match and label addition
            stage1_data.append({
                "content_hash": c_hash,
                "labels": sanitized_labels,
                "primary_label": primary_label
            })
            
            # Prepare full entity data for stage 2 (if needed)
            properties = dict(entity.properties or {})
            properties["content_hash"] = c_hash
            properties["name"] = entity.name
            properties = _serialize_nested_collections(properties)
            
            entity_map[c_hash] = {
                "name": entity.name,
                "labels": sanitized_labels,
                "properties": properties
            }
        
        if not stage1_data:
            return
        
        # Stage 1: Match existing nodes using the base entity label and content_hash
        # This is more robust than matching by primary label as it handles label changes
        stage1_query = f"""
            UNWIND $data AS row
            MATCH (e:{BASE_ENTITY_LABEL} {{content_hash: row.content_hash}})
            SET e:$(row.labels)
            RETURN row.content_hash AS matched_hash
        """
        
        # Stage 2: Create only the missing nodes with full properties
        stage2_query = f"""
            UNWIND $data AS row
            CREATE (e:{BASE_ENTITY_LABEL} {{content_hash: row.properties.content_hash}})
            SET e += apoc.map.clean(row.properties, [], [])
            WITH e, row
            SET e:$(row.labels)
            RETURN count(e) AS created_count
        """
        
        # Split into chunks
        stage1_chunks = [stage1_data[i:i + CHUNK_SIZE] for i in range(0, len(stage1_data), CHUNK_SIZE)]
        
        # Execute stage 1
        matched_hashes = set()
        total_chunks = len(stage1_chunks)
        logging.info(f"Stage 1: Matching {len(stage1_data)} nodes by content_hash and adding labels ({total_chunks} chunks)")
        
        if self.max_workers and self.max_workers > 1:
            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                futures = [
                    executor.submit(self._execute_query_in_session, stage1_query, {"data": chunk})
                    for chunk in stage1_chunks
                ]
                completed_count = 0
                for future in as_completed(futures):
                    try:
                        result = future.result()
                        for r in result:
                            if r.get("matched_hash"):
                                matched_hashes.add(r["matched_hash"])
                        completed_count += 1
                        if completed_count % 5 == 0 or completed_count == total_chunks:
                            logging.info(f"Stage 1: Processed {completed_count}/{total_chunks} chunks, found {len(matched_hashes)} matches")
                    except Exception as e:
                        logging.error(f"Error in stage 1 parallel upsert: {e}")
                        raise
        else:
            for idx, chunk in enumerate(stage1_chunks, 1):
                result = self.structured_query(stage1_query, param_map={"data": chunk})
                for r in result:
                    if r.get("matched_hash"):
                        matched_hashes.add(r["matched_hash"])
                if idx % 5 == 0 or idx == total_chunks:
                    logging.info(f"Stage 1: Processed {idx}/{total_chunks} chunks, found {len(matched_hashes)} matches")
        
        logging.info(f"Stage 1 complete: Found {len(matched_hashes)} existing nodes")
        
        # Stage 2: Create only missing nodes
        missing_entities = [entity_map[h] for h in entity_map.keys() if h not in matched_hashes]
        
        if not missing_entities:
            logging.info("Stage 2: No new nodes to create")
            return
        
        logging.info(f"Stage 2: Creating {len(missing_entities)} new nodes with full properties")
        stage2_chunks = [missing_entities[i:i + CHUNK_SIZE] for i in range(0, len(missing_entities), CHUNK_SIZE)]
        
        if self.max_workers and self.max_workers > 1:
            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                futures = [
                    executor.submit(self._execute_query_in_session, stage2_query, {"data": chunk})
                    for chunk in stage2_chunks
                ]
                for future in as_completed(futures):
                    try:
                        future.result()
                    except Exception as e:
                        logging.error(f"Error in stage 2 parallel creation: {e}")
                        raise
        else:
            for chunk in stage2_chunks:
                self.structured_query(stage2_query, param_map={"data": chunk})
        
        logging.info(f"Stage 2 complete: Created {len(missing_entities)} new nodes")
    
    def upsert_relations(self, relations: List[Relationship]) -> None:
        """
        Override parent's upsert_relations to work directly with Relationship models.
        Matches nodes by name, version label, and content_hash.
        
        Args:
            relations: List of Relationship objects to upsert
        """
        CHUNK_SIZE = self.batch_size
        
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
        
        def _extract_entity_type_label(labels: List[str]) -> Optional[str]:
            """Extract primary entity type label (DISTRIBUTION_PACKAGE, IMPORT_PACKAGE, MODULE, CLASS, etc.)"""
            entity_types = {'DISTRIBUTION_PACKAGE', 'IMPORT_PACKAGE', 'MODULE', 'FUNCTION', 'CLASS', 'METHOD', 
                          'RESOLVED_SIGNATURE', 'SOURCE', 
                          'DECORATOR_DETAILS', 'IMPORT_DETAILS'}
            for label in labels or []:
                if label in entity_types:
                    return label
            return None
        
        params = []
        relation_type_counts = {}
        
        for r in relations:
            source_name = r.from_entity.name
            target_name = r.to_entity.name
            source_content_hash = r.from_entity.content_hash
            target_content_hash = r.to_entity.content_hash
            
            source_label = _extract_entity_type_label(r.from_entity.labels)
            target_label = _extract_entity_type_label(r.to_entity.labels)
            
            properties = _serialize_nested_collections(r.properties or {})
            
            relation_type_counts[r.label] = relation_type_counts.get(r.label, 0) + 1
            
            params.append({
                "source_name": source_name,
                "source_content_hash": source_content_hash,
                "source_label": source_label,
                "target_name": target_name,
                "target_content_hash": target_content_hash,
                "target_label": target_label,
                "label": r.label,
                "properties": properties
            })
        
        logging.info(f"Upserting {len(params)} relationships: {relation_type_counts}")
        
        upsert_rel_query = f"""
            UNWIND $data AS row
            MATCH (source:{BASE_ENTITY_LABEL} {{content_hash: row.source_content_hash}})
            MATCH (target:{BASE_ENTITY_LABEL} {{content_hash: row.target_content_hash}})
            CALL apoc.merge.relationship(source, row.label, {{}}, row.properties, target) YIELD rel
            RETURN row.label AS rel_type, count(rel) AS created_count
        """
        
        # Split into chunks
        chunks = [params[i:i + CHUNK_SIZE] for i in range(0, len(params), CHUNK_SIZE)]
        
        # Parallel execution if max_workers is set
        if self.max_workers and self.max_workers > 1:
            logging.info(f"Upserting relationships in parallel with {self.max_workers} workers")
            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                # Submit all chunks as parallel tasks
                futures = [
                    executor.submit(self._execute_query_in_session, upsert_rel_query, {"data": chunk})
                    for chunk in chunks
                ]
                # Wait for all to complete and handle any errors
                for i, future in enumerate(as_completed(futures)):
                    try:
                        result = future.result()
                        if result:
                            # Aggregate counts per chunk
                            type_counts = {}
                            for r in result:
                                rel_type = r.get('rel_type', 'unknown')
                                count = r.get('created_count', 0)
                                type_counts[rel_type] = type_counts.get(rel_type, 0) + count
                            # Log once per chunk
                            count_str = ", ".join([f"{count} {rel_type}" for rel_type, count in type_counts.items()])
                            logging.info(f"Chunk {i}: Created {count_str}")
                    except Exception as e:
                        logging.error(f"Error in parallel relationship upsert chunk {i}: {e}")
                        raise
        else:
            # Sequential execution (original behavior)
            for index in range(0, len(params), CHUNK_SIZE):
                chunked_params = params[index : index + CHUNK_SIZE]
                
                try:
                    logging.info(f"Upserting relationship chunk {index}-{index+CHUNK_SIZE} with {len(chunked_params)} relationships")
                    result = self.structured_query(upsert_rel_query, param_map={"data": chunked_params})
                    
                    # Aggregate counts per chunk
                    if result:
                        type_counts = {}
                        for r in result:
                            rel_type = r.get('rel_type', 'unknown')
                            count = r.get('created_count', 0)
                            type_counts[rel_type] = type_counts.get(rel_type, 0) + count
                        # Log once per chunk
                        count_str = ", ".join([f"{count} {rel_type}" for rel_type, count in type_counts.items()])
                        logging.info(f"Chunk {index}-{index+CHUNK_SIZE}: Created {count_str}")
                            
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
            embed_nodes: Optional[bool] = False,
            version: Optional[str] = None
        ) -> None:
        """
        Upsert entities and relationships into Neo4j.

        Args:
            module_name (str): The name of the module.
            entities (List[Entity]): List of entity nodes to upsert.
            relations (List[Relationship]): List of relationships to upsert.
            other_relations (Dict[str, List[Tuple]]): Dictionary containing other relations.
            embed_nodes (bool): Whether to generate embeddings for the nodes.
            version (Optional[str]): The version of the module being processed.
        """
        # Try to detect version from entities if not provided
        if not version and entities:
            for entity in entities:
                for label in entity.labels:
                    if label.startswith("version:"):
                        version = label.split(":", 1)[1]
                        break
                if version:
                    break

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

        # Add INHERITS, EXPOSES, and PUBLISHES relations as properties to the respective nodes
        self._add_other_relations_as_properties(other_relations, source_version=version)

        # Process INHERITS, EXPOSES, and PUBLISHES relations
        self._process_other_relations()

    def _add_other_relations_as_properties(self, other_relations: Dict[str, List[Tuple]], source_version: Optional[str] = None):
        """
        Add INHERITS, EXPOSES, and PUBLISHES relations as properties to the respective nodes.
        Now works with (content_hash, ExternalEntityRef) tuples.

        Args:
            other_relations (Dict[str, List[Tuple]]): Dictionary containing INHERITS, EXPOSES, and PUBLISHES relations.
                Each tuple is (from_content_hash, ExternalEntityRef)
            source_version (Optional[str]): The version of the source entity.
        """
        from ..com_extractor import ExternalEntityRef
        
        internal_inherits = other_relations.get("INTERNAL_INHERITS", [])
        external_inherits = other_relations.get("EXTERNAL_INHERITS", [])
        exposes_relations = other_relations.get("EXPOSES", [])
        publishes_relations = other_relations.get("PUBLISHES", [])
        exposes_all_relations = other_relations.get("EXPOSES_ALL", [])
        publishes_all_relations = other_relations.get("PUBLISHES_ALL", [])
        
        # Convert (content_hash, ExternalEntityRef) tuples to (content_hash, target_info_dict) for INTERNAL_INHERITS
        internal_inherits_processed = []
        for from_hash, to_ref in internal_inherits:
            if isinstance(to_ref, ExternalEntityRef):
                # Store as dict with name and version
                target_info = {
                    "name": to_ref.name,
                    "version": to_ref.version,
                    "source_version": source_version,
                    "alias": to_ref.alias
                }
                internal_inherits_processed.append((from_hash, json.dumps(target_info)))
            else:
                # Legacy format: just name
                target_info = {
                    "name": to_ref,
                    "version": None,
                    "source_version": source_version,
                    "alias": None
                }
                internal_inherits_processed.append((from_hash, json.dumps(target_info)))

        # Convert (content_hash, ExternalEntityRef) tuples to (content_hash, target_info_dict) for EXTERNAL_INHERITS
        external_inherits_processed = []
        for from_hash, to_ref in external_inherits:
            if isinstance(to_ref, ExternalEntityRef):
                # Store as dict with name and version
                target_info = {
                    "name": to_ref.name,
                    "version": to_ref.version,
                    "source_version": source_version,
                    "alias": to_ref.alias
                }
                external_inherits_processed.append((from_hash, json.dumps(target_info)))
            else:
                # Legacy format: just name
                target_info = {
                    "name": to_ref,
                    "version": None,
                    "source_version": source_version,
                    "alias": None
                }
                external_inherits_processed.append((from_hash, json.dumps(target_info)))
        
        # Convert (content_hash, ExternalEntityRef) tuples to (content_hash, target_info_dict) for EXPOSES/PUBLISHES
        exposes_processed = []
        for from_hash, to_ref in exposes_relations:
            if isinstance(to_ref, ExternalEntityRef):
                target_info = {
                    "name": to_ref.name,
                    "version": to_ref.version,
                    "source_version": source_version,
                    "alias": to_ref.alias
                }
                exposes_processed.append((from_hash, json.dumps(target_info)))
            else:
                target_info = {
                    "name": to_ref,
                    "version": None,
                    "source_version": source_version,
                    "alias": None
                }
                exposes_processed.append((from_hash, json.dumps(target_info)))
        
        publishes_processed = []
        for from_hash, to_ref in publishes_relations:
            if isinstance(to_ref, ExternalEntityRef):
                target_info = {
                    "name": to_ref.name,
                    "version": to_ref.version,
                    "source_version": source_version,
                    "alias": to_ref.alias
                }
                publishes_processed.append((from_hash, json.dumps(target_info)))
            else:
                target_info = {
                    "name": to_ref,
                    "version": None,
                    "source_version": source_version,
                    "alias": None
                }
                publishes_processed.append((from_hash, json.dumps(target_info)))
        
        # Convert (content_hash, ExternalEntityRef) tuples to (content_hash, target_info_dict) for EXPOSES_ALL/PUBLISHES_ALL
        exposes_all_processed = []
        for from_hash, to_ref in exposes_all_relations:
            if isinstance(to_ref, ExternalEntityRef):
                target_info = {
                    "name": to_ref.name,
                    "version": to_ref.version,
                    "source_version": source_version,
                    "alias": to_ref.alias
                }
                exposes_all_processed.append((from_hash, json.dumps(target_info)))
            else:
                target_info = {
                    "name": to_ref,
                    "version": None,
                    "source_version": source_version,
                    "alias": None
                }
                exposes_all_processed.append((from_hash, json.dumps(target_info)))
        
        publishes_all_processed = []
        for from_hash, to_ref in publishes_all_relations:
            if isinstance(to_ref, ExternalEntityRef):
                target_info = {
                    "name": to_ref.name,
                    "version": to_ref.version,
                    "source_version": source_version,
                    "alias": to_ref.alias
                }
                publishes_all_processed.append((from_hash, json.dumps(target_info)))
            else:
                target_info = {
                    "name": to_ref,
                    "version": None,
                    "source_version": source_version,
                    "alias": None
                }
                publishes_all_processed.append((from_hash, json.dumps(target_info)))

        add_internal_inherits_query = (
            """
            UNWIND $inherits_relations AS rel
            MATCH (c:CLASS {content_hash: rel[0]})
            SET c.INTERNAL_INHERITS = apoc.coll.toSet(coalesce(c.INTERNAL_INHERITS, []) + [rel[1]])
            """
        )
        add_external_inherits_query = (
            """
            UNWIND $inherits_relations AS rel
            MATCH (c:CLASS {content_hash: rel[0]})
            SET c.EXTERNAL_INHERITS = apoc.coll.toSet(coalesce(c.EXTERNAL_INHERITS, []) + [rel[1]])
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
        add_exposes_all_query = (
            """
            UNWIND $exposes_all_relations AS rel
            MATCH (m {content_hash: rel[0]})
            SET m.EXPOSES_ALL = apoc.coll.toSet(coalesce(m.EXPOSES_ALL, []) + [rel[1]])
            """
        )
        add_publishes_all_query = (
            """
            UNWIND $publishes_all_relations AS rel
            MATCH (m {content_hash: rel[0]})
            SET m.PUBLISHES_ALL = apoc.coll.toSet(coalesce(m.PUBLISHES_ALL, []) + [rel[1]])
            """
        )
        self.structured_query(add_internal_inherits_query, {"inherits_relations": internal_inherits_processed})
        self.structured_query(add_external_inherits_query, {"inherits_relations": external_inherits_processed})
        self.structured_query(add_exposes_query, {"exposes_relations": exposes_processed})
        self.structured_query(add_publishes_query, {"publishes_relations": publishes_processed})
        self.structured_query(add_exposes_all_query, {"exposes_all_relations": exposes_all_processed})
        self.structured_query(add_publishes_all_query, {"publishes_all_relations": publishes_all_processed})

    def _process_other_relations(self):
        """
        Execute Cypher queries to create relations on existing nodes with INHERITS and EXPOSES properties.
        Now handles version-aware matching using JSON-encoded target information.
        Clear info from the INHERITS and EXPOSES property arrays of the nodes if the relations could be created successfully.
        """
        # Process INTERNAL_INHERITS with version-aware matching
        process_internal_inherits_query = (
            """
            MATCH (c:CLASS)
            WHERE c.INTERNAL_INHERITS IS NOT NULL
            UNWIND c.INTERNAL_INHERITS AS parentInfo
            WITH c, parentInfo,
                 CASE WHEN parentInfo STARTS WITH '{' 
                      THEN apoc.convert.fromJsonMap(parentInfo)
                      ELSE {name: parentInfo, version: null, content_hash: null, source_version: null, alias: null}
                 END AS parentData
            OPTIONAL MATCH (p:CLASS {name: parentData.name})
            WHERE parentData.version IS NULL 
               OR ('version_' + replace(replace(replace(parentData.version, '.', '_'), ':', '_'), '-', '_')) IN labels(p)
            WITH c, parentInfo, p, parentData
            WHERE p IS NOT NULL
            MERGE (c)-[r:INTERNAL_INHERITS]->(p)
            SET r.alias = parentData.alias
            SET r.versions = apoc.coll.toSet(coalesce(r.versions, []) + 
                CASE WHEN parentData.source_version IS NOT NULL 
                     THEN ['version_' + replace(replace(replace(parentData.source_version, '.', '_'), ':', '_'), '-', '_')]
                     ELSE [lbl IN labels(c) WHERE lbl STARTS WITH 'version_'] 
                END
            )
            WITH c, COLLECT(p.content_hash) AS parentHashes, COLLECT(parentInfo) as processedInfos
            SET c.NEW_Internally_INHERITED_ENTITIES = parentHashes
            SET c.INTERNAL_INHERITS = [info IN c.INTERNAL_INHERITS WHERE NOT info IN processedInfos]
            """
        )
        
        # Process EXTERNAL_INHERITS with version-aware matching
        process_external_inherits_query = (
            """
            MATCH (c:CLASS)
            WHERE c.EXTERNAL_INHERITS IS NOT NULL
            UNWIND c.EXTERNAL_INHERITS AS parentInfo
            WITH c, parentInfo,
                 CASE WHEN parentInfo STARTS WITH '{' 
                      THEN apoc.convert.fromJsonMap(parentInfo)
                      ELSE {name: parentInfo, version: null, content_hash: null, source_version: null, alias: null}
                 END AS parentData
            OPTIONAL MATCH (p:CLASS {name: parentData.name})
            WHERE parentData.version IS NULL 
               OR ('version_' + replace(replace(replace(parentData.version, '.', '_'), ':', '_'), '-', '_')) IN labels(p)
            WITH c, parentInfo, p, parentData
            WHERE p IS NOT NULL
            MERGE (c)-[r:EXTERNAL_INHERITS]->(p)
            SET r.alias = parentData.alias
            SET r.versions = apoc.coll.toSet(coalesce(r.versions, []) + 
                CASE WHEN parentData.source_version IS NOT NULL 
                     THEN ['version_' + replace(replace(replace(parentData.source_version, '.', '_'), ':', '_'), '-', '_')]
                     ELSE [lbl IN labels(c) WHERE lbl STARTS WITH 'version_'] 
                END
            )
            WITH c, COLLECT(p.content_hash) AS parentHashes, COLLECT(parentInfo) as processedInfos
            SET c.NEW_Externally_INHERITED_ENTITIES = parentHashes
            SET c.EXTERNAL_INHERITS = [info IN c.EXTERNAL_INHERITS WHERE NOT info IN processedInfos]
            """
        )
        
        # Process EXPOSES with version-aware matching
        process_exposes_query = (
            """
            MATCH (m:MODULE|IMPORT_PACKAGE)
            WHERE m.EXPOSES IS NOT NULL
            UNWIND m.EXPOSES AS exposedInfo
            WITH m, exposedInfo,
                 CASE WHEN exposedInfo STARTS WITH '{'
                      THEN apoc.convert.fromJsonMap(exposedInfo)
                      ELSE {name: exposedInfo, version: null, source_version: null, alias: null}
                 END AS exposedData
            OPTIONAL MATCH (e {name: exposedData.name})
            WHERE exposedData.version IS NULL
               OR ('version_' + replace(replace(replace(exposedData.version, '.', '_'), ':', '_'), '-', '_')) IN labels(e)
            WITH m, exposedInfo, e, exposedData
            WHERE e IS NOT NULL
            MERGE (m)-[r:EXPOSES]->(e)
            SET r.alias = exposedData.alias
            SET r.versions = apoc.coll.toSet(coalesce(r.versions, []) + 
                CASE WHEN exposedData.source_version IS NOT NULL 
                     THEN ['version_' + replace(replace(replace(exposedData.source_version, '.', '_'), ':', '_'), '-', '_')]
                     ELSE [lbl IN labels(m) WHERE lbl STARTS WITH 'version_'] 
                END
            )
            WITH m, COLLECT(exposedInfo) AS processedExposes
            SET m.EXPOSES = [info IN m.EXPOSES WHERE NOT info IN processedExposes]
            """
        )
        
        process_publishes_query = (
            """
            MATCH (m:MODULE|IMPORT_PACKAGE)
            WHERE m.PUBLISHES IS NOT NULL
            UNWIND m.PUBLISHES AS publishedInfo
            WITH m, publishedInfo,
                 CASE WHEN publishedInfo STARTS WITH '{'
                      THEN apoc.convert.fromJsonMap(publishedInfo)
                      ELSE {name: publishedInfo, version: null, source_version: null, alias: null}
                 END AS publishedData
            OPTIONAL MATCH (e {name: publishedData.name})
            WHERE publishedData.version IS NULL
               OR ('version_' + replace(replace(replace(publishedData.version, '.', '_'), ':', '_'), '-', '_')) IN labels(e)
            WITH m, publishedInfo, e, publishedData
            WHERE e IS NOT NULL
            MERGE (m)-[r:PUBLISHES]->(e)
            SET r.alias = publishedData.alias
            SET r.versions = apoc.coll.toSet(coalesce(r.versions, []) + 
                CASE WHEN publishedData.source_version IS NOT NULL 
                     THEN ['version_' + replace(replace(replace(publishedData.source_version, '.', '_'), ':', '_'), '-', '_')]
                     ELSE [lbl IN labels(m) WHERE lbl STARTS WITH 'version_'] 
                END
            )
            WITH m, COLLECT(publishedInfo) AS processedPublishes
            SET m.PUBLISHES = [info IN m.PUBLISHES WHERE NOT info IN processedPublishes]
            """
        )
        
        cleanup_empty_INTERNAL_INHERITS_query = (
            """
            MATCH (n)
            WHERE n.INTERNAL_INHERITS IS NOT NULL AND size(n.INTERNAL_INHERITS) = 0
            REMOVE n.INTERNAL_INHERITS
            """
        )
        cleanup_empty_EXTERNAL_INHERITS_query = (
            """
            MATCH (n)
            WHERE n.EXTERNAL_INHERITS IS NOT NULL AND size(n.EXTERNAL_INHERITS) = 0
            REMOVE n.EXTERNAL_INHERITS
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
        
        process_exposes_all_query = (
            """
            MATCH (m:MODULE|IMPORT_PACKAGE)
            WHERE m.EXPOSES_ALL IS NOT NULL
            UNWIND m.EXPOSES_ALL AS exposedInfo
            WITH m, exposedInfo,
                 CASE WHEN exposedInfo STARTS WITH '{'
                      THEN apoc.convert.fromJsonMap(exposedInfo)
                      ELSE {name: exposedInfo, version: null, source_version: null, alias: null}
                 END AS exposedData
            OPTIONAL MATCH (e {name: exposedData.name})
            WHERE exposedData.version IS NULL
               OR ('version_' + replace(replace(replace(exposedData.version, '.', '_'), ':', '_'), '-', '_')) IN labels(e)
            WITH m, exposedInfo, e, exposedData
            WHERE e IS NOT NULL
            MERGE (m)-[r:EXPOSES_ALL]->(e)
            SET r.alias = exposedData.alias
            SET r.versions = apoc.coll.toSet(coalesce(r.versions, []) + 
                CASE WHEN exposedData.source_version IS NOT NULL 
                     THEN ['version_' + replace(replace(replace(exposedData.source_version, '.', '_'), ':', '_'), '-', '_')]
                     ELSE [lbl IN labels(m) WHERE lbl STARTS WITH 'version_'] 
                END
            )
            WITH m, COLLECT(exposedInfo) AS processedExposes
            SET m.EXPOSES_ALL = [info IN m.EXPOSES_ALL WHERE NOT info IN processedExposes]
            """
        )
        
        process_publishes_all_query = (
            """
            MATCH (m:MODULE|IMPORT_PACKAGE)
            WHERE m.PUBLISHES_ALL IS NOT NULL
            UNWIND m.PUBLISHES_ALL AS publishedInfo
            WITH m, publishedInfo,
                 CASE WHEN publishedInfo STARTS WITH '{'
                      THEN apoc.convert.fromJsonMap(publishedInfo)
                      ELSE {name: publishedInfo, version: null, source_version: null, alias: null}
                 END AS publishedData
            OPTIONAL MATCH (e {name: publishedData.name})
            WHERE publishedData.version IS NULL
               OR ('version_' + replace(replace(replace(publishedData.version, '.', '_'), ':', '_'), '-', '_')) IN labels(e)
            WITH m, publishedInfo, e, publishedData
            WHERE e IS NOT NULL
            MERGE (m)-[r:PUBLISHES_ALL]->(e)
            SET r.alias = publishedData.alias
            SET r.versions = apoc.coll.toSet(coalesce(r.versions, []) + 
                CASE WHEN publishedData.source_version IS NOT NULL 
                     THEN ['version_' + replace(replace(replace(publishedData.source_version, '.', '_'), ':', '_'), '-', '_')]
                     ELSE [lbl IN labels(m) WHERE lbl STARTS WITH 'version_'] 
                END
            )
            WITH m, COLLECT(publishedInfo) AS processedPublishes
            SET m.PUBLISHES_ALL = [info IN m.PUBLISHES_ALL WHERE NOT info IN processedPublishes]
            """
        )

        cleanup_empty_EXPOSES_ALL_query = (
            """
            MATCH (n)
            WHERE n.EXPOSES_ALL IS NOT NULL AND size(n.EXPOSES_ALL) = 0
            REMOVE n.EXPOSES_ALL
            """
        )

        cleanup_empty_PUBLISHES_ALL_query = (
            """
            MATCH (n)
            WHERE n.PUBLISHES_ALL IS NOT NULL AND size(n.PUBLISHES_ALL) = 0
            REMOVE n.PUBLISHES_ALL
            """
        )

        self.structured_query(process_internal_inherits_query)
        self.structured_query(process_external_inherits_query)
        self.structured_query(process_exposes_query)
        self.structured_query(process_publishes_query)
        self.structured_query(process_exposes_all_query)
        self.structured_query(process_publishes_all_query)
        self.structured_query(cleanup_empty_INTERNAL_INHERITS_query)
        self.structured_query(cleanup_empty_EXTERNAL_INHERITS_query)
        self.structured_query(cleanup_empty_EXPOSES_query)
        self.structured_query(cleanup_empty_PUBLISHES_query)
        self.structured_query(cleanup_empty_EXPOSES_ALL_query)
        self.structured_query(cleanup_empty_PUBLISHES_ALL_query)
    
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
        Excludes property entity types (RESOLVED_SIGNATURE, SOURCE, DECORATOR_DETAILS, IMPORT_DETAILS).
        """
        retrieve_new_nodes = (
            """
            MATCH (e)
            WHERE NOT e:INTERNAL
            AND NOT e:PRIVATE
            AND NOT e:DUNDER
            AND NOT e:RESOLVED_SIGNATURE
            AND NOT e:SOURCE
            AND NOT e:DECORATOR_DETAILS
            AND NOT e:IMPORT_DETAILS
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
        
        logging.info(f"Found {len(new_nodes)} new nodes to embed in this batch.")

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
    
            # For MODULE, IMPORT_PACKAGE, and CLASS, fetch docstring from SOURCE property entity
            if node["type"] in ("IMPORT_PACKAGE", "MODULE", "CLASS"):
                docstring_query = """
                MATCH (e {name: $name})-[:HAS_SOURCE]->(s:SOURCE)
                RETURN s.docstring AS docstring
                """
                docstring_result = self.structured_query(docstring_query, {"name": node["name"]})
                if docstring_result and docstring_result[0].get("docstring"):
                    docstring = docstring_result[0]["docstring"]
                    if docstring and len(docstring) > 0:
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