"""
Tool methods for COMStore that return XML-formatted responses for agent/MCP use.
These methods are separated from the main COMStore class for better organization.
"""
from typing import Optional
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

    def retrieve_relevant_distribution_packages(self, query: str, top_k: int) -> str:
        """
        Retrieve all relevant distribution packages based on the query, using similarity search, and store them for pagination.

        Args:
            query (str): The query string.
            top_k (int): The number of results to return. Defaults to 5.

        Returns:
            str: XML-formatted string containing:
                - results: Top k relevant distribution packages based on the query, each with:
                    - name (str): Package name
                    - score (float): Similarity score
                    - summary (str): Package summary
                - query_info: Information about the query
                - system_message (str): Informational message
        """
        # Clean input params
        top_k = int(top_k)

        # Create a Cypher query to return all distribution packages based on similarity to the query
        retrieve_distribution_packages_query = """
            MATCH (m:DISTRIBUTION_PACKAGE)
            WHERE m.embedding IS NOT NULL
            WITH m,
                vector.similarity.cosine(m.embedding, $query_vector) AS similarity
            ORDER BY similarity DESC
            RETURN m.name AS name, similarity AS score, m.summary AS summary
        """

        query_params = {
            "query_vector": Settings.embed_model.get_query_embedding(query)
        }

        # Execute the query to retrieve all relevant distribution packages
        results = self.store.database_query(retrieve_distribution_packages_query, query_params)

        # Store the results
        self.store._distribution_packages = results
        self.store._distribution_packages_index = top_k
        self.store._last_distribution_packages_query = {"query": query, "top_k": top_k}

        data = {
            "results": self.store._distribution_packages[:top_k],
            "query_info": {
                "query": query,
                "top_k": top_k,
                "total_found": len(results)
            },
            "system_message": f"Retrieved top {top_k} relevant distribution packages from {len(results)} total matches."
        }
        return dict_to_xml_string(data, "retrieve_relevant_distribution_packages_response")
    
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
            MATCH (parent {name: $parent_name})-[:HAS_SUBMODULE|HAS_CLASS|HAS_METHOD|HAS_FUNCTION|EXPOSES|PUBLISHES|PROVIDES|EXPOSES_ALL|PUBLISHES_ALL]->(child)
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
            from_ (str): "DISTRIBUTION_PACKAGE" or "CHILDREN", indicating which list to retrieve from.
            top_k (int): The number of entities to retrieve.

        Returns:
            str: XML-formatted string containing:
                - results: The next top_k entities
                - pagination_info: Information about pagination status
                - system_message (str): Informational message
        """
        top_k = int(top_k)
        if from_ == "DISTRIBUTION_PACKAGE":
            if self.store._distribution_packages == None or self.store._distribution_packages_index == -1:
                data = {
                    "results": [],
                    "pagination_info": {
                        "source": "DISTRIBUTION_PACKAGE",
                        "error": "No DISTRIBUTION_PACKAGE query has been made yet or all entities have been retrieved."
                    },
                    "system_message": "No DISTRIBUTION_PACKAGE query has been made yet or all entities have been retrieved."
                }
                return dict_to_xml_string(data, "next_entities_response")
            
            start_index = self.store._distribution_packages_index
            end_index = min(start_index + top_k, len(self.store._distribution_packages))
            entities = self.store._distribution_packages[start_index:end_index]
            self.store._distribution_packages_index = end_index
            all_retrieved = end_index == len(self.store._distribution_packages)
            
            if all_retrieved:
                self.store._distribution_packages_index = -1
                self.store._last_distribution_packages_query = {}
            
            data = {
                "results": entities,
                "pagination_info": {
                    "source": "DISTRIBUTION_PACKAGE",
                    "start_index": start_index,
                    "end_index": end_index,
                    "has_more": not all_retrieved,
                    "all_retrieved": all_retrieved
                },
                "system_message": f"Retrieved entities {start_index+1} to {end_index}." + 
                                 (" ALL RELEVANT DISTRIBUTION PACKAGES RETRIEVED." if all_retrieved else f" {len(self.store._distribution_packages) - end_index} more available.")
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
            raise ValueError("`from` must be either 'DISTRIBUTION_PACKAGE' or 'CHILDREN'")

    def list_libraries(
            self,
            search_terms = None,
        ) -> str:
        """
        Get a list of all ROOT_MODULE entities (libraries) in the knowledge graph.
        
        Args:
            search_terms (str | List[str], optional): Search terms to filter libraries by name, using case-insensitive partial matching. If string, will be split by commas and each term trimmed. Defaults to None.

        Returns:
            str: XML-formatted string containing:
                - libraries: A list of library objects, each containing:
                    - name (str): The name of the library/root module
                    - versions (List[str]): List of version labels available for the library
                - system_message (str): Informational message about the results
        """
        # Normalize search_terms: convert string to list if needed
        if search_terms:
            if isinstance(search_terms, str):
                search_terms = [term.strip() for term in search_terms.split(',') if term.strip()]
        
        # Build the query with optional filtering and version aggregation
        query = """
        MATCH (lib:DISTRIBUTION_PACKAGE)
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
        library: str,
        search_terms,
        version: str,
        parent_filters: str = None,
        page: int = 1,
        page_size: int = 10
    ) -> str:
        """
        Search for code definitions (functions, classes, methods) within a provided library.
        Acts like VS Code's file search (Cmd/Ctrl + P) within a project.
        *Note*: All params are case-sensitive.
        
        Args:
            library (str): Name of the library to search within. Must be a simple name.
            search_terms (str | List[str]): Simple names to search for.
            version (str): Version of the library to search within.
            parent_filters (str | List[str], optional): Optional parent path filters. Can contain sub-path names ('a.b', 'x.y'). If string, will be split by commas and each filter trimmed. Defaults to None.
            page (int): Page number starting from 1. Default is 1.
            page_size (int): Number of results per page. Default is 10.
        
        Returns:
            str: XML-formatted string containing:
                - definitions: Array of matching code definitions, each containing:
                    - fqn (str): Fully qualified name
                    - labels (List[str]): Base entity labels (excluding version labels)
                - next_page (int | None): Next page number
                - current_page (int): Current page number
                - total_results (int): Total number of matching results
                - system_message (str): Informational message
        """
        from .utils import _escape_regex_special_chars
        
        # Normalize library: must be simple name
        if '.' in library:
            data = {
                "definitions": [],
                "system_message": "Library name must be a simple name (no dots)."
            }
            return dict_to_xml_string(data, "search_definitions_response")

        # Normalize search_terms: convert string to list if needed
        if isinstance(search_terms, str):
            search_terms = [term.strip() for term in search_terms.split(',') if term.strip()]
        
        # Filter out terms with dots (only simple names allowed)
        search_terms = [term for term in search_terms if '.' not in term]
        
        if not search_terms:
            data = {
                "definitions": [],
                "next_page": None,
                "current_page": page,
                "total_results": 0,
                "system_message": "No valid simple names found in search terms."
            }
            return dict_to_xml_string(data, "search_definitions_response")
        
        # Normalize version string if provided
        version_label = None
        if version:
            if version.startswith("version_"):
                version_label = version
            else:
                version_label = f"version_{version.replace('.', '_').replace(':', '_').replace('-', '_')}"
        
        # Construct Cypher regex
        escaped_lib = _escape_regex_special_chars(library)
        escaped_terms = [_escape_regex_special_chars(term) for term in search_terms]
        terms_pattern = f"({'|'.join(escaped_terms)})"
        
        if parent_filters:
            if isinstance(parent_filters, str):
                parent_filters = [f.strip() for f in parent_filters.split(',') if f.strip()]
            escaped_filters = [_escape_regex_special_chars(f) for f in parent_filters]
            filters_pattern = f"({'|'.join(escaped_filters)})"
            # Pattern: ^library(?:\..*filters)?.*\.\.search_term$
            pattern_str = f"^{escaped_lib}(?:\\..*{filters_pattern})?.*\\.{terms_pattern}$"
        else:
            # Pattern: ^library.*\.search_term$
            pattern_str = f"^{escaped_lib}.*\\.{terms_pattern}$"
            
        cypher_regex = pattern_str
        
        skip = (page - 1) * page_size
        
        query = """
        CALL {
            MATCH (n:__Entity__)
            WHERE n.name =~ $cypher_regex
              AND ($version_label IS NULL OR $version_label IN labels(n))
              AND (ANY(lbl IN labels(n) WHERE lbl IN ['FUNCTION', 'CLASS', 'METHOD', 'MODULE', 'DISTRIBUTION_PACKAGE', 'IMPORT_PACKAGE']))
            RETURN n.name AS fqn, [lbl IN labels(n) WHERE NOT lbl STARTS WITH 'version_'] AS labels

            UNION

            MATCH ()-[r:EXPOSES|PUBLISHES|PROVIDES]->(target)
            WHERE r.name =~ $cypher_regex
              AND ($version_label IS NULL OR $version_label IN r.versions)
              AND (ANY(lbl IN labels(target) WHERE lbl IN ['FUNCTION', 'CLASS', 'METHOD', 'MODULE', 'DISTRIBUTION_PACKAGE', 'IMPORT_PACKAGE']))
            RETURN r.name AS fqn, [lbl IN labels(target) WHERE NOT lbl STARTS WITH 'version_'] AS labels

            UNION

            MATCH path = (child:CLASS)-[:INHERITS]->()-[:INHERITS|HAS_METHOD|HAS_CLASS*]->(member)
            WHERE child.name STARTS WITH $library
              AND ($version_label IS NULL OR $version_label IN labels(child))
              AND NOT 'PRIVATE' IN labels(member)
              AND (member:FUNCTION OR member:CLASS OR member:METHOD)
              AND NOT type(last(relationships(path))) = 'INHERITS'
            
            WITH child, member, path,
                 endNode(head([r IN relationships(path) WHERE type(r) <> 'INHERITS'])) AS first_member,
                 reduce(s = child.name, r IN relationships(path) | 
                    CASE type(r)
                        WHEN 'INHERITS' THEN s
                        ELSE s + "." + endNode(r).__name__
                    END
                 ) AS fqn
            
            WHERE fqn =~ $cypher_regex
              AND NOT EXISTS {
                  MATCH (child)-[:HAS_METHOD|HAS_CLASS]->(override)
                  WHERE override.__name__ = first_member.__name__
                    AND (
                        (
                            'CLASS' IN labels(first_member) 
                            AND 'CLASS' IN labels(override)
                        )
                        OR
                        (
                            'METHOD' IN labels(first_member)
                            AND 'METHOD' IN labels(override)
                            AND (
                                'DUNDER' IN labels(first_member)
                                OR
                                (
                                    NOT 'DUNDER' IN labels(first_member)
                                    AND EXISTS {
                                        MATCH (override)-[:HAS_SOURCE]->(os:SOURCE),
                                              (first_member)-[:HAS_SOURCE]->(ms:SOURCE)
                                        WHERE os.signature = ms.signature
                                    }
                                )
                            )
                        )
                    )
              }
            
            WITH fqn, collect({member: member, depth: length(path)}) as candidates
            UNWIND candidates as c1
            WITH fqn, candidates, c1
            WHERE NONE(c2 IN candidates WHERE 
                c2.depth < c1.depth 
                AND (
                    (
                        'CLASS' IN labels(c1.member)
                        AND 'CLASS' IN labels(c2.member)
                    )
                    OR
                    (
                        'METHOD' IN labels(c1.member)
                        AND 'METHOD' IN labels(c2.member)
                        AND (
                            'DUNDER' IN labels(c1.member)
                            OR
                            (
                                NOT 'DUNDER' IN labels(c1.member)
                                AND EXISTS {
                                    MATCH (m2)-[:HAS_SOURCE]->(s2:SOURCE),
                                          (m1)-[:HAS_SOURCE]->(s1:SOURCE)
                                    WHERE m2 = c2.member AND m1 = c1.member AND s2.signature = s1.signature
                                }
                            )
                        )
                    )
                )
            )
            
            RETURN fqn, [lbl IN labels(c1.member) WHERE NOT lbl STARTS WITH 'version_'] AS labels
        }
        WITH fqn, labels
        WITH collect({fqn: fqn, labels: labels}) AS all_results
        WITH all_results, size(all_results) AS total_count
        UNWIND all_results AS result
        WITH result, total_count
        SKIP $skip
        LIMIT $page_size
        RETURN 
            result.fqn AS fqn,
            result.labels AS labels,
            total_count
        """
        
        # Shadowing Logic Explanation:
        # 1. Head Shadowing (Namespace Shadowing):
        #    - Handled by `first_member` and the `NOT EXISTS` clause.
        #    - Scenario: Child.Nested shadows Parent.Nested.
        #    - If Child.Nested exists, we must NOT access Parent.Nested.method, even if Child.Nested is empty.
        #    - The `first_member` identifies the entry point of the inherited path (e.g., Parent.Nested).
        #    - We check if the Child has a direct member with the same name (Child.Nested).
        #    - If so, we discard the path from Parent.Nested.
        #
        # 2. Tail Shadowing (Deep Inheritance / Overriding):
        #    - Handled by the `NONE(...)` filter on `candidates`.
        #    - Scenario: Child inherits from Parent, Parent inherits from Grandparent. Both define `method`.
        #    - We get two paths to `method` (one via Parent, one via Grandparent).
        #    - We group by FQN and filter candidates.
        #    - We keep a candidate only if there is NO other candidate that is "closer" (shorter depth) AND has the same signature.
        #    - If signatures differ, we keep both (Overloading).
        #
        # 3. Versioning on Inherited Members:
        #    - We do NOT filter inherited members by version.
        #    - We only enforce version on the `child` class (the entry point).
        #    - This ensures we find members inherited from base classes that might be version-agnostic or from other libraries.
        
        query_params = {
            "cypher_regex": cypher_regex,
            "version_label": version_label,
            "skip": skip,
            "page_size": page_size,
            "library": library
        }
        
        try:
            results = self.store.structured_query(query, query_params)
            
            if not results:
                data = {
                    "definitions": [],
                    "next_page": None,
                    "current_page": page,
                    "total_results": 0,
                    "system_message": f"No definitions found matching search terms in library '{library}'. Try using more lenient search terms, or use 'list_libraries' to see available libraries, or 'library_map' to see the full structure of a library."
                }
                return dict_to_xml_string(data, "search_definitions_response")
            
            total_count = results[0]["total_count"]
            total_pages = (total_count + page_size - 1) // page_size
            has_next_page = page < total_pages
            
            definitions = []
            for result in results:
                definitions.append({
                    "fqn": result["fqn"],
                    "labels": result["labels"]
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
        
    def get_definitions(self, entity_names, version: Optional[str] = None) -> str:
        """
        Get detailed definition information for one or more entities.

        Args:
            entity_names (str | List[str]): Entity names to retrieve. If string, will be split by commas and each name trimmed.
            version (str, optional): Version of the entities to retrieve (e.g., "4.28")

        Returns:
            str: XML-formatted string containing:
                - definitions: List of entity definitions, each containing:
                    - query_name (str): The queried entity name
                    - fqn (str): Fully qualified name
                    - docstring (str): Entity docstring
                    - all_labels (List[str]): All labels
                    - signature (str): Entity signature
                    - resolved_sig (str): Resolved signature from type hints
                    - found (bool): Whether the entity was found
                - system_message (str): Informational message
        """
        # Normalize entity_names: convert string to list if needed
        if isinstance(entity_names, str):
            entity_names = [name.strip() for name in entity_names.split(',') if name.strip()]
        
        # Normalize version string if provided
        version_label = None
        if version:
            if version.startswith("version_"):
                version_label = version
            else:
                version_label = f"version_{version.replace('.', '_').replace(':', '_').replace('-', '_')}"
        
        # If version specified, check if entities with that version exist
        if version_label:
            check_query = f"""
            UNWIND $entity_names AS entity_name
            OPTIONAL MATCH (versioned1:`{version_label}` {{name: entity_name}})
            WITH entity_name, collect(versioned1)[0] AS versioned_direct
            OPTIONAL MATCH ()-[r:EXPOSES|PUBLISHES|INHERITS_METHOD|INHERITS_CLASS]->(versioned2:`{version_label}`)
            WHERE versioned_direct IS NULL AND r.name = entity_name
            WITH entity_name, versioned_direct, collect(versioned2)[0] AS versioned_exposed
            WITH entity_name, COALESCE(versioned_direct, versioned_exposed) AS versioned_entity
            OPTIONAL MATCH (any_entity {{name: entity_name}})
            RETURN entity_name,
                   versioned_entity IS NOT NULL AS version_exists,
                   any_entity IS NOT NULL AS entity_exists,
                   [label IN labels(any_entity) WHERE label STARTS WITH 'version_'] AS available_versions
            """
            
            check_results = self.store.structured_query(check_query, {"entity_names": entity_names})
            
            # Check if any entities don't have the requested version
            entities_without_version = []
            for check_result in check_results:
                if not check_result["version_exists"] and check_result["entity_exists"]:
                    available = [v[8:].replace("_", ".") for v in check_result["available_versions"]]
                    entities_without_version.append({
                        "entity_name": check_result["entity_name"],
                        "available_versions": available
                    })
            
            if entities_without_version:
                data = {
                    "definitions": [],
                    "entities_without_version": entities_without_version,
                    "system_message": f"Some entities not found with version '{version}'. Check entities_without_version for available versions."
                }
                return dict_to_xml_string(data, "get_definitions_response")
        
        # Build query with version filtering in MATCH clause
        if version_label:
            get_definitions_query = f"""
                UNWIND $entity_names AS entity_name
                OPTIONAL MATCH (end1:`{version_label}` {{name: entity_name}})
                WITH entity_name, collect(end1)[0] AS direct_match
                OPTIONAL MATCH ()-[r:EXPOSES|PUBLISHES|INHERITS_METHOD|INHERITS_CLASS]->(end2:`{version_label}`)
                WHERE direct_match IS NULL AND r.name = entity_name
                WITH entity_name, direct_match, collect(end2)[0] AS exposed_match
                WITH entity_name, COALESCE(direct_match, exposed_match) AS end
                OPTIONAL MATCH (end)-[:HAS_SOURCE]->(source:SOURCE:`{version_label}`)
                WITH entity_name, end, collect(source)[0] AS source
            """
        else:
            get_definitions_query = """
                UNWIND $entity_names AS entity_name
                OPTIONAL MATCH (end1 {name: entity_name})
                WITH entity_name, collect(end1)[0] AS direct_match
                OPTIONAL MATCH ()-[r:EXPOSES|PUBLISHES|INHERITS_METHOD|INHERITS_CLASS]->(end2)
                WHERE direct_match IS NULL AND r.name = entity_name
                WITH entity_name, direct_match, collect(end2)[0] AS exposed_match
                WITH entity_name, COALESCE(direct_match, exposed_match) AS end
                OPTIONAL MATCH (end)-[:HAS_SOURCE]->(source:SOURCE)
                WITH entity_name, end, collect(source)[0] AS source
            """
        
        if version_label:
            get_definitions_query += f"""
                OPTIONAL MATCH (end)-[:HAS_RESOLVED_SIGNATURE]->(resolved_sig:RESOLVED_SIGNATURE:`{version_label}`)
                WITH entity_name, end, source, collect(resolved_sig)[0] AS resolved_sig
                OPTIONAL MATCH (end)-[:HAS_METHOD]->(init:`{version_label}` {{__name__: "__init__"}})
                WHERE "CLASS" IN labels(end)
                WITH entity_name, end, source, resolved_sig, collect(init)[0] AS init
                OPTIONAL MATCH (init)-[:HAS_SOURCE]->(init_source:SOURCE:`{version_label}`)
                WITH entity_name, end, source, resolved_sig, init, collect(init_source)[0] AS init_source
                OPTIONAL MATCH (init)-[:HAS_RESOLVED_SIGNATURE]->(init_resolved_sig:RESOLVED_SIGNATURE:`{version_label}`)
                WITH entity_name, end, source, resolved_sig, init, init_source, collect(init_resolved_sig)[0] AS init_resolved_sig
            """
        else:
            get_definitions_query += """
                OPTIONAL MATCH (end)-[:HAS_RESOLVED_SIGNATURE]->(resolved_sig:RESOLVED_SIGNATURE)
                WITH entity_name, end, source, collect(resolved_sig)[0] AS resolved_sig
                OPTIONAL MATCH (end)-[:HAS_METHOD]->(init {__name__: "__init__"})
                WHERE "CLASS" IN labels(end)
                WITH entity_name, end, source, resolved_sig, collect(init)[0] AS init
                OPTIONAL MATCH (init)-[:HAS_SOURCE]->(init_source:SOURCE)
                WITH entity_name, end, source, resolved_sig, init, collect(init_source)[0] AS init_source
                OPTIONAL MATCH (init)-[:HAS_RESOLVED_SIGNATURE]->(init_resolved_sig:RESOLVED_SIGNATURE)
                WITH entity_name, end, source, resolved_sig, init, init_source, collect(init_resolved_sig)[0] AS init_resolved_sig
            """
        
        get_definitions_query += """
            RETURN 
                entity_name AS query_name,
                CASE WHEN end IS NOT NULL THEN end.name ELSE "" END AS fqn,
                CASE WHEN end IS NOT NULL THEN source.docstring ELSE "" END AS docstring,
                CASE WHEN end IS NOT NULL THEN labels(end) ELSE [] END AS all_labels,
                CASE 
                    WHEN end IS NULL THEN ""
                    WHEN "CLASS" IN labels(end) AND init_source IS NOT NULL THEN init_source.signature
                    WHEN source IS NOT NULL THEN source.signature
                    ELSE ""
                END AS signature,
                CASE 
                    WHEN end IS NULL THEN ""
                    WHEN "CLASS" IN labels(end) AND init_resolved_sig IS NOT NULL THEN init_resolved_sig.value
                    WHEN resolved_sig IS NOT NULL THEN resolved_sig.value
                    ELSE ""
                END AS resolved_sig,
                end IS NOT NULL AS found
        """
        
        query_params = {"entity_names": entity_names}
        
        results = self.store.structured_query(get_definitions_query, query_params)
        
        found_count = sum(1 for r in results if r['found'])
        
        if found_count == 0:
            system_message = f"None of the requested entities ({', '.join(entity_names)}) could be found. If you are unsure of the exact names, try using the 'search_definitions' tool to find them."
            definitions = []
        else:
            system_message = f"Retrieved {len(entity_names)} definition(s). Found {found_count} entities."
            definitions = results

        data = {
            "definitions": definitions,
            "system_message": system_message
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
            version (str): Version of the library (e.g., "4.28")
            depth (int): Directory/entity traversal depth. 0 = full depth (default), >0 = limited depth.
        
        Returns:
            str: XML-formatted string containing:
                - library_name (str): Name of the library
                - version (str): Version being mapped
                - depth (int): Depth used for traversal (0 = full)
                - entities: Nested hierarchy of all entities, each containing:
                    - all_labels (List[str]): All labels associated with the entity
                    - fqn (str): Fully qualified name (entity.name)
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
            # Check if library with version exists
            check_query = f"""
            OPTIONAL MATCH (versioned_lib:`{version_label}` {{name: $library_name}})
            OPTIONAL MATCH (any_lib {{name: $library_name}})
            RETURN versioned_lib IS NOT NULL AS version_exists,
                   any_lib IS NOT NULL AS library_exists,
                   [label IN labels(any_lib) WHERE label STARTS WITH 'version_'] AS available_versions
            LIMIT 1
            """
            
            check_result = self.store.structured_query(check_query, {"library_name": library_name})
            
            if check_result and not check_result[0]["version_exists"]:
                if check_result[0]["library_exists"]:
                    # Library exists but not with this version
                    available = [v[8:].replace("_", ".") for v in check_result[0]["available_versions"]]
                    data = {
                        "library_name": library_name,
                        "version": version_display,
                        "depth": depth,
                        "entities": [],
                        "available_versions": available,
                        "system_message": f"Library '{library_name}' not found with version '{version_display}'. Available versions: {', '.join(available)}"
                    }
                    return dict_to_xml_string(data, "library_map_response")
            
            # Query to get hierarchical structure with version in MATCH
            query = f"""
            MATCH (root:`{version_label}` {{name: $library_name}})
            CALL apoc.path.subgraphAll(root, {{
                relationshipFilter: 'HAS_SUBMODULE>|HAS_CLASS>|HAS_METHOD>|HAS_FUNCTION>|EXPOSES>|PUBLISHES>|INHERITS_METHOD>|INHERITS_CLASS>|PROVIDES>',
                maxLevel: $depth
            }})
            YIELD nodes, relationships
            RETURN 
                [n IN nodes | {{
                    id: id(n),
                    name: n.name,
                    __name__: n.__name__,
                    labels: labels(n)
                }}] AS all_nodes,
                [r IN relationships | {{
                    from_id: id(startNode(r)),
                    to_id: id(endNode(r)),
                    type: type(r)
                }}] AS all_relationships
            """
            
            query_params = {
                "library_name": library_name,
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
            old_version (str): The old version identifier (e.g., "4.28" ).
            new_version (str): The new version identifier (e.g., "4.29" ).

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
            
            # Check if entity exists with both versions
            check_query = f"""
            OPTIONAL MATCH (old_ver:`{old_version_label}` {{name: $parent_entity}})
            OPTIONAL MATCH (new_ver:`{new_version_label}` {{name: $parent_entity}})
            OPTIONAL MATCH (any_entity {{name: $parent_entity}})
            RETURN old_ver IS NOT NULL AS old_version_exists,
                   new_ver IS NOT NULL AS new_version_exists,
                   any_entity IS NOT NULL AS entity_exists,
                   [label IN labels(any_entity) WHERE label STARTS WITH 'version_'] AS available_versions
            LIMIT 1
            """
            
            check_result = self.store.structured_query(check_query, {"parent_entity": parent_entity})
            
            if check_result:
                if not check_result[0]["old_version_exists"] or not check_result[0]["new_version_exists"]:
                    if check_result[0]["entity_exists"]:
                        available = [v[8:].replace("_", ".") for v in check_result[0]["available_versions"]]
                        missing = []
                        if not check_result[0]["old_version_exists"]:
                            missing.append(old_version_display)
                        if not check_result[0]["new_version_exists"]:
                            missing.append(new_version_display)
                        
                        data = {
                            "entity_name": parent_entity,
                            "old_version": old_version_display,
                            "new_version": new_version_display,
                            "diff": "",
                            "entities": [],
                            "available_versions": available,
                            "summary": {
                                "added": 0,
                                "removed": 0,
                                "modified": 0,
                                "unchanged": 0
                            },
                            "system_message": f"Entity '{parent_entity}' not found with version(s): {', '.join(missing)}. Available versions: {', '.join(available)}"
                        }
                        return dict_to_xml_string(data, "get_version_diff_response")
            
            # Query to get both versions' hierarchies with version in MATCH clause
            query = f"""
            MATCH (old_root:`{old_version_label}` {{name: $parent_entity}})
            CALL apoc.path.subgraphAll(old_root, {{
                relationshipFilter: 'HAS_SUBMODULE>|HAS_CLASS>|HAS_METHOD>|HAS_FUNCTION>|EXPOSES>|PUBLISHES>|INHERITS_METHOD>|INHERITS_CLASS>'
            }})
            YIELD nodes AS old_nodes, relationships AS old_rels
            MATCH (new_root:`{new_version_label}` {{name: $parent_entity}})
            CALL apoc.path.subgraphAll(new_root, {{
                relationshipFilter: 'HAS_SUBMODULE>|HAS_CLASS>|HAS_METHOD>|HAS_FUNCTION>|EXPOSES>|PUBLISHES>|INHERITS_METHOD>|INHERITS_CLASS>'
            }})
            YIELD nodes AS new_nodes, relationships AS new_rels
            WITH old_nodes, old_rels, new_nodes, new_rels
            UNWIND old_nodes AS old_n
            OPTIONAL MATCH (old_n)-[:HAS_SOURCE]->(old_source:SOURCE)
            WITH collect({{
                id: id(old_n),
                name: old_n.name,
                __name__: old_n.__name__,
                labels: labels(old_n),
                signature: old_source.signature,
                content_hash: old_n.content_hash
            }}) AS old_all_nodes, old_rels, new_nodes, new_rels
            UNWIND new_nodes AS new_n
            OPTIONAL MATCH (new_n)-[:HAS_SOURCE]->(new_source:SOURCE)
            WITH old_all_nodes, old_rels, new_rels, collect({{
                id: id(new_n),
                name: new_n.name,
                __name__: new_n.__name__,
                labels: labels(new_n),
                signature: new_source.signature,
                content_hash: new_n.content_hash
            }}) AS new_all_nodes
            RETURN 
                old_all_nodes,
                [r IN old_rels | {{
                    from_id: id(startNode(r)),
                    to_id: id(endNode(r))
                }}] AS old_all_relationships,
                new_all_nodes,
                [r IN new_rels | {{
                    from_id: id(startNode(r)),
                    to_id: id(endNode(r))
                }}] AS new_all_relationships
            """
            
            query_params = {
                "parent_entity": parent_entity
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
                        diff_lines.append(f"- {name}: {old_node['signature']}")
                elif new_node and not old_node:
                    added.append(name)
                    if new_node.get("signature"):
                        diff_lines.append(f"+ {name}: {new_node['signature']}")
                elif old_node and new_node:
                    # Check if modified
                    if old_node.get("content_hash") != new_node.get("content_hash"):
                        modified.append(name)
                        if old_node.get("signature") or new_node.get("signature"):
                            old_sig = old_node.get("signature", "")
                            new_sig = new_node.get("signature", "")
                            if old_sig != new_sig:
                                if old_sig:
                                    diff_lines.append(f"- {name}: {old_sig}")
                                if new_sig:
                                    diff_lines.append(f"+ {name}: {new_sig}")
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
    
    # TODO: Consider using allShortestPaths() to handle multiple equal-length paths deterministically.
    # Current implementation uses shortestPath() which is non-deterministic when multiple paths exist.
    # Potential improvements:
    # 1. Use allShortestPaths() and prioritize paths with EXPOSES/PUBLISHES (public API)
    # 2. Order paths by relationship type priority (EXPOSES/PUBLISHES > HAS_*)
    # 3. Return all shortest paths or implement deterministic selection criteria
    def get_api_call_path(
        self, 
        entity_name: str, 
        root_module: Optional[str] = None,
        root_module_version: Optional[str] = None,
        version_label: Optional[str] = None
    ) -> Optional[str]:
        """
        Get the shortest API call path for an entity.
        This method traverses from ROOT_MODULE to the entity and builds the API call path.
        
        Args:
            entity_name (str): The name of the entity to compute path for
            root_module (Optional[str]): The name of the ROOT_MODULE to start from. If None, uses any ROOT_MODULE.
            root_module_version (Optional[str]): Version label for the root module (e.g., 'version_1_24_0'). If None, no version filtering on root.
            version_label (Optional[str]): Optional version label for the target entity (e.g., 'version_1_24_0').
                                          If None, computes path without version filtering on target.
        
        Returns:
            Optional[str]: The computed shortest call path (e.g., 'numpy.array.reshape'), or None if entity not found
        """
        version_filter = f":`{version_label}`" if version_label else ""
        root_version_filter = f":`{root_module_version}`" if root_module_version else ""
        root_name_filter = "{name: $root_module}" if root_module else ""
        
        query = f"""
        CALL {{
            MATCH (e:METHOD{version_filter} {{name: $entity_name}})
            RETURN e
            UNION
            MATCH (e:FUNCTION{version_filter} {{name: $entity_name}})
            RETURN e
            UNION
            MATCH (e:CLASS{version_filter} {{name: $entity_name}})
            RETURN e
            UNION
            MATCH (e:MODULE{version_filter} {{name: $entity_name}})
            RETURN e
            UNION
            MATCH (e:ROOT_MODULE{version_filter} {{name: $entity_name}})
            RETURN e
        }}
        
        OPTIONAL MATCH path = shortestPath(
            (root:ROOT_MODULE{root_version_filter} {root_name_filter})-[:HAS_SUBMODULE|HAS_CLASS|HAS_METHOD|HAS_FUNCTION|EXPOSES|PUBLISHES|INHERITS_METHOD|INHERITS_CLASS*]->(e)
        )
        
        WITH e, path,
            CASE 
                WHEN path IS NOT NULL AND size(nodes(path)) > 1 THEN
                    reduce(
                        accumulated = {{path: head(nodes(path)).name, idx: 1}},
                        n IN tail(nodes(path)) |
                            CASE
                                WHEN n.__name__ CONTAINS '.' THEN
                                    {{path: accumulated.path + '.' + split(n.__name__, '.')[-1], idx: accumulated.idx + 1}}
                                ELSE
                                    {{path: accumulated.path + '.' + n.__name__, idx: accumulated.idx + 1}}
                            END
                    ).path
                WHEN e IS NOT NULL THEN e.name
                ELSE NULL
            END AS computed_path
        
        RETURN computed_path
        LIMIT 1
        """
        
        try:
            params = {"entity_name": entity_name}
            if root_module:
                params["root_module"] = root_module
            
            result = self.store.database_query(query, params)
            result = self.store.database_query(query, {"entity_name": entity_name})
            if result and len(result) > 0:
                return result[0].get("computed_path")
            return None
        except Exception as e:
            logging.error(f"Error computing shortest call path for {entity_name}: {e}")
            return None
