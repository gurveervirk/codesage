"""
Tool methods for COMStore that return XML-formatted responses for agent/MCP use.
These methods are separated from the main COMStore class for better organization.
"""
from typing import List, Optional
from llama_index.core import Settings
from .xml_utils import dict_to_xml_string
from .main import COMStore
import logging

BASE_ENTITY_LABEL = "__Entity__"
BASE_NODE_LABEL = "__Node__"


class COMStoreTools:
    """
    Tool methods for COMStore that provide agent-friendly XML responses.
    This class contains methods that are exposed as tools for agents and MCP servers.
    """

    def __init__(self, store: COMStore):
        """
        Initialize with a reference to the parent COMStore instance.
        
        Args:
            store: The COMStore instance
        """
        self.store = store

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
        results = self.store.database_query(retrieve_root_modules_query, query_params)

        # Store the results
        self.store._root_modules = results
        self.store._root_modules_index = top_k
        self.store._last_root_modules_query = {"query": query, "top_k": top_k}

        data = {
            "results": self.store._root_modules[:top_k],
            "query_info": {
                "query": query,
                "top_k": top_k,
                "total_found": len(results)
            },
            "system_message": f"Retrieved top {top_k} relevant root modules from {len(results)} total matches."
        }
        return dict_to_xml_string(data, "retrieve_relevant_root_modules_response")
    
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
            records = self.store.database_query(sort_and_return_children_query, query_params)

            # Filter out base labels and retain only the relevant labels
            for record in records:
                record["labels"] = [label for label in record["labels"] if label not in [BASE_ENTITY_LABEL, BASE_NODE_LABEL]]

            # Store the results
            self.store._children = records
            self.store._children_index = top_k
            self.store._last_children_query = {"query": query, "parent_name": parent_name, "top_k": top_k}
            
            data = {
                "results": self.store._children[:top_k],
                "query_info": {
                    "query": query,
                    "parent_name": parent_name,
                    "top_k": top_k,
                    "total_found": len(records)
                },
                "system_message": f"Retrieved top {top_k} relevant children from {len(records)} total matches under '{parent_name}'."
            }
            return dict_to_xml_string(data, "retrieve_relevant_children_response")
        
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
            return dict_to_xml_string(data, "retrieve_relevant_children_response")

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
            if self.store._root_modules == None or self.store._root_modules_index == -1:
                data = {
                    "results": [],
                    "pagination_info": {
                        "source": "ROOT_MODULE",
                        "error": "No ROOT_MODULE query has been made yet or all entities have been retrieved."
                    },
                    "system_message": "No ROOT_MODULE query has been made yet or all entities have been retrieved."
                }
                return dict_to_xml_string(data, "next_entities_response")
            
            start_index = self.store._root_modules_index
            end_index = min(start_index + top_k, len(self.store._root_modules))
            entities = self.store._root_modules[start_index:end_index]
            self.store._root_modules_index = end_index
            all_retrieved = end_index == len(self.store._root_modules)
            
            if all_retrieved:
                self.store._root_modules_index = -1
                self.store._last_root_modules_query = {}
            
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
                                 (" ALL RELEVANT ROOT MODULES RETRIEVED." if all_retrieved else f" {len(self.store._root_modules) - end_index} more available.")
            }
            return dict_to_xml_string(data, "next_entities_response")

        elif from_ == "CHILDREN":
            if self.store._children == None or self.store._children_index == -1:
                data = {
                    "results": [],
                    "pagination_info": {
                        "source": "CHILDREN",
                        "error": "No CHILDREN query has been made yet or all entities have been retrieved."
                    },
                    "system_message": "No CHILDREN query has been made yet or all entities have been retrieved."
                }
                return dict_to_xml_string(data, "next_entities_response")
            
            start_index = self.store._children_index
            end_index = min(start_index + top_k, len(self.store._children))
            entities = self.store._children[start_index:end_index]
            self.store._children_index = end_index
            all_retrieved = end_index == len(self.store._children)
            
            if all_retrieved:
                self.store._children_index = -1
                self.store._last_children_query = {}
            
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
                                 (" ALL RELEVANT CHILDREN RETRIEVED." if all_retrieved else f" {len(self.store._children) - end_index} more available.")
            }
            return dict_to_xml_string(data, "next_entities_response")
        else:
            raise ValueError("`from` must be either 'ROOT_MODULE' or 'CHILDREN'")

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
            // Phase 1: Try direct match by node name
            OPTIONAL MATCH (n1:METHOD|FUNCTION|CLASS|MODULE {name: $name})
            WITH collect(n1)[0] AS direct_match
            
            // Phase 2: If no direct match, try EXPOSES/PUBLISHES relationship name
            OPTIONAL MATCH ()-[r:EXPOSES|PUBLISHES]->(n2:METHOD|FUNCTION|CLASS|MODULE)
            WHERE direct_match IS NULL AND r.name = $name
            WITH direct_match, collect(n2)[0] AS exposed_match
            
            // Return the first non-null match
            WITH COALESCE(direct_match, exposed_match) AS found_node
            RETURN found_node.name AS name
            """
        )

        # Execute the query to retrieve the node by name
        retrieved_node = self.store.structured_query(retrieve_node_by_name_query, {"name": name})

        if retrieved_node and retrieved_node[0]["name"]:
            data = {
                "exact_match": retrieved_node[0]["name"],
                "best_matches": [],
                "system_message": f"Found exact match for entity: '{name}'"
            }
            return dict_to_xml_string(data, "get_full_path_name_response")

        # If no relevant nodes are found, process the name for regex search
        logging.info(f"No relevant nodes found for the name: {name}")
        logging.info(f"Performing full-text search for the full path name of the entity: {name}")
        records_str = self.store._fts_full_path_name(name)

        if records_str:
            best_matches = records_str.split("\n") if records_str else []
            data = {
                "exact_match": "",
                "best_matches": best_matches,
                "system_message": f"No exact match found. Best matches for entity: '{name}'"
            }
            return dict_to_xml_string(data, "get_full_path_name_response")
            
        # Split the name by '.', merge first and last parts, and try to find the full path name
        logging.info(f"Performing full-text search for the full path name of the entity with shortened name: {name}")
        name_parts = name.split(".")
        shortened_name = name_parts[0] + "." + name_parts[-1]
        records_str = self.store._fts_full_path_name(shortened_name)

        if records_str:
            best_matches = records_str.split("\n") if records_str else []
            data = {
                "exact_match": "",
                "best_matches": best_matches,
                "system_message": f"No exact match found. Best matches for entity: '{name}' (using shortened search)"
            }
            return dict_to_xml_string(data, "get_full_path_name_response")
        
        # If no relevant nodes are found, return a message indicating that the full path name could not be found
        logging.warning(f"No full path name found for the entity: {name}")

        data = {
            "exact_match": "",
            "best_matches": [],
            "system_message": f"No full path name found for entity: '{name}'"
        }
        return dict_to_xml_string(data, "get_full_path_name_response")
    
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
            retrieve_node_by_name_query = (
                """
                // Phase 1: Try direct match by node name
                OPTIONAL MATCH (n1:METHOD|FUNCTION|CLASS|MODULE {name: $name})
                WITH collect(n1)[0] AS direct_match
                
                // Phase 2: If no direct match, try EXPOSES/PUBLISHES relationship name
                OPTIONAL MATCH ()-[r:EXPOSES|PUBLISHES]->(n2:METHOD|FUNCTION|CLASS|MODULE)
                WHERE direct_match IS NULL AND r.name = $name
                WITH direct_match, collect(n2)[0] AS exposed_match
                
                // Return the first non-null match
                WITH COALESCE(direct_match, exposed_match) AS found_node
                RETURN found_node.name AS name
                """
            )
            retrieved_node = self.store.structured_query(retrieve_node_by_name_query, {"name": name})

            if retrieved_node and retrieved_node[0]["name"]:
                results.append({
                    "query_name": name,
                    "exact_match": retrieved_node[0]["name"],
                    "best_matches": [],
                    "found": True
                })
            else:
                # Try FTS search
                records_str = self.store._fts_full_path_name(name)
                if records_str:
                    best_matches = records_str.split("\n") if records_str else []
                    results.append({
                        "query_name": name,
                        "exact_match": "",
                        "best_matches": best_matches,
                        "found": False
                    })
                else:
                    # Try shortened name
                    name_parts = name.split(".")
                    shortened_name = name_parts[0] + "." + name_parts[-1]
                    records_str = self.store._fts_full_path_name(shortened_name)
                    if records_str:
                        best_matches = records_str.split("\n") if records_str else []
                        results.append({
                            "query_name": name,
                            "exact_match": "",
                            "best_matches": best_matches,
                            "found": False
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
        return dict_to_xml_string(data, "get_full_path_names_response")
    
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

// Phase 2: If no direct match was found, try the fallback search via the EXPOSES or PUBLISHES relationship
OPTIONAL MATCH ()-[r:EXPOSES|PUBLISHES]->(e2:METHOD|FUNCTION|CLASS)
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

OPTIONAL MATCH ()-[r:EXPOSES|PUBLISHES]->(c2:CLASS)
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

        signatures_result = self.store.structured_query(query, {"entity_names": entity_names})[0]["signatures"]
        
        # Convert the result to a list format for XML
        signatures = []
        for entity_name in entity_names:
            sig_info = signatures_result.get(entity_name)
            if sig_info:
                signatures.append({
                    "entity_name": entity_name,
                    "signature": sig_info.get("signature", ""),
                    "type": sig_info.get("type", ""),
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
        return dict_to_xml_string(data, "get_signatures_response")

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
            conditions = []
            for i, term in enumerate(search_terms):
                param_name = f"term_{i}"
                conditions.append(f"toLower(lib.name) CONTAINS toLower(${param_name})")
                query_params[param_name] = term
            
            query += "\nWHERE " + " OR ".join(conditions)
        
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
            results = self.store.structured_query(query, query_params)
            
            # Convert version labels back to semantic version format
            libraries = []
            for result in results:
                versions = []
                for version_label in result["versions"]:
                    # Convert version_4_28_0 back to 4.28.0
                    if version_label and version_label.startswith("version_"):
                        version_str = version_label[8:].replace("_", ".")
                        versions.append(version_str)
                
                libraries.append({
                    "name": result["name"],
                    "versions": sorted(versions)
                })
            
            data = {
                "libraries": libraries,
                "system_message": f"Found {len(libraries)} library/libraries."
            }
            return dict_to_xml_string(data, "list_libraries_response")
        except Exception as e:
            logging.error(f"Error listing libraries: {e}")
            data = {
                "libraries": [],
                "system_message": f"Error listing libraries: {str(e)}"
            }
            return dict_to_xml_string(data, "list_libraries_response")

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
        from .utils import _escape_regex_special_chars, _extract_partial_terms
        
        # Calculate skip value for pagination
        skip = (page - 1) * page_size
        
        # Process search terms: escape regex special chars and extract partial terms
        all_search_patterns = []
        for term in search_terms:
            escaped_term = _escape_regex_special_chars(term)
            partial_terms = _extract_partial_terms(escaped_term)
            for partial in partial_terms:
                # Match full term or term as part of path (after a dot)
                all_search_patterns.append(f"(^{partial}$|\\.")
        
        # Combine all patterns with OR (|)
        search_pattern = "|".join(all_search_patterns)
        
        query = """
        // Phase 1: Find the parent entity by direct name match
        OPTIONAL MATCH (parent1 {name: $parent_entity_name})
        WITH collect(parent1)[0] AS direct_parent
        
        // Phase 2: If no direct match, try EXPOSES/PUBLISHES relationship name
        OPTIONAL MATCH ()-[r:EXPOSES|PUBLISHES]->(parent2)
        WHERE direct_parent IS NULL AND r.name = $parent_entity_name
        WITH direct_parent, collect(parent2)[0] AS exposed_parent
        
        // Combine results - use whichever parent was found
        WITH COALESCE(direct_parent, exposed_parent) AS parent
        
        // Find all children recursively using variable-length path
        // Match 1: Search by child.__name__ and PUBLISHES relationship name
        MATCH path = (parent)-[:HAS_SUBMODULE|HAS_CLASS|HAS_METHOD|HAS_FUNCTION|PUBLISHES*]->(child)
        WHERE child.__name__ =~ $search_pattern 
           OR ANY(rel IN relationships(path) WHERE type(rel) = 'PUBLISHES' AND rel.name =~ $search_pattern)
        
        WITH DISTINCT child, parent
        
        // Match 2a: Direct EXPOSES relationships from parent
        OPTIONAL MATCH (parent)-[direct_exp:EXPOSES]->(direct_exposed_child)
        WHERE direct_exp.name =~ $search_pattern
        
        // Match 2b: Indirect EXPOSES relationships in parent's tree
        OPTIONAL MATCH (parent)-[:HAS_SUBMODULE|HAS_CLASS|HAS_METHOD|HAS_FUNCTION|PUBLISHES*]->(intermediate)-[exp:EXPOSES]->(exposed_child)
        WHERE exp.name =~ $search_pattern
        
        // Combine all matches
        WITH collect(DISTINCT child) + collect(DISTINCT direct_exposed_child) + collect(DISTINCT exposed_child) AS all_children
        UNWIND all_children AS child
        WHERE child IS NOT NULL
        
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
            results = self.store.structured_query(query, query_params)
            
            if not results:
                data = {
                    "definitions": [],
                    "next_page": None,
                    "current_page": page,
                    "total_results": 0,
                    "system_message": f"No definitions found matching search terms in '{parent_entity_name}'."
                }
                return dict_to_xml_string(data, "search_definitions_response")
            
            total_count = results[0]["total_count"]
            total_pages = (total_count + page_size - 1) // page_size
            has_next_page = page < total_pages
            
            definitions = []
            for result in results:
                definitions.append({
                    "fqn": result["fqn"],
                    "api_path": result["api_path"],
                    "definition_type": result["definition_type"],
                    "all_labels": result["all_labels"],
                    "signature": result["signature"]
                })
            
            data = {
                "definitions": definitions,
                "next_page": page + 1 if has_next_page else None,
                "current_page": page,
                "total_results": total_count,
                "system_message": f"Found {total_count} definitions. Showing page {page} of {total_pages}."
            }
            return dict_to_xml_string(data, "search_definitions_response")
            
        except Exception as e:
            logging.error(f"Error searching definitions: {e}")
            data = {
                "definitions": [],
                "next_page": None,
                "current_page": page,
                "total_results": 0,
                "system_message": f"Error searching definitions: {str(e)}"
            }
            return dict_to_xml_string(data, "search_definitions_response")
        
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
            
            // Phase 1: Try to match the entity by name directly
            OPTIONAL MATCH (end1 {name: entity_name})
            WITH entity_name, collect(end1)[0] AS direct_match
            
            // Phase 2: If no direct match, try EXPOSES/PUBLISHES relationship name
            OPTIONAL MATCH ()-[r:EXPOSES|PUBLISHES]->(end2)
            WHERE direct_match IS NULL AND r.name = entity_name
            WITH entity_name, direct_match, collect(end2)[0] AS exposed_match
            
            // Combine results from both phases
            WITH entity_name, COALESCE(direct_match, exposed_match) AS end
            
            // Get __init__ for CLASS entities
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
        
        results = self.store.structured_query(get_definitions_query, {"entity_names": entity_names})
        
        found_count = sum(1 for r in results if r['found'])
        data = {
            "definitions": results,
            "system_message": f"Retrieved {len(entity_names)} definition(s). Found {found_count} entities."
        }
        return dict_to_xml_string(data, "get_definitions_response")

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
            version_display = version[8:].replace("_", ".")
        else:
            version_label = f"version_{version.replace('.', '_').replace(':', '_').replace('-', '_')}"
            version_display = version
        
        # Handle depth: 0 means full depth
        actual_depth = 999 if depth == 0 else depth
        
        try:
            # Query to get hierarchical structure
            query = """
            // Find the root module with the specified version
            MATCH (root:ROOT_MODULE {name: $library_name})
            WHERE $version_label IN labels(root)
            
            // Get all descendants up to the specified depth
            CALL apoc.path.subgraphAll(root, {
                relationshipFilter: 'HAS_SUBMODULE>|HAS_CLASS>|HAS_METHOD>|HAS_FUNCTION>|EXPOSES>|PUBLISHES>',
                maxLevel: $depth
            })
            YIELD nodes, relationships
            
            // Return the structure
            RETURN 
                [n IN nodes | {
                    id: id(n),
                    name: n.name,
                    __name__: n.__name__,
                    shortest_call_path: n.shortest_call_path,
                    labels: labels(n)
                }] AS all_nodes,
                [r IN relationships | {
                    from_id: id(startNode(r)),
                    to_id: id(endNode(r)),
                    type: type(r)
                }] AS all_relationships
            """
            
            query_params = {
                "library_name": library_name,
                "version_label": version_label,
                "depth": actual_depth
            }
            
            results = self.store.structured_query(query, query_params)
            
            if not results or not results[0]["all_nodes"]:
                data = {
                    "library_name": library_name,
                    "version": version_display,
                    "depth": depth,
                    "entities": [],
                    "system_message": f"Library '{library_name}' version '{version_display}' not found."
                }
                return dict_to_xml_string(data, "library_map_response")
            
            all_nodes = results[0]["all_nodes"]
            all_relationships = results[0]["all_relationships"]
            
            # Build a map of node_id -> node data
            node_map = {node["id"]: node for node in all_nodes}
            
            # Build a map of parent_id -> list of child_ids
            children_map = {}
            for rel in all_relationships:
                parent_id = rel["from_id"]
                child_id = rel["to_id"]
                if parent_id not in children_map:
                    children_map[parent_id] = []
                children_map[parent_id].append(child_id)
            
            # Find the root node (the one that's not a child of anyone)
            root_nodes = [node for node in all_nodes if node["name"] == library_name]
            if not root_nodes:
                data = {
                    "library_name": library_name,
                    "version": version_display,
                    "depth": depth,
                    "entities": [],
                    "system_message": f"Root module '{library_name}' not found in results."
                }
                return dict_to_xml_string(data, "library_map_response")
            
            root_node = root_nodes[0]
            
            # Recursively build the hierarchy
            def build_hierarchy(node_id):
                node = node_map[node_id]
                entity = {
                    "all_labels": [label for label in node["labels"] if label not in [BASE_ENTITY_LABEL, BASE_NODE_LABEL]],
                    "fqn": node["name"],
                    "api_path": node.get("shortest_call_path", ""),
                    "children": []
                }
                
                # Add children
                if node_id in children_map:
                    for child_id in children_map[node_id]:
                        child_entity = build_hierarchy(child_id)
                        entity["children"].append(child_entity)
                
                return entity
            
            root_entity = build_hierarchy(root_node["id"])
            
            data = {
                "library_name": library_name,
                "version": version_display,
                "depth": depth,
                "entities": [root_entity],
                "system_message": f"Generated library map for '{library_name}' version '{version_display}'."
            }
            return dict_to_xml_string(data, "library_map_response")
            
        except Exception as e:
            logging.error(f"Error generating library map: {e}")
            data = {
                "library_name": library_name,
                "version": version_display,
                "depth": depth,
                "entities": [],
                "system_message": f"Error generating library map: {str(e)}"
            }
            return dict_to_xml_string(data, "library_map_response")
        
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
            # Normalize version strings
            if old_version.startswith("version_"):
                old_version_label = old_version
                old_version_display = old_version[8:].replace("_", ".")
            else:
                old_version_label = f"version_{old_version.replace('.', '_').replace(':', '_').replace('-', '_')}"
                old_version_display = old_version
            
            if new_version.startswith("version_"):
                new_version_label = new_version
                new_version_display = new_version[8:].replace("_", ".")
            else:
                new_version_label = f"version_{new_version.replace('.', '_').replace(':', '_').replace('-', '_')}"
                new_version_display = new_version
            
            # Query to get both versions' hierarchies
            query = """
            // Get old version hierarchy
            MATCH (old_root {name: $parent_entity})
            WHERE $old_version_label IN labels(old_root)
            CALL apoc.path.subgraphAll(old_root, {
                relationshipFilter: 'HAS_SUBMODULE>|HAS_CLASS>|HAS_METHOD>|HAS_FUNCTION>|EXPOSES>|PUBLISHES>'
            })
            YIELD nodes AS old_nodes, relationships AS old_rels
            
            // Get new version hierarchy
            MATCH (new_root {name: $parent_entity})
            WHERE $new_version_label IN labels(new_root)
            CALL apoc.path.subgraphAll(new_root, {
                relationshipFilter: 'HAS_SUBMODULE>|HAS_CLASS>|HAS_METHOD>|HAS_FUNCTION>|EXPOSES>|PUBLISHES>'
            })
            YIELD nodes AS new_nodes, relationships AS new_rels
            
            RETURN 
                [n IN old_nodes | {
                    id: id(n),
                    name: n.name,
                    __name__: n.__name__,
                    shortest_call_path: n.shortest_call_path,
                    labels: labels(n),
                    signature: n.signature,
                    content_hash: n.content_hash
                }] AS old_all_nodes,
                [r IN old_rels | {
                    from_id: id(startNode(r)),
                    to_id: id(endNode(r))
                }] AS old_all_relationships,
                [n IN new_nodes | {
                    id: id(n),
                    name: n.name,
                    __name__: n.__name__,
                    shortest_call_path: n.shortest_call_path,
                    labels: labels(n),
                    signature: n.signature,
                    content_hash: n.content_hash
                }] AS new_all_nodes,
                [r IN new_rels | {
                    from_id: id(startNode(r)),
                    to_id: id(endNode(r))
                }] AS new_all_relationships
            """
            
            query_params = {
                "parent_entity": parent_entity,
                "old_version_label": old_version_label,
                "new_version_label": new_version_label
            }
            
            results = self.store.structured_query(query, query_params)
            
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
                    "system_message": f"Entity '{parent_entity}' not found in one or both versions."
                }
                return dict_to_xml_string(data, "get_version_diff_response")
            
            result = results[0]
            old_all_nodes = result.get("old_all_nodes", [])
            old_all_relationships = result.get("old_all_relationships", [])
            new_all_nodes = result.get("new_all_nodes", [])
            new_all_relationships = result.get("new_all_relationships", [])
            
            # Build maps for easier comparison
            old_node_map = {node["name"]: node for node in old_all_nodes}
            new_node_map = {node["name"]: node for node in new_all_nodes}
            
            # Build parent-child relationships
            old_children_map = {}
            for rel in old_all_relationships:
                parent_id = rel["from_id"]
                child_id = rel["to_id"]
                if parent_id not in old_children_map:
                    old_children_map[parent_id] = []
                old_children_map[parent_id].append(child_id)
            
            new_children_map = {}
            for rel in new_all_relationships:
                parent_id = rel["from_id"]
                child_id = rel["to_id"]
                if parent_id not in new_children_map:
                    new_children_map[parent_id] = []
                new_children_map[parent_id].append(child_id)
            
            # Build comparison data
            added = []
            removed = []
            modified = []
            unchanged = []
            
            diff_lines = []
            
            # Find added, removed, and modified entities
            all_names = set(old_node_map.keys()) | set(new_node_map.keys())
            
            for name in all_names:
                old_node = old_node_map.get(name)
                new_node = new_node_map.get(name)
                
                if old_node and not new_node:
                    removed.append(name)
                    if old_node.get("signature"):
                        diff_lines.append(f"- {old_node.get('shortest_call_path', name)}: {old_node['signature']}")
                elif new_node and not old_node:
                    added.append(name)
                    if new_node.get("signature"):
                        diff_lines.append(f"+ {new_node.get('shortest_call_path', name)}: {new_node['signature']}")
                elif old_node and new_node:
                    # Check if modified
                    if old_node.get("content_hash") != new_node.get("content_hash"):
                        modified.append(name)
                        if old_node.get("signature") or new_node.get("signature"):
                            old_sig = old_node.get("signature", "")
                            new_sig = new_node.get("signature", "")
                            if old_sig != new_sig:
                                path = new_node.get('shortest_call_path', name)
                                if old_sig:
                                    diff_lines.append(f"- {path}: {old_sig}")
                                if new_sig:
                                    diff_lines.append(f"+ {path}: {new_sig}")
                    else:
                        unchanged.append(name)
            
            # Build hierarchical entity structure (showing changes)
            def build_diff_hierarchy(node_name, old_map, new_map, old_children, new_children):
                old_node = old_map.get(node_name)
                new_node = new_map.get(node_name)
                
                if not old_node and not new_node:
                    return None
                
                # Determine status
                if old_node and not new_node:
                    status = "removed"
                    node_data = old_node
                elif new_node and not old_node:
                    status = "added"
                    node_data = new_node
                elif old_node.get("content_hash") != new_node.get("content_hash"):
                    status = "modified"
                    node_data = new_node
                else:
                    status = "unchanged"
                    node_data = new_node
                
                entity = {
                    "status": status,
                    "all_labels": [label for label in node_data["labels"] if label not in [BASE_ENTITY_LABEL, BASE_NODE_LABEL]],
                    "fqn": node_data["name"],
                    "api_path": node_data.get("shortest_call_path", ""),
                    "children": []
                }
                
                # Add signature diff if changed
                if status == "modified":
                    old_sig = old_node.get("signature", "")
                    new_sig = new_node.get("signature", "")
                    if old_sig != new_sig:
                        entity["old_signature"] = old_sig
                        entity["new_signature"] = new_sig
                
                # Get children from both versions
                old_child_ids = old_children.get(old_node["id"], []) if old_node else []
                new_child_ids = new_children.get(new_node["id"], []) if new_node else []
                
                # Build child name sets
                old_child_names = {old_all_nodes[i]["name"] for i in range(len(old_all_nodes)) if old_all_nodes[i]["id"] in old_child_ids}
                new_child_names = {new_all_nodes[i]["name"] for i in range(len(new_all_nodes)) if new_all_nodes[i]["id"] in new_child_ids}
                
                all_child_names = old_child_names | new_child_names
                
                for child_name in sorted(all_child_names):
                    child_entity = build_diff_hierarchy(child_name, old_map, new_map, old_children, new_children)
                    if child_entity:
                        entity["children"].append(child_entity)
                
                return entity
            
            root_entity = build_diff_hierarchy(parent_entity, old_node_map, new_node_map, old_children_map, new_children_map)
            
            data = {
                "entity_name": parent_entity,
                "old_version": old_version_display,
                "new_version": new_version_display,
                "diff": "\n".join(diff_lines),
                "entities": [root_entity] if root_entity else [],
                "summary": {
                    "added": len(added),
                    "removed": len(removed),
                    "modified": len(modified),
                    "unchanged": len(unchanged)
                },
                "system_message": f"Generated version diff for '{parent_entity}' between {old_version_display} and {new_version_display}."
            }
            return dict_to_xml_string(data, "get_version_diff_response")
            
        except Exception as e:
            logging.error(f"Error generating version diff: {e}")
            data = {
                "entity_name": parent_entity,
                "old_version": old_version,
                "new_version": new_version,
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
            return dict_to_xml_string(data, "get_version_diff_response")
