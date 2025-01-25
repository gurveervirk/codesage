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
# from reflex import Entity, Relationship
import logging
import neo4j

_logger = logging.getLogger(__name__)
BASE_ENTITY_LABEL = "__Entity__"
BASE_NODE_LABEL = "__Node__"

def check_if_not_null(props: List[str], values: List[Any]) -> None:
    """Check if variable is not null and raise error accordingly."""
    for prop, value in zip(props, values):
        if not value:
            raise ValueError(f"Parameter `{prop}` must not be None or empty string")

class Entity:
    """
    Module-agnostic entity class.
    """
    def __init__(self, name: str, label: str, properties: Dict):
        self.name = name
        self.label = label
        self.properties = properties

    def __repr__(self):
        return f"{self.label} ({self.name})"

class Relationship:
    """
    Module-agnostic relation class.
    """
    def __init__(self, from_entity: Entity, to_entity: Entity, label: str, properties: Dict):
        self.from_entity = from_entity
        self.to_entity = to_entity
        self.label = label
        self.properties = properties

    def __repr__(self):
        return f"{self.from_entity} --{self.label}--> {self.to_entity}"

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
        CREATE FULLTEXT INDEX root_module_index IF NOT EXISTS FOR (n:`ROOT_MODULE`) ON EACH [n.`name`, n.`source`]
        """
        self.database_query(root_module_index_query)

        function_index_query = """
        CREATE FULLTEXT INDEX function_index IF NOT EXISTS FOR (n:`FUNCTION`) ON EACH [n.`name`, n.`source`]
        """
        self.database_query(function_index_query)

        module_index_query = """
        CREATE FULLTEXT INDEX module_index IF NOT EXISTS FOR (n:`MODULE`) ON EACH [n.`name`, n.`source`]
        """
        self.database_query(module_index_query)

        class_index_query = """
        CREATE FULLTEXT INDEX class_index IF NOT EXISTS FOR (n:`CLASS`) ON EACH [n.`name`, n.`source`]
        """
        self.database_query(class_index_query)

        method_index_query = """
        CREATE FULLTEXT INDEX method_index IF NOT EXISTS FOR (n:`METHOD`) ON EACH [n.`name`, n.`source`]
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
        CREATE FULLTEXT INDEX general_fts_index IF NOT EXISTS FOR (n:__Entity__) ON EACH [n.name, n.source]
        """
        self.database_query(general_fts_query)

    def query_vector_index(
        self, index_name: str, query: str | List[float],
        **kwargs: Any
    ) -> List[Dict]:
        """
        Query a vector index.

        Args:
            index_name (str): The name of the vector index, restricted to `method_vector_index`, `class_vector_index` and `module_vector_index`.
            query (str or List[float]): The query or query vector embedding.

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
        CALL db.index.vector.queryNodes($index_name, $top_k, $query_vector)
        YIELD node AS n, score
        RETURN {return_fields_str}, score
        """
        query_params = {
            "index_name": index_name,
            "top_k": kwargs.get("top_k", 10),
            "query_vector": query_vector,
        }

        try:
            records = self.database_query(query_str, query_params)
            return records
        except Exception as e:
            _logger.error(f"Error querying vector index '{index_name}': {e}")
            return []

    def query_fulltext_index(
        self, index_name: str, query: str, labels: List[str] = [],
        **kwargs: Any
    ) -> List[Dict]:
        """
        Query a full-text index.

        Args:
            index_name (str): The name of the full-text index, restricted to `module_index`, `class_index` and `method_index`.
            query (str): The query string.
            labels (List[str]): A list of labels to filter query results (e.g., ["module_name", "class_name"]).
        Returns:
            List[Dict]: A list of dictionaries containing the query results.
        """
        return_fields = ["name", "source"]
        return_fields_str = ", ".join([f"n.{field} AS {field}" for field in return_fields])

        query_str = f"""
        CALL db.index.fulltext.queryNodes($index_name, $query)
        YIELD node AS n, score
        """
        if labels:
            query_str += f"""
            WHERE any(label IN labels(n) WHERE label IN $labels)
            """
        query_str += f"""
        RETURN {return_fields_str}, score
        """
        query_params = {
            "index_name": index_name,
            "query": query,
            "labels": labels
        }

        try:
            records = self.database_query(query_str, query_params)
            return records
        except Exception as e:
            _logger.error(f"Error querying full-text index '{index_name}': {e}")
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
            _logger.error(f"Error performing similarity search: {e}")
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

    def create_entity(self, label: str, name: str, properties: dict = None) -> EntityNode:
        """
        Create an entity node with the given label, name, and properties.

        Args:
            label (str): The label of the entity.
            name (str): The name of the entity.
            properties (dict, optional): Additional properties of the entity.

        Returns:
            EntityNode: The created entity node.
        """
        properties = {k: str(v) for k, v in (properties or {}).items()}
        return EntityNode(label=label, name=name, properties=properties)

    def create_relation(self, label: str, source: EntityNode, target: EntityNode, properties: dict = None) -> Relation:
        """
        Create a relation between two entities with the given label and properties.

        Args:
            label (str): The label of the relation.
            source (EntityNode): The source entity node.
            target (EntityNode): The target entity node.
            properties (dict, optional): Additional properties of the relation.

        Returns:
            Relation: The created relation.
        """
        properties = {k: str(v) for k, v in (properties or {}).items()}
        return Relation(label=label, source_id=source.id, target_id=target.id, properties=properties)

    def upsert_to_neo4j(self, module_name: str, entities: List[Entity], relations: List[Relationship], other_relations: Dict[str, List[Tuple]]) -> None:
        """
        Upsert entities and relationships into Neo4j.

        Args:
            module_name (str): The name of the module.
            entities (List[Entity]): List of entity nodes to upsert.
            relations (List[Relationship]): List of relationships to upsert.
            other_relations (Dict[str, List[Tuple]]): Dictionary containing other relations.
        """
        # Convert Entity to EntityNode and Relationship to Relation
        entity_nodes = []
        entities_to_entity_nodes = {}

        for entity in entities:
            entity_node = self.create_entity(entity.label, entity.name, entity.properties)
            entity_nodes.append(entity_node)
            entities_to_entity_nodes[entity.name] = entity_node

        relations = [
            Relation(
                label=r.label,
                source_id=entities_to_entity_nodes[r.from_entity.name].id,
                target_id=entities_to_entity_nodes[r.to_entity.name].id,
                properties=r.properties
            ) for r in relations
        ]

        self.upsert_nodes(entity_nodes)
        self.upsert_relations(relations)

        # Embed the nodes
        self.embed_nodes()

        # Add labels recursively
        self.add_labels(module_name)

        # Add INHERITS and IMPORTS relations as properties to the respective nodes
        self.add_other_relations_as_properties(other_relations)

        # Process INHERITS and IMPORTS relations
        self.process_other_relations()

    def add_other_relations_as_properties(self, other_relations: Dict[str, List[Tuple]]):
        """
        Add INHERITS and IMPORTS relations as properties to the respective nodes.

        Args:
            other_relations (Dict[str, List[Tuple]]): Dictionary containing INHERITS and IMPORTS relations.
        """
        inherits_relations = other_relations.get("INHERITS", [])
        imports_relations = other_relations.get("IMPORTS", [])
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
        self.structured_query(add_inherits_query, {"inherits_relations": inherits_relations})
        self.structured_query(add_imports_query, {"imports_relations": imports_relations})

    def process_other_relations(self):
        """
        Execute Cypher queries to create relations on existing nodes with INHERITS and IMPORTS properties.
        Clear names from the INHERITS and IMPORTS property arrays of the nodes if the relations could be created successfully.
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

        self.structured_query(process_inherits_query)
        self.structured_query(process_imports_query)
        self.structured_query(cleanup_empty_INHERITS_query)
        self.structured_query(cleanup_empty_IMPORTS_query)

    def add_labels(self, module_name):
        """
        Add labels to modules and classes recursively.

        Args:
            module_name (str): The name of the module to label.
        """
        # First query: Exclude :IMPORTS relation
        module_query = (
            """
            MATCH (base:ROOT_MODULE {name: 'requests'})-[r*0..]->(descendant:MODULE)
            WHERE NONE(rel IN r WHERE type(rel) = 'IMPORTS')
            WITH DISTINCT descendant.name AS moduleNames
            UNWIND moduleNames AS moduleName
            MATCH (parent:MODULE {name: moduleName})-[r]->(descendant)
            WHERE type(r) <> "IMPORTS"
            CALL apoc.create.addLabels(parent, [moduleName]) YIELD node as pnode
            CALL apoc.create.addLabels(descendant, [moduleName]) YIELD node as dnode
            RETURN moduleName, COUNT(DISTINCT descendant) AS TotalNodesLabeled
            """
        )
        self.structured_query(module_query, {"module_name": module_name})

        # Second query: Exclude :INHERITS relation
        class_query = (
            """
            MATCH (base:ROOT_MODULE {name: 'requests'})-[r*0..]->(class:CLASS)
            WHERE NONE(rel IN r WHERE type(rel) = 'INHERITS')
            WITH DISTINCT class
            MATCH (class)-[r]->(descendant)
            WHERE type(r) <> "INHERITS"
            CALL apoc.create.addLabels(class, [class.name]) YIELD node as cnode
            CALL apoc.create.addLabels(descendant, [class.name]) YIELD node as dnode
            RETURN class.name AS ClassName, COUNT(DISTINCT descendant) AS TotalNodesLabeled
            """
        )
        self.structured_query(class_query, {"module_name": module_name})

        # Third query: Handle :INHERITS relation
        inherits_query = (
            """
            MATCH (base:ROOT_MODULE {name: $module_name})-[r*0..]->(child:CLASS)
            WHERE NONE(rel IN r WHERE type(rel) = 'INHERITS')
            WITH DISTINCT child
            MATCH (child)-[:INHERITS*0..]->(parent:CLASS)
            WITH child, parent
            MATCH (parent)-[:HAS_METHOD]->(member)
            WHERE NOT EXISTS {
                MATCH (child)-[:HAS_METHOD]->(childMember)
                WHERE split(childMember.name, ".")[-1] = split(member.name, ".")[-1]
            }
            WITH member, child, labels(child) AS childLabels
            CALL apoc.create.addLabels(member, childLabels) YIELD node as labeledMember
            RETURN child.name AS ChildClass, COUNT(DISTINCT member) AS TotalParentMembersLabeled
            """
        )
        self.structured_query(inherits_query, {"module_name": module_name})

    def remove_empty_values(self, input_dict):
        """
        Remove entries with empty values from the dictionary.

        Parameters:
        input_dict (dict): The dictionary from which empty values need to be removed.

        Returns:
        dict: A new dictionary with all empty values removed.
        """
        # Create a new dictionary excluding empty values
        return {key: value for key, value in input_dict.items() if value}

    def embed_nodes(self):
        """
        Embed newly created nodes.
        """
        retrieve_new_nodes = (
            """
            MATCH (e)
            WHERE e.embedding IS NULL
            RETURN
            e.id AS name,
            labels(e)[0] AS type,
            properties(e) AS properties
            """
        )
        new_nodes = self.structured_query(retrieve_new_nodes)
        if not new_nodes:
            return

        entity_nodes, source_codes = [], []
        # Create EntityNode objects for each node
        for node in new_nodes:
            entity_node = EntityNode(
                label=node["type"],
                name=node["name"],
                properties=self.remove_empty_values(node["properties"])
            )
            entity_nodes.append(entity_node)
            source_codes.append(entity_node.properties.get("source", ""))

        # Embed the nodes
        embeddings = Settings.embed_model.get_text_embedding_batch(source_codes)

        for i, node in enumerate(entity_nodes):
            node.properties[self.embedding_node_property] = embeddings[i]

        self.upsert_nodes(entity_nodes)