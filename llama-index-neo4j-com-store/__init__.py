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
import json
import neo4j

logging.basicConfig(level=logging.INFO)
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

# Template for generating code for the entity with all of it's relevant entities
DEFAULT_CODE_GENERATION_PROMPT_TEMPLATE = """
    You are a code generation expert. You are to generate end-to-end code, with all the dependencies and requirements, for the following MAIN_ENTITY, using the following information:

    MAIN_ENTITY:
    {main_entity_name}

    RELEVANT_ENTITIES:
    {relevant_entities_information}

    Please keep in mind the following instructions, if any:
    {other_instructions}

    Your code should be complete and ready to run.
    The code should be specifically and solely for the MAIN_ENTITY ONLY, NOTHING ELSE.
    Use the shortest_call_path's to import and use stuff, wherever necessary.
    This is a completely new and unique code being shown to you, used and generated. Do not worry about recitation.

    Code:
"""

# Template for getting the full paths of dependencies given an entity and it's MODULE code
DEFAULT_DEPENDENCY_PATHS_PROMPT_TEMPLATE = """
    You are a code analysis expert. You are to find all the full paths of parameter types as well as return types for using the following MAIN_ENTITY, given the following information, rules and examples ONLY:

    MAIN_ENTITY name:
    {main_entity_name}

    PARENT_MODULE information:
    {parent_module_information}

    **Rules:**

    These rules are designed to precisely filter the dependencies you need to report. Follow them in the order presented, with higher-numbered rules having precedence over lower-numbered rules.

    **1. Entity Type Determination:**

    -   Determine whether the MAIN_ENTITY is a **Function/Method** or a **Class**.

    **2. Handling Functions/Methods:**

    -   If the MAIN_ENTITY is a **Function/Method:**
        -   **Identify:**
            -   Parameter types from the function/method signature.
            -   Return types from the function/method signature or docstring (if present in the format `:rtype:`).
        -   **Include:** Only the identified parameter and return types.
        -   **Exclude:**
            -   Any types related to exceptions or errors.
            -   Types of any intermediate variables.

    **3. Handling Classes:**

    -   If the MAIN_ENTITY is a **Class:**
        -   **Analyze:** All methods within the class, excluding the `__init__` method.
        -   **For each method:**
            -   **Identify:**
                -   Parameter types from the method signature.
                -   Return types from the method signature or docstring (if present in the format `:rtype:`).
            -   **Include:** Only the identified parameter and return types from each method.
            -   **Exclude:**
                -   Any types related to exceptions or errors.
                -   Types of any intermediate variables.
        -   **Special Handling of `__init__`:**
            -   **Identify:** Parameter types from the `__init__` method's signature.
            -   **Include:** Only the identified parameter types.
            -   **Exclude:** Everything else from `__init__`, including return types (which is implicitly `None`).
        -   **Class/Instance Attribute Exclusion:**
            -   **Always Exclude:** Types used to define or initialize class or instance attributes, variables, or properties. These are often found in the `__init__` method or defined directly within the class using `self.`.

    **4. Dependency Filtering:**

    -   After applying rules 1-3, filter the identified types as follows:
        -   **Exclude:**
            -   **Built-in Types:** Types from the `builtins` module (e.g., `str`, `int`, `list`, `None`).
            -   **Typing Module Types:** Types from the `typing` module (e.g., `List`, `Dict`, `Optional`).
            -   **Implicit Dependencies:** Types that are not explicitly used as parameter or return types.
            -   **Reiterate Class/Instance Attribute Exclusion:** Exclude any types that were used to define or initialize class or instance attributes, variables, or properties, even if they appear in a method's parameter or return type.

    Example 1:
    MAIN_ENTITY name:
    alpha.beta.gamma

    PARENT_MODULE information:
    Name: beta
    Full Path: alpha.beta
    Imports: ['charlie.delta']
    Source: ```
    from charlie import delta

    def something() -> None:
        pass

    def gamma(in: delta) -> None:
        something()
        pass
    ```

    Paths:
    charlie.delta

    Example 2:
    MAIN_ENTITY name:
    alpha.beta.gamma

    PARENT_MODULE information:
    Name: beta
    Full Path: alpha.beta
    Imports: ['charlie.delta']
    Source: ```
    from charlie import delta

    def gamma() -> None:
        pass
    ```

    Paths:
    NONE

    Example 3:
    MAIN_ENTITY name:
    alpha.beta.gamma

    PARENT_MODULE information:
    Name: beta
    Full Path: alpha.beta
    Imports: ['charlie.delta']
    Source: ```
    from charlie import delta

    def gamma():
        ```
        A function that uses something.

        :rtype: delta
        ```
        return something()
    
    Paths:
    charlie.delta

    Example 4:
    MAIN_ENTITY name:
    alpha.beta.gamma

    PARENT_MODULE information:
    Name: beta
    Full Path: alpha.beta
    Imports: ['charlie.delta']
    Source: ```
    from charlie import delta

    def gamma():
        ```
        A function that does something.

        :rtype: something
        ```
        return delta()
        
    Paths:
    something

    Example 5:
    MAIN_ENTITY name:
    alpha.beta.gamma

    PARENT_MODULE information:
    Name: beta
    Full Path: alpha.beta
    Imports: ['charlie.delta', 'charlie.epsilon', 'charlie.zeta', 'charlie.eta', 'charlie.theta']
    Source: ```
    from charlie import delta, epsilon, zeta, eta, theta

    class gamma:
        ```
        A class that does something.
        ```
        def __init__(self, something: delta):
            self.something = something
            self.something_else = epsilon()

        def method_1(self, something_else: zeta) -> eta:
            temp = theta(something_else)

            return eta(temp)
    ```

    Paths:
    charlie.delta
    charlie.zeta
    charlie.eta

    Your response should be formatted as follows:
    ANALYSIS:
    [all analysis, thinking and reasoning goes here
    ...
    ....
    ....]

    Paths:
    (dependencies listed here, one per line)
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

    def refresh_schema(self):
        """
        Set the schema using schema.json file.
        """
        self.structured_schema = json.loads(
            open("./schema.json", "r").read()
        )

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
            logging.error(f"Error querying vector index '{index_name}': {e}")
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
            entity_node = EntityNode(
                label=entity.label,
                name=entity.name,
                properties=entity.properties
            )
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
        self._embed_nodes()

        # Add labels recursively
        self._add_labels(module_name)

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
            MATCH (n)-[r:EXPOSES]-(m)
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
            MATCH (root:ROOT_MODULE {name: $module_name})
            MATCH (end:MODULE|FUNCTION|CLASS|METHOD)<-[:HAS_CLASS|HAS_METHOD|HAS_FUNCTION|EXPOSES*]-(root)
            WITH root, collect(end) AS endNodes
            CALL apoc.path.spanningTree(root, {
            relationshipFilter: 'HAS_SUBMODULE|HAS_CLASS|HAS_METHOD|HAS_FUNCTION|EXPOSES>',
            terminatorNodes: endNodes
            })
            YIELD path
            WITH nodes(path) AS nodesInPath
            WITH nodesInPath[-1] AS targetNode, nodesInPath[-2] as parentNode
            SET targetNode.shortest_call_path =
            CASE
                WHEN size(parentNode.name + "." + targetNode.__name__) < size(targetNode.name)
                THEN parentNode.name + "." + targetNode.__name__
                ELSE targetNode.name
            END
            RETURN count(targetNode) AS numPathsSet
            """
        )
        numPathsSet = self.structured_query(set_shortest_call_paths_query, {"module_name": module_name})
        while numPathsSet > 0:
            numPathsSet = self.structured_query(set_shortest_call_paths_query, {"module_name": module_name})

    def _add_labels(self, module_name):
        """
        Add labels to modules and classes recursively.

        Args:
            module_name (str): The name of the module to label.
        """
        # First query: Exclude :IMPORTS relation
        module_query = (
            """
            MATCH (base:ROOT_MODULE {name: $module_name})
            WITH base
            OPTIONAL MATCH (base)-[r*0..]->(descendant:MODULE)
                        WHERE NONE(rel IN r WHERE type(rel) = 'IMPORTS')
            WITH base, collect(DISTINCT descendant.name) AS descendantModuleNames
            WITH base, descendantModuleNames + base.name as moduleNames
            UNWIND moduleNames AS moduleName
            MATCH (parent:MODULE|ROOT_MODULE {name: moduleName})-[r]->(descendant)
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
            MATCH (base:ROOT_MODULE {name: $module_name})-[r*0..]->(class:CLASS)
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
                MATCH (child)-[:HAS_METHOD]->(childMethod)
                WHERE childMethod.__name__ = member.__name__
            }
            WITH member, child
            CALL apoc.create.addLabels(member, [child.name]) YIELD node as labeledMember
            RETURN child.name AS ChildClass, COUNT(DISTINCT member) AS TotalParentMembersLabeled
            """
        )
        self.structured_query(inherits_query, {"module_name": module_name})

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
                properties=self._remove_empty_values(node["properties"])
            )
            entity_nodes.append(entity_node)
            source_codes.append(entity_node.properties.get("source", ""))

        # Embed the nodes
        embeddings = Settings.embed_model.get_text_embedding_batch(source_codes)

        for i, node in enumerate(entity_nodes):
            node.properties[self.embedding_node_property] = embeddings[i]

        self.upsert_nodes(entity_nodes)

    def _get_parent_module_info(self, entity_name: str) -> List[str]:
        """
        Get the path from the given entity to the parent module.

        Args:
            entity_name (str): The name of the entity.

        Returns:
            List[str]: The path from the entity to the parent module.
        """
        get_parent_module_info_query = (
            """
            MATCH (end {name: $entity_name})<-[:HAS_CLASS|HAS_METHOD|HAS_FUNCTION*1..]-(parent:MODULE|ROOT_MODULE)
            WITH parent, parent.__name__ AS __name__, parent.name AS name, parent.source AS source, end.shortest_call_path AS shortest_call_path
            MATCH (parent)-[:IMPORTS]->(import)
            WITH __name__, name, source, shortest_call_path, collect(import.name) AS imports
            RETURN __name__, name, source, shortest_call_path, imports
            """
        )
        result = self.structured_query(get_parent_module_info_query, {"entity_name": entity_name})
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
        Name: {retrieved_node["__name__"]}
        Full Path: {retrieved_node["name"]}
        Imports: {retrieved_node["imports"]}
        Source: ```
        {retrieved_node["source"]}
        ```
        """
        return entity_representation

    async def _get_dependencies(self, entity_name: str, parent_module_repr: str) -> List[str]:
        """
        Get the dependencies of the given entity.

        Args:
            entity_name (str): The name of the entity.
            parent_module_repr (str): The representation of the parent module.

        Returns:
            List[str]: The dependencies of the entity.
        """
        dependencies = []
        prompt = DEFAULT_DEPENDENCY_PATHS_PROMPT_TEMPLATE.format(
            main_entity_name=entity_name,
            parent_module_information=parent_module_repr
        )

        deps = await Settings.llm.acomplete(prompt)
        deps = deps.text.strip()

        if "NONE" in deps:
            logging.info(f"No dependencies found for entity: {entity_name}")
            return dependencies

        dependencies = deps.split("\n")
        logging.info(f"Dependencies for entity {entity_name}: {dependencies}")
        return dependencies

    async def _generate_code_using_llm(self, main_entity_name: str, relevant_entities_repr: List[Tuple[str, str]], other_instructions: str) -> str:
        """
        Generate code using the LLM model.

        Args:
            main_entity_name (str): The name of the main entity.
            relevant_entities_repr (List[Tuple[str, str]]): The representations of the relevant entities.
            other_instructions (str): Other instructions to be included in the prompt.

        Returns:
            str: The generated code.
        """
        relevant_entities_information = ""
        for entity_repr in relevant_entities_repr:
            relevant_entities_information += f"""
            Shortest Call Path for {entity_repr[0]}: {entity_repr[2]}
            Module Code for {entity_repr[0]}:
            {entity_repr[1]}

            """

        prompt = DEFAULT_CODE_GENERATION_PROMPT_TEMPLATE.format(
            main_entity_name=main_entity_name,
            relevant_entities_information=relevant_entities_information,
            other_instructions=other_instructions
        )

        code = await Settings.llm.acomplete(prompt)
        code = code.text.strip()
        return code
    
    def _get_full_path_name(self, name: str, label: str) -> str:
        """
        Get the full path name of the entity.

        Args:
            name (str): The name of the entity.
            label (str): The label of the entity.

        Returns:
            str: The full path name of the entity.
        """
        retrieve_node_by_name_query = (
            """
            MATCH (n:METHOD|FUNCTION|CLASS {name: $name})
            WHERE $label = "" OR $label IN labels(n)
            RETURN n.name AS name
            """
        )

        # Execute the query to retrieve the node by name
        retrieved_node = self.structured_query(retrieve_node_by_name_query, {"name": name, "label": label})

        if not retrieved_node:
            # If no relevant nodes are found, try querying relationships with this name
            retrieve_relationship_by_name_query = (
                """
                MATCH (n)-[r:EXPOSES]->(m)
                WHERE r.name = $name
                RETURN m.name AS name
                """
            )

            # Execute the query to retrieve relevant relationships
            retrieved_node = self.structured_query(retrieve_relationship_by_name_query, {"name": name})

        if not retrieved_node:
            # If no relevant nodes or relationships are found, return an error message
            return "NONE"

        name = retrieved_node[0]["name"]
        return name

    async def generate_code(self, name: str, label: Optional[str] = "", other_instructions: Optional[str] = "") -> str:
        """
        Generate code for a given entity name.

        Args:
            name (str): The name of the entity.
            label (Optional[str]): The label of the entity.
            other_instructions (Optional[str]): Other instructions to be included in the prompt.

        Returns:
            str: The generated code for the entity.
        """
        # Check if the entity exists in the database
        name = self._get_full_path_name(name, label)

        if name == "NONE":
            return "Entity not found in the database."

        parent_module = self._get_parent_module_info(name)
        parent_module_repr = self._get_retrieved_entity_representation(parent_module[0]) if parent_module else ""

        relevant_entities_repr = [(name, parent_module_repr, parent_module[0]["shortest_call_path"] if parent_module else "")]

        deps = await self._get_dependencies(name, parent_module_repr)
        unique_dependencies = set(deps)
        logging.info(f"Initial dependencies for entity {name}: {deps}")

        while deps:
            next_deps = []

            for dep in deps:
                dep = self._get_full_path_name(dep, "")
                dep_parent_module = self._get_parent_module_info(dep)
                dep_parent_module_repr = self._get_retrieved_entity_representation(dep_parent_module[0]) if dep_parent_module else ""

                relevant_entities_repr.append((dep, dep_parent_module_repr, dep_parent_module[0]["shortest_call_path"] if dep_parent_module else ""))

                new_deps = await self._get_dependencies(dep, dep_parent_module_repr)
                for new_dep in new_deps:
                    if new_dep not in unique_dependencies:
                        next_deps.append(new_dep)
                        unique_dependencies.add(new_dep)

            logging.info(f"Next level dependencies: {next_deps}")
            deps = next_deps

        return await self._generate_code_using_llm(name, relevant_entities_repr, other_instructions)