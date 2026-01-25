"""
This module is an integration of COM logic with the Neo4jPropertyGraphStore class.
"""
from llama_index.graph_stores.neo4j import Neo4jPropertyGraphStore
from llama_index.core.bridge.pydantic import PrivateAttr
from llama_index.core.graph_stores.types import (
    EntityNode, Relation
)
from llama_index.core import Settings
from typing import Any, Dict, List, Optional, Tuple
from ...com_extractor import Entity, Relationship
import logging
import neo4j
import hashlib
import json
import xml.etree.ElementTree as ET
from xml.dom import minidom
import re

logging.basicConfig(level=logging.INFO)
BASE_ENTITY_LABEL = "__Entity__"
BASE_NODE_LABEL = "__Node__"

def _escape_xml(text: str) -> str:
    """Escape special XML characters in text."""
    if text is None:
        return ""
    text = str(text)
    text = text.replace("&", "&amp;")
    text = text.replace("<", "&lt;")
    text = text.replace(">", "&gt;")
    text = text.replace('"', "&quot;")
    text = text.replace("'", "&apos;")
    return text

def _dict_to_xml_string(data: Dict[str, Any], root_tag: str = "response") -> str:
    """
    Convert a dictionary to a formatted XML string.
    
    Args:
        data: Dictionary to convert
        root_tag: Root element tag name
        
    Returns:
        Formatted XML string
    """
    def _add_element(parent: ET.Element, key: str, value: Any) -> None:
        """Recursively add elements to the XML tree."""
        if value is None:
            elem = ET.SubElement(parent, key)
            elem.text = ""
        elif isinstance(value, dict):
            elem = ET.SubElement(parent, key)
            for k, v in value.items():
                _add_element(elem, k, v)
        elif isinstance(value, list):
            elem = ET.SubElement(parent, key)
            for item in value:
                if isinstance(item, dict):
                    item_elem = ET.SubElement(elem, "item")
                    for k, v in item.items():
                        _add_element(item_elem, k, v)
                else:
                    item_elem = ET.SubElement(elem, "item")
                    item_elem.text = _escape_xml(item)
        else:
            elem = ET.SubElement(parent, key)
            elem.text = _escape_xml(value)
    
    root = ET.Element(root_tag)
    for key, value in data.items():
        _add_element(root, key, value)
    
    # Convert to string with pretty formatting
    xml_str = ET.tostring(root, encoding='unicode')
    
    # Parse and pretty print
    dom = minidom.parseString(xml_str)
    return dom.toprettyxml(indent="  ")

def _escape_regex_special_chars(text: str) -> str:
    r"""
    Escape special regex characters in a string for use in Cypher regex patterns.
    
    This escapes characters that have special meaning in regex: . ^ $ * + ? { } [ ] \ | ( )
    
    Args:
        text: String that may contain regex special characters
        
    Returns:
        String with regex special characters escaped
    """
    return re.escape(text)

def _extract_partial_terms(term: str) -> List[str]:
    """
    Extract partial search terms from a potentially fully-qualified name.
    
    For example, 'mod.mod2.entity' would return ['entity', 'mod2.entity', 'mod.mod2.entity']
    This allows finding entities by their simple name or partial path even if the full path doesn't exist.
    
    Args:
        term: Search term (potentially a dotted path)
        
    Returns:
        List of progressively longer partial terms, starting from the rightmost component
    """
    if '.' not in term:
        return [term]
    
    parts = term.split('.')
    partial_terms = []
    
    # Build from right to left: entity, mod2.entity, mod.mod2.entity
    for i in range(len(parts)):
        partial = '.'.join(parts[i:])
        partial_terms.append(partial)
    
    # Reverse to get longest matches first (prefer more specific matches)
    return list(reversed(partial_terms))

def check_if_not_null(props: List[str], values: List[Any]) -> None:
    """Check if variable is not null and raise error accordingly."""
    for prop, value in zip(props, values):
        if not value:
            raise ValueError(f"Parameter `{prop}` must not be None or empty string")

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

    def retrieve_relevant_root_modules(self, query: str, top_k: int) -> str:
        """
        Retrieve all relevant root modules based on the query, using similarity search, and store them for pagination.

        Args:
            query (str): The query string.
            top_k (int): The number of results to return. Defaults to 5.

        Returns:
            str: XML-formatted string containing:
                - results: Top k relevant root modules based on the query, each with:
                    - name (str): Module name
                    - score (float): Similarity score
                    - summary (str): Module summary
                - query_info: Information about the query
                - system_message (str): Informational message
        """
        # Clean input params
        top_k = int(top_k)

        # Create a Cypher query to return all root modules based on similarity to the query
        retrieve_root_modules_query = """
            MATCH (m:ROOT_MODULE)
            WHERE m.embedding IS NOT NULL
            WITH m,
                vector.similarity.cosine(m.embedding, $query_vector) AS similarity
            ORDER BY similarity DESC
            RETURN m.name AS name, similarity AS score, m.summary AS summary
        """

        query_params = {
            "query_vector": Settings.embed_model.get_query_embedding(query)
        }

        # Execute the query to retrieve all relevant root modules
        results = self.database_query(retrieve_root_modules_query, query_params)

        # Store the results
        self._root_modules = results
        self._root_modules_index = top_k
        self._last_root_modules_query = {"query": query, "top_k": top_k}

        data = {
            "results": self._root_modules[:top_k],
            "query_info": {
                "query": query,
                "top_k": top_k,
                "total_found": len(results)
            },
            "system_message": f"Retrieved top {top_k} relevant root modules from {len(results)} total matches."
        }
        return _dict_to_xml_string(data, "retrieve_relevant_root_modules_response")
    
    def retrieve_relevant_children_in_subtree(self, query: str, parent_name: str, top_k: int) -> str:
        """
        Retrieve all relevant IMMEDIATE children in the subtree of the given parent based on the query, using similarity search, and store them for pagination.

        Args:
            query (str): The query string.
            parent_name (str): The name of the parent entity.
            top_k (int): The number of results to return. Defaults to 5.

        Returns:
            str: XML-formatted string containing:
                - results: Top k relevant children in subtree, each with:
                    - name (str): Child name
                    - score (float): Similarity score
                    - labels (list): Entity labels
                    - summary (str): Child summary
                - query_info: Information about the query
                - system_message (str): Informational message
        """
        # Clean input params
        top_k = int(top_k)
        
        # Embed the query
        query_vector = Settings.embed_model.get_query_embedding(query)

        # Use a cypher query to return all IMMEDIATE children of the parent entity, sorted by similarity to the query
        sort_and_return_children_query = """
            MATCH (parent {name: $parent_name})-[:HAS_SUBMODULE|HAS_CLASS|HAS_METHOD|HAS_FUNCTION|EXPOSES|PUBLISHES]->(child)
            WHERE child.embedding IS NOT NULL
            WITH parent, child,
                vector.similarity.cosine(child.embedding, $query_vector) AS similarity
            ORDER BY similarity DESC
            RETURN child.name AS name, similarity AS score, labels(child) AS labels, child.summary AS summary
        """

        query_params = {
            "parent_name": parent_name,
            "query_vector": query_vector,
        }

        try:
            records = self.database_query(sort_and_return_children_query, query_params)

            # Filter out base labels and retain only the relevant labels
            for record in records:
                record["labels"] = [label for label in record["labels"] if label not in [BASE_ENTITY_LABEL, BASE_NODE_LABEL]]

            # Store the results
            self._children = records
            self._children_index = top_k
            self._last_children_query = {"query": query, "parent_name": parent_name, "top_k": top_k}
            
            data = {
                "results": self._children[:top_k],
                "query_info": {
                    "query": query,
                    "parent_name": parent_name,
                    "top_k": top_k,
                    "total_found": len(records)
                },
                "system_message": f"Retrieved top {top_k} relevant children from {len(records)} total matches under '{parent_name}'."
            }
            return _dict_to_xml_string(data, "retrieve_relevant_children_response")
        
        except Exception as e:
            logging.error(f"Error retrieving relevant children in subtree: {e}")
            data = {
                "results": [],
                "query_info": {
                    "query": query,
                    "parent_name": parent_name,
                    "top_k": top_k,
                    "total_found": 0
                },
                "system_message": f"Error retrieving relevant children in subtree: {str(e)}"
            }
            return _dict_to_xml_string(data, "retrieve_relevant_children_response")

    def next_entities(self, from_: str, top_k: int) -> str:
        """
        Retrieve the next top_k entities from the stored list.

        Args:
            from_ (str): "ROOT_MODULE" or "CHILDREN", indicating which list to retrieve from.
            top_k (int): The number of entities to retrieve.

        Returns:
            str: XML-formatted string containing:
                - results: The next top_k entities
                - pagination_info: Information about pagination status
                - system_message (str): Informational message
        """
        top_k = int(top_k)
        if from_ == "ROOT_MODULE":
            if self._root_modules == None or self._root_modules_index == -1:
                data = {
                    "results": [],
                    "pagination_info": {
                        "source": "ROOT_MODULE",
                        "has_more": False,
                        "all_retrieved": True
                    },
                    "system_message": "NO ROOT MODULES HAVE BEEN QUERIED FOR. PROCEED WITH QUERYING `retrieve_relevant_root_modules`."
                }
                return _dict_to_xml_string(data, "next_entities_response")
            
            start_index = self._root_modules_index
            end_index = min(start_index + top_k, len(self._root_modules))
            entities = self._root_modules[start_index:end_index]
            self._root_modules_index = end_index
            all_retrieved = end_index == len(self._root_modules)
            
            if all_retrieved:
                self._root_modules = None
                self._root_modules_index = -1
            
            data = {
                "results": entities,
                "pagination_info": {
                    "source": "ROOT_MODULE",
                    "start_index": start_index,
                    "end_index": end_index,
                    "has_more": not all_retrieved,
                    "all_retrieved": all_retrieved
                },
                "system_message": f"Retrieved entities {start_index+1} to {end_index}." + 
                                 (" ALL RELEVANT ROOT MODULES RETRIEVED." if all_retrieved else f" {len(self._root_modules) - end_index} more available.")
            }
            return _dict_to_xml_string(data, "next_entities_response")

        elif from_ == "CHILDREN":
            if self._children == None or self._children_index == -1:
                data = {
                    "results": [],
                    "pagination_info": {
                        "source": "CHILDREN",
                        "has_more": False,
                        "all_retrieved": True
                    },
                    "system_message": "NO CHILDREN HAVE BEEN QUERIED FOR. PROCEED WITH QUERYING `retrieve_relevant_children_in_subtree`."
                }
                return _dict_to_xml_string(data, "next_entities_response")
            
            start_index = self._children_index
            end_index = min(start_index + top_k, len(self._children))
            entities = self._children[start_index:end_index]
            self._children_index = end_index
            all_retrieved = end_index == len(self._children)
            
            if all_retrieved:
                self._children = None
                self._children_index = -1
            
            data = {
                "results": entities,
                "pagination_info": {
                    "source": "CHILDREN",
                    "start_index": start_index,
                    "end_index": end_index,
                    "has_more": not all_retrieved,
                    "all_retrieved": all_retrieved
                },
                "system_message": f"Retrieved entities {start_index+1} to {end_index}." + 
                                 (" ALL RELEVANT CHILDREN RETRIEVED." if all_retrieved else f" {len(self._children) - end_index} more available.")
            }
            return _dict_to_xml_string(data, "next_entities_response")
        else:
            raise ValueError("`from` must be either 'ROOT_MODULE' or 'CHILDREN'")

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
        self._handle_inherited_methods(module_name)

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
        from ...com_extractor import ExternalEntityRef
        
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
    
    def get_full_path_name(self, name: str) -> str:
        """
        Get the full path name of the entity.

        Args:
            name (str): The name of the entity.

        Returns:
            str: XML-formatted string containing:
                - exact_match (str): The full path name of the entity if found
                - best_matches: List of best matches if no exact match is found
                - system_message (str): Informational message
        """
        retrieve_node_by_name_query = (
            """
            MATCH (n:METHOD|FUNCTION|CLASS|MODULE {name: $name})
            RETURN n.name AS name
            """
        )

        # Execute the query to retrieve the node by name
        retrieved_node = self.structured_query(retrieve_node_by_name_query, {"name": name})

        if retrieved_node:
            retrieved_name = retrieved_node[0]["name"]
            data = {
                "exact_match": retrieved_name,
                "best_matches": [],
                "system_message": f"Exact match found for '{name}'."
            }
            return _dict_to_xml_string(data, "get_full_path_name_response")

        # If no relevant nodes are found, process the name for regex search
        logging.info(f"No relevant nodes found for the name: {name}")
        logging.info(f"Performing full-text search for the full path name of the entity: {name}")
        records_str = self._fts_full_path_name(name)

        if records_str:
            # Extract matches from the formatted string
            matches = [line.strip() for line in records_str.split('\n\n') if line.strip() and not line.startswith('Best matches')]
            data = {
                "exact_match": "",
                "best_matches": matches,
                "system_message": f"Found {len(matches)} potential matches for '{name}'."
            }
            return _dict_to_xml_string(data, "get_full_path_name_response")
            
        # Split the name by '.', merge first and last parts, and try to find the full path name
        logging.info(f"Performing full-text search for the full path name of the entity with shortened name: {name}")
        name_parts = name.split(".")
        shortened_name = name_parts[0] + "." + name_parts[-1]
        records_str = self._fts_full_path_name(shortened_name)

        if records_str:
            matches = [line.strip() for line in records_str.split('\n\n') if line.strip() and not line.startswith('Best matches')]
            data = {
                "exact_match": "",
                "best_matches": matches,
                "system_message": f"Found {len(matches)} potential matches using shortened name '{shortened_name}'."
            }
            return _dict_to_xml_string(data, "get_full_path_name_response")
        
        # If no relevant nodes are found, return a message indicating that the full path name could not be found
        logging.warning(f"No full path name found for the entity: {name}")

        data = {
            "exact_match": "",
            "best_matches": [],
            "system_message": f"No full path name found for entity: '{name}'"
        }
        return _dict_to_xml_string(data, "get_full_path_name_response")
    
    def get_full_path_names(self, names: List[str]) -> str:
        """
        Get the full path names of multiple entities.

        Args:
            names (List[str]): List of entity names.

        Returns:
            str: XML-formatted string containing full path name results for each entity
        """
        results = []
        for name in names:
            # We need to parse the individual XML response to extract data
            # For simplicity, let's make direct database calls here
            retrieve_node_by_name_query = (
                """
                MATCH (n:METHOD|FUNCTION|CLASS|MODULE {name: $name})
                RETURN n.name AS name
                """
            )
            retrieved_node = self.structured_query(retrieve_node_by_name_query, {"name": name})
            
            if retrieved_node:
                results.append({
                    "query_name": name,
                    "exact_match": retrieved_node[0]["name"],
                    "best_matches": [],
                    "found": True
                })
            else:
                # Try FTS
                records_str = self._fts_full_path_name(name)
                if records_str:
                    matches = [line.strip() for line in records_str.split('\n\n') if line.strip() and not line.startswith('Best matches')]
                    results.append({
                        "query_name": name,
                        "exact_match": "",
                        "best_matches": matches,
                        "found": True
                    })
                else:
                    results.append({
                        "query_name": name,
                        "exact_match": "",
                        "best_matches": [],
                        "found": False
                    })

        data = {
            "results": results,
            "system_message": f"Processed {len(names)} entity name(s)."
        }
        return _dict_to_xml_string(data, "get_full_path_names_response")
    
    def get_signatures(self, entity_names: List[str]) -> str:
        """
        Get signatures for multiple entities.

        Args:
            entity_names (List[str]): List of entity names.

        Returns:
            str: XML-formatted string containing signature and type for each entity
        """
        # Prepare a Cypher query to retrieve signatures for the entities
        query = (
"""
// Start with the list of names to search for and create a row for each
UNWIND $entity_names AS entity_name

// Phase 1: Try to find a direct match for the entity by its own properties
OPTIONAL MATCH (e1:METHOD|FUNCTION|CLASS)
WHERE e1.name = entity_name OR e1.shortest_call_path = entity_name
WITH entity_name, collect(e1)[0] AS direct_match

// Phase 2: If no direct match was found, try the fallback search via the EXPOSES relationship
OPTIONAL MATCH ()-[r:EXPOSES]->(e2:METHOD|FUNCTION|CLASS)
WHERE direct_match IS NULL AND r.name = entity_name
WITH entity_name, direct_match, collect(e2)[0] AS exposed_match

// Combine the results from both phases. COALESCE gives us the first non-null entity found.
WITH entity_name, COALESCE(direct_match, exposed_match) AS found_entity

// Phase 3: If still no match, try parsing as Class.method
// This block will only execute if found_entity from phases 1 & 2 is NULL.
CALL apoc.when(
  found_entity IS NULL AND entity_name CONTAINS '.',
  // If TRUE, execute this subquery to find the method via its class
  '
    WITH entity_name

// 1. Collect all positions of the last dot
WITH entity_name,
     apoc.text.indexesOf(entity_name, ".") AS ids

// 2. Determine the last index (if none found, default to -1)
WITH entity_name, ids,
     CASE
       WHEN size(ids) = 0 THEN -1
       ELSE ids[size(ids) - 1]
     END AS lastDot

// 3. Split into class_path and method_name based on that
WITH entity_name, lastDot,
     substring(entity_name, 0, lastDot) AS class_path,
     substring(entity_name, lastDot + 1) AS method_name

// 4. Try to find the class node by direct or exposed match
OPTIONAL MATCH (c1:CLASS)
WHERE c1.name = class_path OR c1.shortest_call_path = class_path
WITH entity_name, class_path, method_name, collect(c1)[0] AS class_direct_match

OPTIONAL MATCH ()-[r:EXPOSES]->(c2:CLASS)
WHERE class_direct_match IS NULL AND r.name = class_path
WITH entity_name, method_name, class_direct_match, collect(c2)[0] AS class_exposed_match

WITH entity_name, method_name,
     COALESCE(class_direct_match, class_exposed_match) AS found_class

// 5. Finally, find the method under that class
OPTIONAL MATCH (found_class)-[:HAS_METHOD]->(method:METHOD {__name__: method_name})
RETURN method AS method_match;
  ',
  // If FALSE, return null
  'RETURN NULL AS method_match',
  // Parameters for the subquery
  {entity_name: entity_name}
) YIELD value

// Combine results from all phases.
WITH entity_name, COALESCE(found_entity, value.method_match) AS final_entity

// Phase 4: Get the signature, with special handling for CLASS nodes.
// If the final_entity is a CLASS, we OPTIONALLY look for its `__init__` method.
OPTIONAL MATCH (final_entity)-[:HAS_METHOD]->(init:METHOD {__name__: "__init__"})
WHERE "CLASS" IN labels(final_entity)

// Final Projection: Build the result map using a CASE statement for conditional logic.
RETURN apoc.map.fromPairs(
  collect([
    entity_name,
    CASE
      WHEN final_entity IS NULL THEN NULL
      ELSE {
        signature: CASE
          // If a class was found, use the __init__ method's signature.
          // If the class has no __init__, `init.signature` will correctly be null.
          WHEN "CLASS" IN labels(final_entity) THEN init.signature
          // For METHOD, FUNCTION, use the entity's own signature.
          ELSE final_entity.signature
        END,
        type: [label IN labels(final_entity) WHERE label IN ["CLASS", "FUNCTION", "METHOD"]][0]
      }
    END
  ])
) AS signatures
"""
        )

        signatures_result = self.structured_query(query, {"entity_names": entity_names})[0]["signatures"]
        
        # Convert the result to a list format for XML
        signatures = []
        for entity_name in entity_names:
            entity_data = signatures_result.get(entity_name) if signatures_result else None
            if entity_data:
                signatures.append({
                    "entity_name": entity_name,
                    "signature": entity_data.get("signature", ""),
                    "type": entity_data.get("type", ""),
                    "found": True
                })
            else:
                signatures.append({
                    "entity_name": entity_name,
                    "signature": "",
                    "type": "",
                    "found": False
                })
        
        data = {
            "signatures": signatures,
            "system_message": f"Retrieved signatures for {len(entity_names)} entity/entities."
        }
        return _dict_to_xml_string(data, "get_signatures_response")

    def list_libraries(
            self,
            search_terms: Optional[List[str]] = None,
        ) -> str:
        """
        Get a list of all ROOT_MODULE entities (libraries) in the knowledge graph.
        
        Args:
            search_terms (List[str], optional): Search terms to filter libraries by name, using case-insensitive partial matching. Defaults to None.

        Returns:
            str: XML-formatted string containing:
                - libraries: A list of library objects, each containing:
                    - name (str): The name of the library/root module
                    - versions (List[str]): List of version labels available for the library
                - system_message (str): Informational message about the results
        """
        # Build the query with optional filtering and version aggregation
        query = """
        MATCH (lib:ROOT_MODULE)
        """
        
        query_params = {}
        
        # Add WHERE clause if search_terms are provided
        if search_terms:
            # Create case-insensitive partial match patterns for each search term
            search_patterns = [f"(?i).*{_escape_regex_special_chars(term)}.*" for term in search_terms]
            # Combine patterns with OR
            search_pattern = "|".join(search_patterns)
            query += """
        WHERE lib.name =~ $search_pattern
            """
            query_params["search_pattern"] = search_pattern
        
        # Group by library name and collect all versions across nodes
        query += """
        WITH lib.name AS name,
             collect(DISTINCT [label IN labels(lib) WHERE label STARTS WITH 'version_']) AS all_version_lists
        WITH name,
             reduce(versions = [], version_list IN all_version_lists | versions + version_list) AS all_versions
        RETURN name,
               apoc.coll.toSet(all_versions) AS versions
        ORDER BY name
        """
        
        try:
            results = self.structured_query(query, query_params)
            
            # Clean up version labels (remove 'version_' prefix and convert underscores back)
            for result in results:
                result['versions'] = sorted([
                    v.replace('version_', '').replace('_', '.')
                    for v in result.get('versions', [])
                ])
            
            filtered_msg = " matching search terms" if search_terms else ""
            data = {
                "libraries": results,
                "system_message": f"Found {len(results)} indexed libraries{filtered_msg} in the knowledge graph."
            }
            return _dict_to_xml_string(data, "list_libraries_response")
        except Exception as e:
            logging.error(f"Error listing libraries: {e}")
            data = {
                "libraries": [],
                "system_message": f"Error retrieving libraries: {str(e)}"
            }
            return _dict_to_xml_string(data, "list_libraries_response")

    def search_definitions(
        self,
        parent_entity_name: str,
        search_terms: List[str],
        page: int = 1,
        page_size: int = 10
    ) -> str:
        """
        Search for code definitions (functions, classes, methods) within a provided entity.
        Supports exact matches, partial matches, and pagination.
        
        Args:
            parent_entity_name (str): Name of the parent entity to search within
            search_terms (List[str]): List of definition names to search for
            page (int): Page number starting from 1. Default is 1.
            page_size (int): Number of results per page. Default is 10.
        
        Returns:
            str: XML-formatted string containing:
                - definitions: Array of matching code definitions, each containing:
                    - fqn (str): Fully qualified name (entity.name)
                    - api_path (str): API call path (entity.shortest_call_path)
                    - definition_type (str): Primary type of definition (e.g., "FUNCTION", "CLASS", "METHOD")
                    - all_labels (List[str]): All labels associated with the entity
                    - signature (str): Code signature (for CLASS, shows __init__ signature if available)
                - next_page (int | None): Next page number if more results are available
                - current_page (int): Current page number
                - total_results (int): Total number of matching results
                - system_message (str): Informational message about the search results
        """
        # Calculate skip value for pagination
        skip = (page - 1) * page_size
        
        # Process search terms: escape regex special chars and extract partial terms
        all_search_patterns = []
        for term in search_terms:
            # Get partial terms (e.g., 'mod.mod2.entity' -> ['mod.mod2.entity', 'mod2.entity', 'entity'])
            partial_terms = _extract_partial_terms(term)
            
            for partial in partial_terms:
                # Escape regex special characters (dots, etc.)
                escaped_term = _escape_regex_special_chars(partial)
                # Build case-insensitive pattern that matches the term anywhere in __name__
                all_search_patterns.append(f"(?i).*{escaped_term}.*")
        
        # Combine all patterns with OR (|)
        search_pattern = "|".join(all_search_patterns)
        
        query = """
        // Find the parent entity
        MATCH (parent {name: $parent_entity_name})
        
        // Find all children recursively using variable-length path
        MATCH (parent)-[:HAS_SUBMODULE|HAS_CLASS|HAS_METHOD|HAS_FUNCTION*]->(child)
        WHERE child.__name__ =~ $search_pattern
        
        // Get distinct children to avoid duplicates from multiple paths
        WITH DISTINCT child
        
        // For CLASS entities, optionally get their __init__ method signature
        OPTIONAL MATCH (child)-[:HAS_METHOD]->(init:METHOD {__name__: "__init__"})
        WHERE "CLASS" IN labels(child)
        
        // Build complete result set with all data
        WITH child, init,
            child.name AS fqn,
            child.shortest_call_path AS api_path,
            [label IN labels(child) WHERE label IN ['FUNCTION', 'CLASS', 'METHOD', 'MODULE', 'ROOT_MODULE']][0] AS definition_type,
            labels(child) AS all_labels,
            CASE
                // For CLASS, use __init__ signature if available
                WHEN "CLASS" IN labels(child) AND init IS NOT NULL THEN init.signature
                // For others, use their own signature
                WHEN child.signature IS NOT NULL THEN child.signature
                ELSE child.__name__
            END AS signature
        ORDER BY fqn
        
        // Get total count before pagination
        WITH collect({
            fqn: fqn,
            api_path: api_path,
            definition_type: definition_type,
            all_labels: all_labels,
            signature: signature
        }) AS all_results
        
        WITH all_results, size(all_results) AS total_count
        
        // Apply pagination at the end
        UNWIND all_results AS result
        WITH result, total_count
        SKIP $skip
        LIMIT $page_size
        
        // Return paginated results with total count
        RETURN 
            result.fqn AS fqn,
            result.api_path AS api_path,
            result.definition_type AS definition_type,
            result.all_labels AS all_labels,
            result.signature AS signature,
            total_count
        """
        
        query_params = {
            "parent_entity_name": parent_entity_name,
            "search_pattern": search_pattern,
            "skip": skip,
            "page_size": page_size
        }
        
        try:
            results = self.structured_query(query, query_params)
            
            if not results:
                data = {
                    "definitions": [],
                    "next_page": None,
                    "current_page": page,
                    "total_results": 0,
                    "system_message": f"No definitions found matching search terms within '{parent_entity_name}'. "
                                     f"Verify that the parent entity name is correct and that definitions exist."
                }
                return _dict_to_xml_string(data, "search_definitions_response")
            
            total_results = results[0].get("total_count", 0) if results else 0
            definitions = []
            
            for result in results:
                definitions.append({
                    "fqn": result["fqn"],
                    "api_path": result["api_path"],
                    "definition_type": result["definition_type"],
                    "all_labels": result["all_labels"],
                    "signature": result["signature"]
                })
            
            # Calculate if there's a next page
            total_pages = (total_results + page_size - 1) // page_size
            next_page = page + 1 if page < total_pages else None
            
            system_message = f"Found {total_results} definition(s) matching search terms within '{parent_entity_name}'. "
            system_message += f"Showing page {page} of {total_pages}."
            if next_page:
                system_message += f" Use page={next_page} to see more results."
            
            data = {
                "definitions": definitions,
                "next_page": next_page,
                "current_page": page,
                "total_results": total_results,
                "system_message": system_message
            }
            return _dict_to_xml_string(data, "search_definitions_response")
            
        except Exception as e:
            logging.error(f"Error searching definitions: {e}")
            data = {
                "definitions": [],
                "next_page": None,
                "current_page": page,
                "total_results": 0,
                "system_message": f"Error searching definitions: {str(e)}"
            }
            return _dict_to_xml_string(data, "search_definitions_response")
        
    def get_definitions(self, entity_names: List[str]) -> str:
        """
        Get definition information for one or more entities.

        Args:
            entity_names (List[str]): List of entity names (can be a single entity or multiple).

        Returns:
            str: XML-formatted string containing:
                - definitions: List of entity definitions, each containing:
                    - query_name (str): The queried entity name
                    - fqn (str): Fully qualified name
                    - docstring (str): Entity docstring
                    - all_labels (List[str]): All labels
                    - api_path (str): API call path
                    - signature (str): Entity signature
                    - resolved_sig (str): Resolved signature from type hints
                    - found (bool): Whether the entity was found
                - system_message (str): Informational message
        """
        get_definitions_query = """
            UNWIND $entity_names AS entity_name
            
            // Try to match the entity by name
            OPTIONAL MATCH (end {name: entity_name})
            OPTIONAL MATCH (end:CLASS)-[:HAS_METHOD]->(init {__name__: "__init__"})
            WHERE "CLASS" IN labels(end)
            
            WITH entity_name, end, init
            RETURN 
                entity_name AS query_name,
                CASE WHEN end IS NOT NULL THEN end.name ELSE "" END AS fqn,
                CASE WHEN end IS NOT NULL THEN end.doc ELSE "" END AS docstring,
                CASE WHEN end IS NOT NULL THEN labels(end) ELSE [] END AS all_labels,
                CASE WHEN end IS NOT NULL THEN end.shortest_call_path ELSE "" END AS api_path,
                CASE 
                    WHEN end IS NULL THEN ""
                    WHEN "CLASS" IN labels(end) AND init IS NOT NULL THEN init.signature
                    ELSE end.signature
                END AS signature,
                CASE 
                    WHEN end IS NULL THEN ""
                    WHEN "CLASS" IN labels(end) AND init IS NOT NULL THEN init.resolved_signature
                    ELSE end.resolved_signature
                END AS resolved_sig,
                end IS NOT NULL AS found
        """
        
        results = self.structured_query(get_definitions_query, {"entity_names": entity_names})
        
        found_count = sum(1 for r in results if r['found'])
        data = {
            "definitions": results,
            "system_message": f"Retrieved {len(entity_names)} definition(s). Found {found_count} entities."
        }
        return _dict_to_xml_string(data, "get_definitions_response")

    def library_map(
        self,
        library_name: str,
        version: str,
        depth: int = 0
    ) -> str:
        """
        Generate a hierarchical map of a library showing all entities in nested form.
        
        Args:
            library_name (str): Name of the ROOT_MODULE (library) to map
            version (str): Version of the library (e.g., "4.28" or "version_4_28")
            depth (int): Directory/entity traversal depth. 0 = full depth (default), >0 = limited depth.
        
        Returns:
            str: XML-formatted string containing:
                - library_name (str): Name of the library
                - version (str): Version being mapped
                - depth (int): Depth used for traversal (0 = full)
                - entities: Nested hierarchy of all entities, each containing:
                    - all_labels (List[str]): All labels associated with the entity
                    - fqn (str): Fully qualified name (entity.name)
                    - api_path (str): API call path (entity.shortest_call_path)
                    - children (List): Nested child entities
                - system_message (str): Informational message about the results
        """
        # Normalize version string
        if version.startswith("version_"):
            version_label = version
            version_display = version.replace("version_", "").replace("_", ".")
        else:
            version_display = version
            version_label = f"version_{version.replace('.', '_').replace(':', '_').replace('-', '_')}"
        
        # Handle depth: 0 means full depth
        actual_depth = 999 if depth == 0 else depth
        
        try:
            # Check if library exists with the specified version
            check_query = """
            MATCH (lib:ROOT_MODULE {name: $library_name})
            WHERE $version_label IN labels(lib)
            RETURN lib.name AS name
            """
            
            check_result = self.structured_query(check_query, {
                "library_name": library_name,
                "version_label": version_label
            })
            
            if not check_result:
                data = {
                    "library_name": library_name,
                    "version": version_display,
                    "depth": depth,
                    "entities": [],
                    "system_message": f"Library '{library_name}' with version '{version_display}' not found in the knowledge graph."
                }
                return _dict_to_xml_string(data, "library_map_response")
            
            # Fetch all entities in hierarchical order
            hierarchy_query = """
            MATCH path = (lib:ROOT_MODULE {name: $library_name})-[:HAS_SUBMODULE|HAS_CLASS|HAS_METHOD|HAS_FUNCTION*0..]->(entity)
            WHERE $version_label IN labels(entity)
            AND length(path) <= $actual_depth
            WITH entity, path, length(path) AS depth_level,
                 [node in nodes(path) | node.name] AS path_names
            ORDER BY path_names, entity.__name__
            RETURN 
                entity.name AS fqn,
                entity.shortest_call_path AS api_path,
                labels(entity) AS all_labels,
                depth_level,
                path_names
            """
            
            results = self.structured_query(hierarchy_query, {
                "library_name": library_name,
                "version_label": version_label,
                "actual_depth": actual_depth
            })
            
            # Build nested hierarchy
            def build_hierarchy(results):
                """Convert flat list to nested hierarchy based on path_names"""
                root_entities = []
                entity_map = {}
                
                for result in results:
                    entity_data = {
                        "all_labels": result["all_labels"],
                        "fqn": result["fqn"],
                        "api_path": result["api_path"],
                        "children": []
                    }
                    
                    fqn = result["fqn"]
                    entity_map[fqn] = entity_data
                    
                    # Determine parent
                    path_names = result["path_names"]
                    if len(path_names) == 1:
                        # Root level entity
                        root_entities.append(entity_data)
                    else:
                        # Find parent by checking if any entity has this one in its path
                        parent_fqn = path_names[-2]
                        if parent_fqn in entity_map:
                            entity_map[parent_fqn]["children"].append(entity_data)
                
                return root_entities
            
            entities = build_hierarchy(results)
            
            data = {
                "library_name": library_name,
                "version": version_display,
                "depth": depth,
                "entities": entities,
                "system_message": f"Found {len(results)} entities in '{library_name}' version {version_display}."
            }
            return _dict_to_xml_string(data, "library_map_response")
            
        except Exception as e:
            logging.error(f"Error generating library map: {e}")
            data = {
                "library_name": library_name,
                "version": version_display,
                "depth": depth,
                "entities": [],
                "system_message": f"Error generating library map: {str(e)}"
            }
            return _dict_to_xml_string(data, "library_map_response")
        
    def get_version_diff(self, parent_entity: str, old_version: str, new_version: str) -> str:
        """
        Get the version difference between two versions of an entity's hierarchy, in hierarchical form with git-style diff.

        Args:
            parent_entity (str): The entity, under which the versions are to be compared for itself and its children.
            old_version (str): The old version identifier (e.g., "4.28" or "version_4_28").
            new_version (str): The new version identifier (e.g., "4.29" or "version_4_29").

        Returns:
            str: XML-formatted string containing:
                - entity_name (str): Name of the parent entity
                - old_version (str): The old version identifier
                - new_version (str): The new version identifier
                - diff (str): The git-style diff between the two versions (only for entities with signatures)
                - entities: Nested hierarchy of entities with their status and changes
                - summary: Statistics about changes
                - system_message (str): Informational message about the results
        """
        try:
            # Normalize version strings to match label format
            def normalize_version(version):
                if version.startswith("version_"):
                    return version, version.replace("version_", "").replace("_", ".")
                else:
                    normalized = f"version_{version.replace('.', '_').replace(':', '_').replace('-', '_')}"
                    return normalized, version
            
            old_version_label, old_version_display = normalize_version(old_version)
            new_version_label, new_version_display = normalize_version(new_version)
            
            # Single optimized query that validates and retrieves all data
            query = """
            // Try to find the parent entity
            OPTIONAL MATCH (parent {name: $parent_entity})
            
            // Check if parent exists and has the required version labels
            WITH parent,
                 parent IS NOT NULL AS parent_exists,
                 CASE WHEN parent IS NOT NULL THEN $old_version_label IN labels(parent) ELSE false END AS has_old_version,
                 CASE WHEN parent IS NOT NULL THEN $new_version_label IN labels(parent) ELSE false END AS has_new_version
            
            // Early return metadata if parent doesn't exist or versions are missing
            WITH parent, parent_exists, has_old_version, has_new_version,
                 CASE 
                     WHEN NOT parent_exists THEN 'parent_not_found'
                     WHEN NOT has_old_version AND NOT has_new_version THEN 'neither_version_found'
                     WHEN NOT has_old_version THEN 'old_version_not_found'
                     WHEN NOT has_new_version THEN 'new_version_not_found'
                     ELSE 'valid'
                 END AS validation_status
            
            // If validation passes, find all descendants with old version label
            CALL {
                WITH parent, validation_status, $old_version_label AS old_label
                OPTIONAL MATCH path = (parent)-[:HAS_SUBMODULE|HAS_CLASS|HAS_METHOD|HAS_FUNCTION*0..]->(entity)
                WHERE validation_status = 'valid' AND old_label IN labels(entity)
                RETURN entity, path, true AS has_old, false AS has_new
            }
            
            UNION ALL
            
            // Find all descendants with new version label
            CALL {
                WITH parent, validation_status, $new_version_label AS new_label
                OPTIONAL MATCH path = (parent)-[:HAS_SUBMODULE|HAS_CLASS|HAS_METHOD|HAS_FUNCTION*0..]->(entity)
                WHERE validation_status = 'valid' AND new_label IN labels(entity)
                RETURN entity, path, false AS has_old, true AS has_new
            }
            
            // Return validation status and entity data (if valid)
            WITH validation_status, entity, path, has_old, has_new,
                 CASE WHEN entity IS NOT NULL THEN entity.name ELSE null END AS fqn,
                 CASE WHEN entity IS NOT NULL THEN entity.__name__ ELSE null END AS simple_name,
                 CASE WHEN entity IS NOT NULL THEN entity.shortest_call_path ELSE null END AS api_path,
                 CASE WHEN entity IS NOT NULL THEN labels(entity) ELSE [] END AS all_labels,
                 CASE WHEN entity IS NOT NULL THEN [label IN labels(entity) WHERE label IN ['ROOT_MODULE', 'MODULE', 'CLASS', 'FUNCTION', 'METHOD']][0] ELSE null END AS type,
                 CASE WHEN entity IS NOT NULL THEN entity.signature ELSE null END AS signature,
                 CASE WHEN path IS NOT NULL THEN [node in nodes(path) | node.name] ELSE [] END AS path_names
            
            // Collect all results and merge entities that appear in both versions
            WITH validation_status, 
                 fqn,
                 simple_name,
                 api_path,
                 all_labels,
                 type,
                 signature,
                 max(has_old) AS has_old_version,
                 max(has_new) AS has_new_version,
                 path_names
            WHERE fqn IS NOT NULL
            
            // Get signatures for both versions (if different)
            WITH validation_status, fqn, simple_name, api_path, all_labels, type, has_old_version, has_new_version, path_names,
                 CASE WHEN has_old_version THEN signature ELSE null END AS old_signature,
                 CASE WHEN has_new_version THEN signature ELSE null END AS new_signature
            
            // Build entity data structure
            WITH validation_status,
                 collect({
                     fqn: fqn,
                     simple_name: simple_name,
                     api_path: api_path,
                     all_labels: all_labels,
                     type: type,
                     old_signature: old_signature,
                     new_signature: new_signature,
                     has_old_version: has_old_version,
                     has_new_version: has_new_version,
                     path_names: path_names
                 }) AS valid_entities
            
            // Sort the entities
            UNWIND CASE WHEN size(valid_entities) > 0 THEN valid_entities ELSE [null] END AS entity_data
            WITH validation_status, entity_data
            ORDER BY entity_data.path_names, entity_data.fqn
            
            RETURN validation_status, 
                   collect(entity_data) AS results
            """
            
            query_result = self.structured_query(query, {
                "parent_entity": parent_entity,
                "old_version_label": old_version_label,
                "new_version_label": new_version_label
            })[0]
            
            validation_status = query_result["validation_status"]
            results = [r for r in query_result["results"] if r is not None]
            
            # Handle validation errors
            if validation_status != 'valid':
                error_messages = {
                    'parent_not_found': f"Parent entity '{parent_entity}' not found in the knowledge graph.",
                    'neither_version_found': f"Neither version '{old_version_display}' nor '{new_version_display}' found for entity '{parent_entity}'.",
                    'old_version_not_found': f"Version '{old_version_display}' not found for entity '{parent_entity}'.",
                    'new_version_not_found': f"Version '{new_version_display}' not found for entity '{parent_entity}'."
                }
                
                data = {
                    "entity_name": parent_entity,
                    "old_version": old_version_display,
                    "new_version": new_version_display,
                    "diff": "",
                    "entities": [],
                    "summary": {
                        "added": 0,
                        "removed": 0,
                        "modified": 0,
                        "unchanged": 0
                    },
                    "system_message": error_messages.get(validation_status, "Unknown validation error.")
                }
                return _dict_to_xml_string(data, "get_version_diff_response")
            
            if not results:
                data = {
                    "entity_name": parent_entity,
                    "old_version": old_version_display,
                    "new_version": new_version_display,
                    "diff": "",
                    "entities": [],
                    "summary": {
                        "added": 0,
                        "removed": 0,
                        "modified": 0,
                        "unchanged": 0
                    },
                    "system_message": f"No entities found under '{parent_entity}' with versions '{old_version_display}' or '{new_version_display}'."
                }
                return _dict_to_xml_string(data, "get_version_diff_response")
            
            # Generate git-style diff (only for entities with signatures that changed)
            diff_lines = []
            diff_lines.append(f"--- {parent_entity} @ {old_version_display}")
            diff_lines.append(f"+++ {parent_entity} @ {new_version_display}")
            diff_lines.append("")
            
            added_count = 0
            removed_count = 0
            modified_count = 0
            unchanged_count = 0
            
            # Process entities and determine their status
            entity_map = {}
            
            for result in results:
                fqn = result["fqn"]
                has_old = result.get("has_old_version", False)
                has_new = result.get("has_new_version", False)
                old_sig = result.get("old_signature")
                new_sig = result.get("new_signature")
                entity_type = result["type"]
                api_path = result["api_path"]
                all_labels = result["all_labels"]
                path_names = result["path_names"]
                
                # Determine status
                if has_old and has_new:
                    if old_sig != new_sig:
                        status = "modified"
                        modified_count += 1
                        # Add to diff if signatures exist and changed
                        if old_sig and new_sig:
                            diff_lines.append(f"@@ {entity_type}: {api_path} @@")
                            diff_lines.append(f"- {old_sig}")
                            diff_lines.append(f"+ {new_sig}")
                            diff_lines.append("")
                    else:
                        status = "unchanged"
                        unchanged_count += 1
                elif has_new and not has_old:
                    status = "added"
                    added_count += 1
                    # Add to diff if signature exists
                    if new_sig:
                        diff_lines.append(f"@@ {entity_type}: {api_path} @@")
                        diff_lines.append(f"+ {new_sig}")
                        diff_lines.append("")
                elif has_old and not has_new:
                    status = "removed"
                    removed_count += 1
                    # Add to diff if signature exists
                    if old_sig:
                        diff_lines.append(f"@@ {entity_type}: {api_path} @@")
                        diff_lines.append(f"- {old_sig}")
                        diff_lines.append("")
                else:
                    continue
                
                # Build entity entry
                entity_entry = {
                    "fqn": fqn,
                    "api_path": api_path,
                    "all_labels": all_labels,
                    "status": status,
                    "children": []
                }
                
                if status == "modified":
                    entity_entry["old_signature"] = old_sig
                    entity_entry["new_signature"] = new_sig
                elif status == "added":
                    entity_entry["signature"] = new_sig
                elif status == "removed":
                    entity_entry["signature"] = old_sig
                else:  # unchanged
                    entity_entry["signature"] = new_sig
                
                entity_map[fqn] = {
                    "data": entity_entry,
                    "path_names": path_names
                }
            
            # Build nested hierarchy
            def build_diff_hierarchy(entity_map):
                """Convert flat entity map to nested hierarchy"""
                root_entities = []
                
                for fqn, info in entity_map.items():
                    entity_data = info["data"]
                    path_names = info["path_names"]
                    
                    if len(path_names) == 1:
                        # Root level entity
                        root_entities.append(entity_data)
                    else:
                        # Find parent
                        parent_fqn = path_names[-2]
                        if parent_fqn in entity_map:
                            entity_map[parent_fqn]["data"]["children"].append(entity_data)
                
                return root_entities
            
            entities_hierarchy = build_diff_hierarchy(entity_map)
            
            # Build summary message
            summary_parts = []
            if added_count > 0:
                summary_parts.append(f"{added_count} added")
            if removed_count > 0:
                summary_parts.append(f"{removed_count} removed")
            if modified_count > 0:
                summary_parts.append(f"{modified_count} modified")
            if unchanged_count > 0:
                summary_parts.append(f"{unchanged_count} unchanged")
            
            summary = ", ".join(summary_parts) if summary_parts else "no changes"
            system_message = f"Version diff generated for '{parent_entity}': {summary}."
            
            diff_text = "\n".join(diff_lines)
            
            data = {
                "entity_name": parent_entity,
                "old_version": old_version_display,
                "new_version": new_version_display,
                "diff": diff_text,
                "entities": entities_hierarchy,
                "summary": {
                    "added": added_count,
                    "removed": removed_count,
                    "modified": modified_count,
                    "unchanged": unchanged_count
                },
                "system_message": system_message
            }
            return _dict_to_xml_string(data, "get_version_diff_response")
            
        except Exception as e:
            logging.error(f"Error generating version diff: {e}")
            data = {
                "entity_name": parent_entity,
                "old_version": old_version_display if 'old_version_display' in locals() else old_version,
                "new_version": new_version_display if 'new_version_display' in locals() else new_version,
                "diff": "",
                "entities": [],
                "summary": {
                    "added": 0,
                    "removed": 0,
                    "modified": 0,
                    "unchanged": 0
                },
                "system_message": f"Error generating version diff: {str(e)}"
            }
            return _dict_to_xml_string(data, "get_version_diff_response")