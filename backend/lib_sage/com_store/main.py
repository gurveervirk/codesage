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
from .utils import check_if_not_null
import logging
import neo4j
import json
from concurrent.futures import ThreadPoolExecutor, as_completed

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
    - Relationships: HAS_CLASS, HAS_METHOD, INHERITS, EXPOSES, PUBLISHES
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
        max_workers: Optional[int] = None,
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
        1. Composite indices on (name, content_hash) for all entity types - CRITICAL for MERGE performance
        2. 5 full-text indices in Neo4j:
            - one for ROOT_MODULE entities on 'name' and 'source' properties.
            - one for MODULE entities on 'name' and 'source' properties.
            - one for FUNCTION entities on 'name' and 'source' properties.
            - one for CLASS entities on 'name' and 'source' properties.
            - one for METHOD entities on 'name' and 'source' properties.
        3. 5 vector indices:
            - one for ROOT_MODULE entities on the 'embedding' property.
            - one for FUNCTION entities on the 'embedding' property.
            - one for MODULE entities on the 'embedding' property.
            - one for CLASS entities on the 'embedding' property.
            - one for METHOD entities on the 'embedding' property.

        It uses the IF NOT EXISTS clause to avoid errors if the indices already exist.
        """

        # Create composite uniqueness constraints on (name, content_hash) for MERGE optimization
        # These are CRITICAL for performance and data integrity when using MERGE with both properties
        # Constraints automatically create indexes AND guarantee uniqueness
        composite_constraints = [
            "CREATE CONSTRAINT root_module_unique IF NOT EXISTS FOR (n:ROOT_MODULE) REQUIRE (n.name, n.content_hash) IS UNIQUE",
            "CREATE CONSTRAINT module_unique IF NOT EXISTS FOR (n:MODULE) REQUIRE (n.name, n.content_hash) IS UNIQUE",
            "CREATE CONSTRAINT function_unique IF NOT EXISTS FOR (n:FUNCTION) REQUIRE (n.name, n.content_hash) IS UNIQUE",
            "CREATE CONSTRAINT class_unique IF NOT EXISTS FOR (n:CLASS) REQUIRE (n.name, n.content_hash) IS UNIQUE",
            "CREATE CONSTRAINT method_unique IF NOT EXISTS FOR (n:METHOD) REQUIRE (n.name, n.content_hash) IS UNIQUE",
            "CREATE CONSTRAINT signature_unique IF NOT EXISTS FOR (n:SIGNATURE) REQUIRE (n.name, n.content_hash) IS UNIQUE",
            "CREATE CONSTRAINT resolved_signature_unique IF NOT EXISTS FOR (n:RESOLVED_SIGNATURE) REQUIRE (n.name, n.content_hash) IS UNIQUE",
            "CREATE CONSTRAINT docstring_unique IF NOT EXISTS FOR (n:DOCSTRING) REQUIRE (n.name, n.content_hash) IS UNIQUE",
            "CREATE CONSTRAINT source_unique IF NOT EXISTS FOR (n:SOURCE) REQUIRE (n.name, n.content_hash) IS UNIQUE",
            "CREATE CONSTRAINT decorator_details_unique IF NOT EXISTS FOR (n:DECORATOR_DETAILS) REQUIRE (n.name, n.content_hash) IS UNIQUE",
            "CREATE CONSTRAINT import_details_unique IF NOT EXISTS FOR (n:IMPORT_DETAILS) REQUIRE (n.name, n.content_hash) IS UNIQUE",
        ]
        
        for query in composite_constraints:
            self.database_query(query)

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

        # Create full-text indices for property entity types
        signature_index_query = """
        CREATE FULLTEXT INDEX signature_index IF NOT EXISTS FOR (n:`SIGNATURE`) ON EACH [n.`name`]
        """
        self.database_query(signature_index_query)

        resolved_signature_index_query = """
        CREATE FULLTEXT INDEX resolved_signature_index IF NOT EXISTS FOR (n:`RESOLVED_SIGNATURE`) ON EACH [n.`name`]
        """
        self.database_query(resolved_signature_index_query)

        docstring_index_query = """
        CREATE FULLTEXT INDEX docstring_index IF NOT EXISTS FOR (n:`DOCSTRING`) ON EACH [n.`name`]
        """
        self.database_query(docstring_index_query)

        source_index_query = """
        CREATE FULLTEXT INDEX source_index IF NOT EXISTS FOR (n:`SOURCE`) ON EACH [n.`name`]
        """
        self.database_query(source_index_query)

        decorator_details_index_query = """
        CREATE FULLTEXT INDEX decorator_details_index IF NOT EXISTS FOR (n:`DECORATOR_DETAILS`) ON EACH [n.`name`]
        """
        self.database_query(decorator_details_index_query)

        import_details_index_query = """
        CREATE FULLTEXT INDEX import_details_index IF NOT EXISTS FOR (n:`IMPORT_DETAILS`) ON EACH [n.`name`]
        """
        self.database_query(import_details_index_query)

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
        self, index_name: str, query: Union[str, List[float]], top_k: int = 10,
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
        query: Union[str, List[float]],
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
        Override parent's upsert_nodes to work directly with Entity models.
        This method uses name and content_hash for MERGE operations.
        Entity already has content_hash computed and labels sanitized.
        Supports optional parallel execution via max_workers parameter.
        
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
        
        if not entity_dicts:
            return
        
        upsert_query = """
            UNWIND $data AS row
            MERGE (e {name: row.name, content_hash: row.properties.content_hash})
            ON CREATE SET e += apoc.map.clean(row.properties, [], [])
            WITH e, row
            CALL apoc.create.addLabels(e, row.labels)
            YIELD node
            RETURN count(node)
        """
        
        # Split into chunks
        chunks = [entity_dicts[i:i + CHUNK_SIZE] for i in range(0, len(entity_dicts), CHUNK_SIZE)]
        
        # Parallel execution if max_workers is set
        if self.max_workers and self.max_workers > 1:
            logging.info(f"Upserting {len(entity_dicts)} nodes in parallel with {self.max_workers} workers")
            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                # Submit all chunks as parallel tasks
                futures = [
                    executor.submit(self._execute_query_in_session, upsert_query, {"data": chunk})
                    for chunk in chunks
                ]
                # Wait for all to complete and handle any errors
                for future in as_completed(futures):
                    try:
                        future.result()
                    except Exception as e:
                        logging.error(f"Error in parallel node upsert: {e}")
                        raise
        else:
            # Sequential execution (original behavior)
            for chunk in chunks:
                self.structured_query(upsert_query, param_map={"data": chunk})
    
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
        
        def _extract_entity_type_label(labels: List[str]) -> Optional[str]:
            """Extract primary entity type label (ROOT_MODULE, MODULE, CLASS, etc.)"""
            entity_types = {'ROOT_MODULE', 'MODULE', 'FUNCTION', 'CLASS', 'METHOD', 
                          'SIGNATURE', 'RESOLVED_SIGNATURE', 'DOCSTRING', 'SOURCE', 
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
        
        upsert_rel_query = """
            UNWIND $data AS row
            CALL apoc.cypher.run(
              'MATCH (source:' + row.source_label + ' {name: $source_name, content_hash: $source_content_hash}) 
               MATCH (target:' + row.target_label + ' {name: $target_name, content_hash: $target_content_hash})
               MERGE (source)-[r:' + row.label + ']->(target)
               SET r += $properties
               RETURN $label as rel_type, 1 as created_count',
              {source_name: row.source_name, source_content_hash: row.source_content_hash,
               target_name: row.target_name, target_content_hash: row.target_content_hash,
               properties: row.properties, label: row.label}
            ) YIELD value
            RETURN value.rel_type AS rel_type, value.created_count AS created_count
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
                            for r in result:
                                logging.info(f"Created {r.get('created_count', 0)} {r.get('rel_type', 'unknown')} relationships")
                    except Exception as e:
                        logging.error(f"Error in parallel relationship upsert chunk {i}: {e}")
                        raise
        else:
            # Sequential execution (original behavior)
            for index in range(0, len(params), CHUNK_SIZE):
                chunked_params = params[index : index + CHUNK_SIZE]
                
                try:
                    result = self.structured_query(upsert_rel_query, param_map={"data": chunked_params})
                    
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

        # Add INHERITS, EXPOSES, and PUBLISHES relations as properties to the respective nodes
        self._add_other_relations_as_properties(other_relations)

        # Process INHERITS, EXPOSES, and PUBLISHES relations
        self._process_other_relations()

        # Handle inherited methods
        self._handle_inherited_methods()

        # Set the shortest call paths for all nodes in the module
        self._set_shortest_call_paths(module_name)

    def _add_other_relations_as_properties(self, other_relations: Dict[str, List[Tuple]]):
        """
        Add INHERITS, EXPOSES, and PUBLISHES relations as properties to the respective nodes.
        Now works with (content_hash, ExternalEntityRef) tuples.

        Args:
            other_relations (Dict[str, List[Tuple]]): Dictionary containing INHERITS, EXPOSES, and PUBLISHES relations.
                Each tuple is (from_content_hash, ExternalEntityRef)
        """
        from ..com_extractor import ExternalEntityRef
        
        inherits_relations = other_relations.get("INHERITS", [])
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
        
        # Convert (content_hash, ExternalEntityRef) tuples to (content_hash, target_info_dict) for EXPOSES/PUBLISHES
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
        self.structured_query(add_exposes_query, {"exposes_relations": exposes_processed})
        self.structured_query(add_publishes_query, {"publishes_relations": publishes_processed})

    def _process_other_relations(self):
        """
        Execute Cypher queries to create relations on existing nodes with INHERITS and EXPOSES properties.
        Now handles version-aware matching using JSON-encoded target information.
        Clear info from the INHERITS and EXPOSES property arrays of the nodes if the relations could be created successfully.
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
            MERGE (c)-[r:INHERITS]->(p)
            SET r.versions = apoc.coll.toSet(coalesce(r.versions, []) + [lbl IN labels(c) WHERE lbl STARTS WITH 'version_'])
            WITH c, COLLECT({name: p.name, content_hash: p.content_hash}) AS parentInfo
            SET c.NEW_INHERITED_ENTITIES = [p IN parentInfo | p.name + '::' + p.content_hash]
            REMOVE c.INHERITS
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
        self.structured_query(process_exposes_query)
        self.structured_query(process_publishes_query)
        self.structured_query(cleanup_empty_INHERITS_query)
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
        set_shortest_call_paths_query = (
            """
MATCH (end:MODULE|FUNCTION|CLASS|METHOD)<-[:HAS_SUBMODULE|HAS_CLASS|HAS_METHOD|HAS_FUNCTION|EXPOSES|PUBLISHES*]-(root:ROOT_MODULE {name: $module_name})
WITH root, collect(end) AS endNodes

CALL apoc.path.spanningTree(root, {
    relationshipFilter: 'HAS_SUBMODULE>|HAS_CLASS>|HAS_METHOD>|HAS_FUNCTION>|EXPOSES>|PUBLISHES>',
    endNodes: endNodes
})
YIELD path

WITH nodes(path) AS nodesInPath
WHERE size(nodesInPath) > 1
WITH
    LAST(nodesInPath) AS targetNode,
    nodesInPath[-2] AS parentNode

WHERE targetNode.shortest_call_path IS NULL

SET targetNode.shortest_call_path =
    CASE
        WHEN targetNode.__name__ CONTAINS '.'
        THEN targetNode.__name__
        ELSE COALESCE(parentNode.shortest_call_path, parentNode.name) + '.' + targetNode.__name__
    END

RETURN count(targetNode) AS numPathsSet
"""
        )
        iteration = 0
        total_updated = 0
        while True:
            iteration += 1
            result = self.structured_query(set_shortest_call_paths_query, {"module_name": module_name})
            num_paths_set = result[0]["numPathsSet"] if result else 0
            total_updated += num_paths_set
            
            if num_paths_set == 0:
                break
        
        if total_updated > 0:
            retry_info = f" (completed in {iteration} iteration{'s' if iteration > 1 else ''})" if iteration > 1 else ""
            logging.info(f"Set shortest_call_path for {total_updated} nodes in module {module_name}{retry_info}")

    def _handle_inherited_methods(self):
        """
        Create HAS_METHOD relations for inherited methods for all classes in the specified module.
        Now handles methods with SIGNATURE property entities instead of inline signature properties.
        Uses content_hash for precise version-aware parent matching.
        
        This method runs iteratively to handle inheritance chains:
        - Class C inherits from B, B inherits from A
        - First iteration: B gets methods from A, C gets methods from B
        - Second iteration: C gets newly inherited methods from B (that B got from A)
        - Continues until no new methods are inherited (fixed-point)
        """
        handle_inheritance_query = (
            """
MATCH (child:CLASS)
WHERE child.NEW_INHERITED_ENTITIES IS NOT NULL
WITH child, child.NEW_INHERITED_ENTITIES AS parentInfoList

REMOVE child.NEW_INHERITED_ENTITIES

WITH child, parentInfoList
UNWIND parentInfoList AS parentInfo
WITH child, split(parentInfo, '::') AS parts
WITH child, parts[0] AS parentName, parts[1] AS parentContentHash
MATCH (parent:CLASS {name: parentName, content_hash: parentContentHash})-[:HAS_METHOD]->(member)

WHERE
    NOT 'PRIVATE' IN labels(member)

    AND (
        (
            'DUNDER' IN labels(member) AND
            NOT EXISTS { MATCH (child)-[:HAS_METHOD]->({__name__: member.__name__}) }
        )
        OR
        (
            NOT 'DUNDER' IN labels(member) AND
            NOT EXISTS { 
                MATCH (child)-[:HAS_METHOD]->(childMethod {__name__: member.__name__})-[:HAS_SIGNATURE]->(childSig:SIGNATURE),
                      (member)-[:HAS_SIGNATURE]->(memberSig:SIGNATURE)
                WHERE childSig.value = memberSig.value
            }
        )
    )

WITH child, collect(DISTINCT member) AS members
UNWIND members AS member
MERGE (child)-[r:HAS_METHOD]->(member)
SET r.versions = apoc.coll.toSet(coalesce(r.versions, []) + [lbl IN labels(child) WHERE lbl STARTS WITH 'version_'])

WITH DISTINCT child, collect(member) AS newMembers
WHERE size(newMembers) > 0
WITH child, newMembers
OPTIONAL MATCH (grandchild:CLASS)-[:INHERITS]->(child)
WHERE grandchild IS NOT NULL
WITH child, newMembers, [child.name + '::' + child.content_hash] AS childInfo, collect(DISTINCT grandchild) AS grandchildren
FOREACH (gc IN grandchildren |
    SET gc.NEW_INHERITED_ENTITIES = CASE 
        WHEN gc.NEW_INHERITED_ENTITIES IS NULL THEN childInfo
        ELSE gc.NEW_INHERITED_ENTITIES + childInfo
    END
)
RETURN child.name AS ChildClass, size(newMembers) AS TotalParentMembersLabeled, size(grandchildren) AS GrandchildrenMarked
            """
        )
        
        max_iterations = 100
        iteration = 0
        
        while iteration < max_iterations:
            iteration += 1
            result = self.structured_query(handle_inheritance_query)
            
            if not result or all(r.get('TotalParentMembersLabeled', 0) == 0 for r in result):
                logging.info(f"Inheritance propagation completed after {iteration} iteration(s)")
                break
            
            total_inherited = sum(r.get('TotalParentMembersLabeled', 0) for r in result)
            total_marked = sum(r.get('GrandchildrenMarked', 0) for r in result)
            logging.info(f"Iteration {iteration}: {total_inherited} methods inherited, {total_marked} grandchildren marked for propagation")
        
        if iteration >= max_iterations:
            logging.warning(f"Inheritance propagation stopped after {max_iterations} iterations (possible circular inheritance)")

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
        Excludes property entity types (SIGNATURE, RESOLVED_SIGNATURE, DOCSTRING, SOURCE, DECORATOR_DETAILS, IMPORT_DETAILS).
        """
        retrieve_new_nodes = (
            """
            MATCH (e)
            WHERE NOT e:INTERNAL
            AND NOT e:PRIVATE
            AND NOT e:DUNDER
            AND NOT e:SIGNATURE
            AND NOT e:RESOLVED_SIGNATURE
            AND NOT e:DOCSTRING
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
    
            # For MODULE, ROOT_MODULE, and CLASS, fetch docstring from DOCSTRING property entity
            if node["type"] in ("ROOT_MODULE", "MODULE", "CLASS"):
                docstring_query = """
                MATCH (e {name: $name})-[:HAS_DOCSTRING]->(d:DOCSTRING)
                RETURN d.value AS docstring
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