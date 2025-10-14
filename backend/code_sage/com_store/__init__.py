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
from ..reflex import Entity, Relationship
import logging
import neo4j
import hashlib
import xml.etree.ElementTree as ET
from xml.dom import minidom

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
            MATCH (parent {name: $parent_name})-[:HAS_SUBMODULE|HAS_CLASS|HAS_METHOD|HAS_FUNCTION|EXPOSES]->(child)
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
            from\_ (str): "ROOT_MODULE" or "CHILDREN", indicating which list to retrieve from.
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
        # Convert Entity to EntityNode and Relationship to Relation with versioning + overload support
        entity_nodes: List[EntityNode] = []
        # Map by Python object identity to support multiple entities with the same name (overloads, versions)
        entities_to_entity_nodes: Dict[int, EntityNode] = {}
        # Capture extra labels and version info to apply post-upsert
        post_rows: List[Dict[str, Any]] = []

        def _extract_version(labels: List[str]) -> Optional[str]:
            for l in labels or []:
                if isinstance(l, str) and l.startswith("version:"):
                    return l.split("version:", 1)[1] or None
            return None

        def _content_hash(props: Dict[str, Any]) -> str:
            # Use source + signature + resolved_signature + decorators as a stable content signature
            src = str(props.get("source", ""))
            sig = str(props.get("signature", ""))
            rsig = str(props.get("resolved_signature", ""))
            dec = ",".join(props.get("decorators", []) or [])
            h = hashlib.sha256()
            h.update(src.encode("utf-8", errors="ignore"))
            h.update(b"|::|")
            h.update(sig.encode("utf-8", errors="ignore"))
            h.update(b"|::|")
            h.update(rsig.encode("utf-8", errors="ignore"))
            h.update(b"|::|")
            h.update(dec.encode("utf-8", errors="ignore"))
            return h.hexdigest()

        def _build_id(e: Entity, content_hash: str) -> str:
            # Stable ID based on path and content. This ensures: same content across versions -> same node.
            # Different content (new version with changes) -> new node.
            # Keep it compact for readability.
            return f"{e.name}|{content_hash[:12]}"

        def _extra_labels(labels: List[str]) -> List[str]:
            # All labels except the primary one and version:* entries become extra Neo4j labels
            if not labels:
                return []
            primary = labels[0]
            extras: List[str] = []
            for l in labels[1:]:
                if isinstance(l, str) and not l.startswith("version:") and l != primary:
                    # Neo4j labels cannot contain colon; our extras do not, so safe.
                    extras.append(l)
            return list(dict.fromkeys(extras))  # de-dupe

        for entity in entities:
            version = _extract_version(getattr(entity, "labels", []) or [])
            c_hash = _content_hash(entity.properties or {})
            node_id = _build_id(entity, c_hash)

            # Attach helpful versioning properties on the node
            properties = dict(entity.properties or {})
            properties["content_hash"] = c_hash
            if version:
                # latest observed version for this ingestion
                properties["version"] = version

            entity_node = EntityNode(
                id=node_id,
                label=entity.label,
                name=entity.name,
                properties=properties,
            )
            entity_nodes.append(entity_node)
            entities_to_entity_nodes[id(entity)] = entity_node

            post_rows.append({
                "id": node_id,
                "version": version,
                "content_hash": c_hash,
                "extra_labels": _extra_labels(getattr(entity, "labels", []) or []),
            })

        # Convert incoming relationships using object-identity mapping
        rels: List[Relation] = []
        for r in relations:
            src_node = entities_to_entity_nodes.get(id(r.from_entity))
            tgt_node = entities_to_entity_nodes.get(id(r.to_entity))
            if not src_node or not tgt_node:
                # Skip relationships whose endpoints were filtered out for any reason
                continue
            rels.append(
                Relation(
                    label=r.label,
                    source_id=src_node.id,
                    target_id=tgt_node.id,
                    properties=r.properties,
                )
            )

        # Upsert nodes and relationships (MERGE semantics in underlying store)
        self.upsert_nodes(entity_nodes)
        self.upsert_relations(rels)

        # Post-process: add versions and extra labels safely on the merged nodes
        if post_rows:
            # Update versions set, version (last seen), and ensure content_hash is stored
            update_versions_query = """
            UNWIND $rows AS row
            MATCH (n {id: row.id})
            FOREACH (v IN CASE WHEN row.version IS NOT NULL THEN [row.version] ELSE [] END |
                SET n.versions = apoc.coll.toSet(coalesce(n.versions, []) + v)
                SET n.version = v
            )
            SET n.content_hash = row.content_hash
            RETURN count(n) AS updated
            """
            self.structured_query(update_versions_query, {"rows": post_rows})

            # Apply extra labels like OVERLOAD, OVERLOADED, PRIVATE, etc.
            add_labels_query = """
            UNWIND $rows AS row
            WITH row WHERE size(row.extra_labels) > 0
            MATCH (n {id: row.id})
            CALL apoc.create.addLabels(n, row.extra_labels)
            YIELD node
            RETURN count(node) AS labeled
            """
            self.structured_query(add_labels_query, {"rows": post_rows})

        # Embed the nodes if specified
        if embed_nodes:
            self._embed_nodes()

        # Add labels recursively
        self._handle_inherited_methods(module_name)

        # Add INHERITS and IMPORTS relations as properties to the respective nodes
        self._add_other_relations_as_properties(other_relations)

        # Process INHERITS and IMPORTS relations
        self._process_other_relations()

        # Set the shortest call paths for all nodes in the module
        self._set_shortest_call_paths(module_name)

    def _add_other_relations_as_properties(self, other_relations: Dict[str, List[Tuple]]):
        """
        Add INHERITS and IMPORTS relations as properties to the respective nodes.

        Args:
            other_relations (Dict[str, List[Tuple]]): Dictionary containing INHERITS and IMPORTS relations.
        """
        inherits_relations = other_relations.get("INHERITS", [])
        imports_relations = other_relations.get("IMPORTS", [])
        exposes_relations = other_relations.get("EXPOSES", [])
        add_inherits_query = (
            """
            UNWIND $inherits_relations AS rel
            MATCH (c:CLASS {name: rel[0]})
            SET c.INHERITS = apoc.coll.toSet(coalesce(c.INHERITS, []) + rel[1])
            """
        )
        add_imports_query = (
            """
            UNWIND $imports_relations AS rel
            MATCH (e {name: rel[0]})
            SET e.IMPORTS = apoc.coll.toSet(coalesce(e.IMPORTS, []) + rel[1])
            """
        )
        add_exposes_query = (
            """
            UNWIND $exposes_relations AS rel
            MATCH (m {name: rel[0]})
            SET m.EXPOSES = apoc.coll.toSet(coalesce(m.EXPOSES, []) + rel[1])
            """
        )
        self.structured_query(add_inherits_query, {"inherits_relations": inherits_relations})
        self.structured_query(add_imports_query, {"imports_relations": imports_relations})
        self.structured_query(add_exposes_query, {"exposes_relations": exposes_relations})

    def _process_other_relations(self):
        """
        Execute Cypher queries to create relations on existing nodes with INHERITS, IMPORTS and EXPOSES properties.
        Clear names from the INHERITS, IMPORTS and EXPOSES property arrays of the nodes if the relations could be created successfully.
        """
        process_inherits_query = (
            """
            MATCH (c:CLASS)
            WHERE c.INHERITS IS NOT NULL
            UNWIND c.INHERITS AS parent
            MATCH (p:CLASS {name: parent})
            MERGE (c)-[:INHERITS]->(p)
            WITH c, COLLECT(parent) AS parentNames
            SET c.INHERITS = [name IN c.INHERITS WHERE NOT name IN parentNames]
            SET c.NEW_INHERIT_RELS = parentNames
            """
        )
        process_imports_query = (
            """
            MATCH (e1)
            WHERE e1.IMPORTS IS NOT NULL
            UNWIND e1.IMPORTS AS importee
            MATCH (e2 {name: importee})
            MERGE (e1)-[:IMPORTS]->(e2)
            WITH e1, COLLECT(importee) AS importeeNames
            SET e1.IMPORTS = [name IN e1.IMPORTS WHERE NOT name IN importeeNames]
            """
        )
        process_exposes_query = (
            """
            MATCH (m:MODULE|ROOT_MODULE)
            WHERE m.EXPOSES IS NOT NULL
            UNWIND m.EXPOSES AS exposed
            MATCH (e {name: exposed})
            MERGE (m)-[:EXPOSES]->(e)
            WITH m, COLLECT(exposed) AS exposedNames
            SET m.EXPOSES = [name IN m.EXPOSES WHERE NOT name IN exposedNames]
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
        add_names_to_EXPOSES_rels_query = (
            """
            MATCH (n)-[r:EXPOSES]->(m)
            WHERE r.name IS NULL
            SET r.name = n.name + "." + m.__name__
            RETURN count(r)
            """
        )

        self.structured_query(process_inherits_query)
        self.structured_query(process_imports_query)
        self.structured_query(process_exposes_query)
        self.structured_query(cleanup_empty_INHERITS_query)
        self.structured_query(cleanup_empty_IMPORTS_query)
        self.structured_query(cleanup_empty_EXPOSES_query)
        self.structured_query(add_names_to_EXPOSES_rels_query)

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
MATCH (end:MODULE|FUNCTION|CLASS|METHOD)<-[:HAS_SUBMODULE|HAS_CLASS|HAS_METHOD|HAS_FUNCTION|EXPOSES*]-(root:ROOT_MODULE {name: $module_name})
WITH root, collect(end) AS endNodes

// Phase 2: Use spanningTree to get ordered paths from the root outwards (BFS).
CALL apoc.path.spanningTree(root, {
    relationshipFilter: 'HAS_SUBMODULE>|HAS_CLASS>|HAS_METHOD>|HAS_FUNCTION>|EXPOSES>',
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

    def _handle_inherited_methods(self, module_name: str):
        """
        Create HAS_METHOD relations for inherited methods for all classes in the specified module.

        Args:
            module_name (str): The name of the module.
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

    def _get_entity_info(self, entity_name: str) -> List[str]:
        """
        Get information about the entity.

        Args:
            entity_name (str): The name of the entity.

        Returns:
            List[str]: Information about the entity.
        """
        get_entity_info_query = (
            """
            // Try to match the entity by name
            MATCH (end {name: $entity_name})
            OPTIONAL MATCH (end:CLASS)-[:HAS_METHOD]->(init {__name__: "__init__"})
            WHERE "CLASS" IN labels(end)
            WITH end, init, NULL AS parent_class, NULL AS parent_init
            RETURN 
                end.name AS name, 
                end.__name__ AS __name__, 
                end.summary AS summary, 
                CASE 
                    WHEN "CLASS" IN labels(end) AND init IS NOT NULL THEN init.signature
                    ELSE end.signature
                END AS signature,
                end.llm_signature AS llm_signature, 
                end.shortest_call_path AS shortest_call_path,
                end.doc AS docstring,
                'entity' AS type
            UNION
            // If the entity is a method, also get its parent class's __init__ (if any)
            MATCH (m:METHOD {name: $entity_name})<-[:HAS_METHOD]-(cls:CLASS)
            OPTIONAL MATCH (cls)-[:HAS_METHOD]->(init:METHOD {__name__: "__init__"})
            RETURN 
                init.name AS name, 
                init.__name__ AS __name__, 
                init.summary AS summary, 
                init.signature AS signature,
                init.llm_signature AS llm_signature, 
                init.shortest_call_path AS shortest_call_path,
                init.doc AS docstring,
                'init' AS type
            """
        )
        result = self.structured_query(get_entity_info_query, {"entity_name": entity_name})
        # Filter out None results (e.g., if no __init__ exists)
        result = [r for r in result if r.get("name")]
        return result if result else []

    def _get_retrieved_entity_representation(self, retrieved_node: Dict) -> str:
        """
        Get the representation of the retrieved entity.

        Args:
            retrieved_node (Dict): The retrieved node.

        Returns:
            str: The representation of the retrieved entity.
        """
        entity_representation = f"""
*Name*: {retrieved_node["__name__"]}
*Full Path*: {retrieved_node["name"]}
*Shortest Call Path*: {retrieved_node["shortest_call_path"]}
*Signature*: {retrieved_node["signature"]}
*Signature identified by LLM as JSON (ONLY TO BE USED IF TYPES CANNOT BE ASCERTAINED FROM THE `Signature` FIELD)*: 
{retrieved_node["llm_signature"]}

*Summary of the Entity*:
```
{retrieved_node["summary"]}
```

*Docstring*:
```
{retrieved_node["docstring"]}
```
        """
        return entity_representation
    
    def get_entity_info(self, entity_name: str) -> str:
        """
        Get information about the entity.

        Args:
            entity_name (str): The name of the entity.

        Returns:
            str: XML-formatted string containing:
                - entity_data: Detailed information about the entity
                - system_message (str): Informational message
        """
        entity_node = self._get_entity_info(entity_name)
        if not entity_node:
            data = {
                "entity_data": [],
                "system_message": f"No entity found with the name: {entity_name}"
            }
            return _dict_to_xml_string(data, "get_entity_info_response")
        
        # If the list contains multiple entries, it is most likely a class' method and its __init__ method
        data = {
            "entity_data": entity_node,
            "system_message": f"Found {len(entity_node)} entity record(s) for '{entity_name}'." + 
                             (" (Includes method and its class __init__)" if len(entity_node) > 1 else "")
        }
        return _dict_to_xml_string(data, "get_entity_info_response")
    
    def get_info_for_entities(self, entity_names: List[str]) -> str:
        """
        Get information about multiple entities.

        Args:
            entity_names (List[str]): List of entity names.

        Returns:
            str: XML-formatted string containing:
                - entities: Information for each entity
                - system_message (str): Informational message
        """
        entities_data = []
        # Iterate through the list of entity names and retrieve their information
        for name in entity_names:
            entity_info_list = self._get_entity_info(name)
            entities_data.append({
                "entity_name": name,
                "records": entity_info_list if entity_info_list else [],
                "found": len(entity_info_list) > 0 if entity_info_list else False
            })

        data = {
            "entities": entities_data,
            "system_message": f"Retrieved information for {len(entity_names)} entity name(s)."
        }
        return _dict_to_xml_string(data, "get_info_for_entities_response")
    
    def _fts_full_path_name(self, name: str) -> str:
        """
        Perform a full-text search for the full path name of the entity.

        Args:
            name (str): The name of the entity.

        Returns:
            str: The full path name of the entity if found, otherwise an empty string.
        """
        processed_name = name.replace(".", ".*\.")
        name_till_dotunderscore = processed_name
        if ".*\._" in name_till_dotunderscore:
            name_till_dotunderscore = name_till_dotunderscore.split(".*\._")[0] + ".*"

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

    def list_libraries(self) -> str:
        """
        Get a list of all ROOT_MODULE entities (libraries) in the knowledge graph.
        
        Returns:
            str: XML-formatted string containing:
                - libraries: A list of library objects, each containing:
                    - name (str): The name of the library/root module
                    - summary (str): Summary description of the library
                    - source (str): Source file path
                - system_message (str): Informational message about the results
        """
        query = """
        MATCH (lib:ROOT_MODULE)
        RETURN lib.name AS name, 
               lib.summary AS summary, 
               lib.source AS source
        ORDER BY lib.name
        """
        
        try:
            results = self.structured_query(query)
            
            data = {
                "libraries": results,
                "system_message": f"Found {len(results)} indexed libraries in the knowledge graph."
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
                    - name (str): The name of the definition
                    - fqn (str): Fully qualified name of the definition
                    - definition_type (str): Type of definition (e.g., "FUNCTION", "CLASS", "METHOD")
                    - context (str): Code signature (for CLASS, shows __init__ signature if available)
                - next_page (int | None): Next page number if more results are available
                - current_page (int): Current page number
                - total_results (int): Total number of matching results
                - system_message (str): Informational message about the search results
        """
        # Calculate skip value for pagination
        skip = (page - 1) * page_size
        
        # Build the search pattern for case-insensitive partial matching
        search_pattern = "|".join([f"(?i).*{term}.*" for term in search_terms])
        
        query = """
        // Find the parent entity
        MATCH (parent {name: $parent_entity_name})
        
        // Find all children recursively
        MATCH (parent)-[:HAS_SUBMODULE|HAS_CLASS|HAS_METHOD|HAS_FUNCTION|EXPOSES*]->(child)
        WHERE child.__name__ =~ $search_pattern
        
        // Get total count
        WITH collect(child) AS all_children
        WITH all_children, size(all_children) AS total_count
        
        // Unwind for pagination
        UNWIND all_children AS child
        
        // For CLASS entities, optionally get their __init__ method signature
        OPTIONAL MATCH (child)-[:HAS_METHOD]->(init:METHOD {__name__: "__init__"})
        WHERE "CLASS" IN labels(child)
        
        // Apply pagination
        WITH child, init, total_count
        ORDER BY child.name
        SKIP $skip
        LIMIT $page_size
        
        // Return results with metadata
        RETURN 
            child.name AS name,
            child.shortest_call_path AS fqn,
            [label IN labels(child) WHERE label IN ['FUNCTION', 'CLASS', 'METHOD', 'MODULE']][0] AS definition_type,
            CASE
                // For CLASS, use __init__ signature if available
                WHEN "CLASS" IN labels(child) AND init IS NOT NULL THEN init.signature
                // For others, use their own signature
                WHEN child.signature IS NOT NULL THEN child.signature
                ELSE child.__name__
            END AS context,
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
                    "name": result["name"],
                    "fqn": result["fqn"],
                    "definition_type": result["definition_type"],
                    "context": result["context"]
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

    def library_map(
        self,
        library_name: str,
        depth: int = 2,
        show_structure: bool = True,
        show_definitions: bool = True,
        page: int = 1,
        page_size: int = 50
    ) -> str:
        """
        Generate a compact, API-style map of a library segment showing structure and definitions.
        
        Args:
            library_name (str): Name of the ROOT_MODULE (library) to map
            relative_paths (List[str], optional): Specific paths within the library to focus on.
                                                  If None, maps entire library.
            depth (int): Directory/entity traversal depth. 0 = full depth, 1-3 = limited depth. Default is 2.
            show_structure (bool): Include the structure tree. Default is True.
            show_definitions (bool): Include definitions. Default is True.
            page (int): Page number for pagination. Default is 1.
            page_size (int): Max definitions per page. Default is 50.
        
        Returns:
            str: XML-formatted string containing:
                - library_name (str): Name of the library
                - depth (int): Depth used for traversal (0 = full)
                - structure (str): ASCII tree representation of the library structure
                - definitions: List of definitions found, each containing:
                    - path (str): Path to the entity
                    - name (str): Name of the entity
                    - type (str): Type of definition
                    - location (str): Line range
                    - signature (str): Function/method signature
                    - summary (str): Brief description
                - next_page (int | None): Next page number if more results are available
                - total_definitions (int): Total number of definitions found
                - system_message (str): Informational message about the results
        """
        # Handle depth: 0 means full depth, otherwise clamp between 1 and 3
        if depth == 0:
            # Use a very large number to represent "unlimited" depth
            actual_depth = 999
            depth_display = 0
        else:
            actual_depth = max(1, min(3, depth))
            depth_display = actual_depth
        skip = (page - 1) * page_size
        
        structure_tree = ""
        definitions = []
        total_definitions = 0
        
        try:
            # Build structure tree if requested
            if show_structure:
                structure_query = """
                MATCH path = (lib:ROOT_MODULE {{name: $library_name}})-[:HAS_SUBMODULE|HAS_CLASS|HAS_METHOD|HAS_FUNCTION*0..{depth}]->(entity)
                WITH entity, length(path) AS depth_level, path
                WHERE depth_level <= $depth
                ORDER BY depth_level, entity.__name__
                RETURN 
                    entity.__name__ AS name,
                    [label IN labels(entity) WHERE label IN ['MODULE', 'CLASS', 'FUNCTION', 'METHOD']][0] AS type,
                    depth_level,
                    [node in nodes(path) | node.__name__] AS path_segments
                """
                
                structure_results = self.structured_query(
                    structure_query.format(depth=actual_depth),
                    {"library_name": library_name, "depth": actual_depth}
                )
                
                # Build ASCII tree
                tree_lines = [library_name + "/"]
                prev_path = []
                
                for result in structure_results:
                    if result["depth_level"] == 0:
                        continue
                        
                    segments = result["path_segments"][1:]  # Skip root
                    indent = "  " * (len(segments) - 1)
                    is_last = False  # Simplified - could be enhanced with sibling detection
                    prefix = "└── " if is_last else "├── "
                    
                    entity_type_marker = {
                        "MODULE": "📦",
                        "CLASS": "🔷",
                        "FUNCTION": "⚡",
                        "METHOD": "⚙️"
                    }.get(result["type"], "")
                    
                    tree_lines.append(f"{indent}{prefix}{entity_type_marker} {result['name']}")
                
                structure_tree = "\n".join(tree_lines)
            
            # Fetch definitions if requested
            if show_definitions:
                definitions_query = """
                MATCH path = (lib:ROOT_MODULE {{name: $library_name}})-[:HAS_SUBMODULE|HAS_CLASS|HAS_METHOD|HAS_FUNCTION*0..{depth}]->(entity)
                WHERE length(path) <= $depth
                AND length(path) > 0
                WITH entity, 
                     [node in nodes(path) | node.__name__] AS path_segments,
                     length(path) AS depth_level
                ORDER BY path_segments, entity.__name__
                
                WITH collect(entity) AS all_entities, count(entity) AS total_count
                UNWIND all_entities AS entity
                
                WITH entity, total_count
                SKIP $skip
                LIMIT $page_size
                
                RETURN 
                    entity.name AS full_name,
                    entity.__name__ AS name,
                    entity.shortest_call_path AS path,
                    [label IN labels(entity) WHERE label IN ['MODULE', 'CLASS', 'FUNCTION', 'METHOD']][0] AS type,
                    CASE 
                        WHEN entity.start_line IS NOT NULL AND entity.end_line IS NOT NULL 
                        THEN 'L' + toString(entity.start_line) + '-' + toString(entity.end_line)
                        ELSE ''
                    END AS location,
                    entity.signature AS signature,
                    entity.summary AS summary,
                    total_count
                """
                
                definitions_results = self.structured_query(
                    definitions_query.format(depth=actual_depth),
                    {
                        "library_name": library_name,
                        "depth": actual_depth,
                        "skip": skip,
                        "page_size": page_size
                    }
                )
                
                if definitions_results:
                    total_definitions = definitions_results[0].get("total_count", 0)
                    
                    for result in definitions_results:
                        definitions.append({
                            "path": result["path"],
                            "name": result["name"],
                            "type": result["type"],
                            "location": result["location"],
                            "signature": result.get("signature", ""),
                            "summary": result.get("summary", "")
                        })
            
            # Calculate pagination
            total_pages = (total_definitions + page_size - 1) // page_size if page_size > 0 else 1
            next_page = page + 1 if page < total_pages else None
            
            depth_msg = "full depth" if depth_display == 0 else f"depth={depth_display}"
            system_message = f"Library map for '{library_name}' at {depth_msg}. "
            if show_definitions:
                system_message += f"Found {total_definitions} definitions. "
                system_message += f"Showing page {page} of {total_pages}."
                if next_page:
                    system_message += f" Use page={next_page} to see more."
            
            data = {
                "library_name": library_name,
                "depth": depth_display,
                "structure": structure_tree if show_structure else "",
                "definitions": definitions,
                "next_page": next_page,
                "current_page": page,
                "total_definitions": total_definitions,
                "system_message": system_message
            }
            return _dict_to_xml_string(data, "library_map_response")
            
        except Exception as e:
            logging.error(f"Error generating library map: {e}")
            data = {
                "library_name": library_name,
                "depth": depth_display,
                "structure": "",
                "definitions": [],
                "next_page": None,
                "current_page": page,
                "total_definitions": 0,
                "system_message": f"Error generating library map: {str(e)}"
            }
            return _dict_to_xml_string(data, "library_map_response")