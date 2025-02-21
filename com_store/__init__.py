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
from reflex import Entity, Relationship
import re
import logging
import neo4j

logging.basicConfig(level=logging.INFO)
BASE_ENTITY_LABEL = "__Entity__"
BASE_NODE_LABEL = "__Node__"

def check_if_not_null(props: List[str], values: List[Any]) -> None:
    """Check if variable is not null and raise error accordingly."""
    for prop, value in zip(props, values):
        if not value:
            raise ValueError(f"Parameter `{prop}` must not be None or empty string")

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

    -   If the MAIN_ENTITY is a **Function/Method:** (**THESE INCLUDE EVERYTHING STARTING WITH A `def ` in python, from methods, functions to properties, etc.**)
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
        -   **For each method (**THESE INCLUDE EVERYTHING STARTING WITH A `def ` in python, from methods, functions to properties, etc.**):**
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

    Please think, reason and analyze the above properly.
    Your response should be formatted as follows:
    <thinking>
    (all thinking, reasoning, analysis to be written here IN DETAIL)
    </thinking>

    Paths:
    (dependencies listed here, one per line)
"""

FULL_TEXT_FULL_NAME_SEARCH_TEMPLATE = """
Could not find exact match...
Used a full-text index search to find the following best matches for the full paths(top 3 max):

{top_3_matches}
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
        CREATE FULLTEXT INDEX general_fts_index IF NOT EXISTS FOR (n:__Entity__) ON EACH [n.name, n.source]
        """
        self.database_query(general_fts_query)

    def retrieve_relevant_root_modules(self, query: str, top_k: int = 10) -> str:
        """
        Retrieve relevant root modules based on the query, using similarity search.

        Args:
            query (str): The query string.
            top_k (int): The number of results to return. Defaults to None.

        Returns:
            str: Relevant root modules based on the query formatted as a string.

        Example Output:
        ```
        Relevant Root Modules:

        1. module1: summary1
        2. module2: summary2
        ...
        ```
        """
        results = self.query_vector_index("root_module_vector_index", query, top_k=top_k)

        # Format the results as a string
        formatted_results = "Relevant Root Modules:\n\n" + "\n\n".join(
            [f"{i+1}. **{result['name']}** (similarity score: {result['score']}):{result['summary']}" for i, result in enumerate(results)]
        )

        return formatted_results
    
    def retrieve_relevant_children_in_subtree(self, query: str, parent_name: str) -> str:
        """
        Retrieve relevant IMMEDIATE children in the subtree of the given parent based on the query, using similarity search.

        Args:
            query (str): The query string.
            parent_name (str): The name of the parent entity.

        Returns:
            str: Relevant children in the subtree of the parent based on the query formatted as a string.

        Example Output:
        ```
        Relevant Children in Subtree:

        1. child1: summary1
        2. child2: summary2
        ...
        ```
        """
        # Embed the query
        query_vector = Settings.embed_model.get_query_embedding(query)

        # Use a cypher query to return all IMMEDIATE children of the parent entity, sorted by similarity to the query
        sort_and_return_children_query = """
            MATCH (parent {name: $parent_name})-[:HAS_SUBMODULE|HAS_CLASS|HAS_METHOD|HAS_FUNCTION|EXPOSES]->(child)
            WHERE child.embedding IS NOT NULL
            WITH parent, child,
            vector.similarity.cosine(parent.embedding, $query_vector) AS similarity
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

            # Format the results as a string
            formatted_results = "Relevant Children in Subtree:\n\n" + "\n\n".join(
                [f"{i+1}. **{result['name']}** (similarity score: {result['score']}, relevant labels: {result['labels']}):\n{result['summary']}" for i, result in enumerate(records)]
            )
            
            return formatted_results
        
        except Exception as e:
            logging.error(f"Error retrieving relevant children in subtree: {e}")
            return []

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

        # Add dunder labels to entities starting with '_'
        self._add_dunder_labels(module_name)

    def _add_dunder_labels(self, module_name: str):
        """
        Add dunder labels to entities starting with '_' in the specified module's subtree.

        Args:
            module_name (str): The name of the module.
        """
        # Create cypher query to add dunder labels to entities starting with '_'
        add_dunder_labels_query = (
            """
            MATCH (root:ROOT_MODULE {name: $module_name})
            MATCH (root)-[:HAS_SUBMODULE|HAS_CLASS|HAS_METHOD|HAS_FUNCTION|EXPOSES*]->(children)
            WHERE children.name STARTS WITH '_'
            CALL apoc.create.addLabels(children, ['DUNDER'])
            YIELD node
            RETURN count(node) AS numNodesLabeled
            """
        )

        self.structured_query(add_dunder_labels_query, {"module_name": module_name})

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
            MATCH (root:ROOT_MODULE {name: 'emoji'})
            MATCH (end:MODULE|FUNCTION|CLASS|METHOD)<-[:HAS_CLASS|HAS_METHOD|HAS_FUNCTION|EXPOSES*]-(root)
            WITH root, collect(end) AS endNodes
            CALL apoc.path.spanningTree(root, {
            relationshipFilter: 'HAS_SUBMODULE|HAS_CLASS|HAS_METHOD|HAS_FUNCTION|EXPOSES>',
            terminatorNodes: endNodes
            })
            YIELD path
            WITH nodes(path) AS nodesInPath
            WITH nodesInPath[-1] AS targetNode, nodesInPath[-2] as parentNode
            WHERE targetNode.shortest_call_path IS NULL
            SET targetNode.shortest_call_path =
            CASE
                WHEN size(parentNode.name + "." + targetNode.__name__) < size(targetNode.name)
                THEN parentNode.name + "." + targetNode.__name__
                ELSE targetNode.name
            END
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
            MERGE (child)-[:HAS_METHOD]->(member)
            RETURN child.name AS ChildClass, COUNT(DISTINCT member) AS TotalParentMembersLabeled
            """
        )
        self.structured_query(handle_inheritance_query, {"module_name": module_name})

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
            summaries.append(entity_node.properties.get("summary", ""))

        # Embed the nodes
        embeddings = Settings.embed_model.get_text_embedding_batch(
            summaries,
            show_progress=True
        )

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
    
    def _parse_deps_response(self, response: str) -> List[str]:
        """
        Parse the dependencies response using regex.

        Response Format:
        <thinking>
        (all thinking, reasoning, analysis to be written here IN DETAIL)
        </thinking>

        Paths:
        (dependencies listed here, one per line)

        Args:
            response (str): The response string.

        Returns:
            List[str]: The parsed dependencies.
        """
        # Remove THINKING part of the response
        response = re.sub(r"<thinking>.*?</thinking>", "", response, flags=re.DOTALL)
        response = response.strip()

        # Extract the dependencies from the response
        dependencies = re.findall(r"Paths:\n(.*?)", response, flags=re.DOTALL)

        if dependencies:
            if "NONE" in dependencies[0]:
                logging.info("No dependencies found.")
                return []

            dependencies = dependencies[0].strip().split("\n")
            logging.info(f"Dependencies found: {dependencies}")

        return dependencies

    async def _get_dependencies(self, entity_name: str, parent_module_repr: str) -> List[str]:
        """
        Get the dependencies of the given entity.

        Args:
            entity_name (str): The name of the entity.
            parent_module_repr (str): The representation of the parent module.

        Returns:
            List[str]: The dependencies of the entity.
        """
        prompt = DEFAULT_DEPENDENCY_PATHS_PROMPT_TEMPLATE.format(
            main_entity_name=entity_name,
            parent_module_information=parent_module_repr
        )

        deps = await Settings.llm.acomplete(prompt)
        deps = deps.text.strip()

        deps = self._parse_deps_response(deps)
        return deps

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
    
    def _get_full_path_name(self, name: str, label: str = None) -> str:
        """
        Get the full path name of the entity.

        Args:
            name (str): The name of the entity.
            label (str): The label of the entity. Defaults to None. Accepts values 'ROOT_MODULE', 'MODULE', 'CLASS', 'METHOD' and 'FUNCTION'.

        Returns:
            str: The full path name of the entity.
        """
        if label:
            retrieve_node_by_name_query = (
                """
                MATCH (n:{label} {name: $name})
                RETURN n.name AS name
                """
            )
            # Execute the query to retrieve the node by name
            retrieved_node = self.structured_query(retrieve_node_by_name_query, {"name": name, "label": label})

        else:
            retrieve_node_by_name_query = (
                """
                MATCH (n:METHOD|FUNCTION|CLASS {name: $name})
                RETURN n.name AS name
                """
            )

            # Execute the query to retrieve the node by name
            retrieved_node = self.structured_query(retrieve_node_by_name_query, {"name": name})

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

        if retrieved_node:
            name = retrieved_node[0]["name"]
            return name
        
        # If no relevant nodes or relationships are found, search in a full-text index
        if label:
            records = self.query_fulltext_index(f"{label.lower()}_index", name)[:3]

        else:
            records = self.query_fulltext_index("general_fts_index", name)[:3]

        if not records:
            return "NONE"  

        records_str += "\n\n".join([f"{i + 1}. {record["name"]}" for i, record in enumerate(records)])
        result = FULL_TEXT_FULL_NAME_SEARCH_TEMPLATE.format(
            top_3_matches=records_str
        )

        return result