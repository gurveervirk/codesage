from collections import deque
from typing import Dict, List, Set, Tuple

import networkx as nx

from ..models import Entity, Relationship

def find_aliases(
    entities: List[Entity],
    relations: List[Relationship],
    other_relations: Dict[str, List[Tuple]]
) -> Dict[str, List[str]]:
    """
    Find all aliases for entities based on relations including EXPOSES, PUBLISHES, and INHERITS.
    
    Args:
        entities: List of all extracted entities.
        relations: List of structural relationships (HAS_CLASS, etc.).
        other_relations: Dictionary of other relationships (EXPOSES, PUBLISHES, INHERITS).
        
    Returns:
        Dict mapping entity name (FQN) to list of alias strings.
    """
    # Helper maps
    # Use name as key because content_hash lookup is needed for other_relations source
    hash_to_entity = {e.content_hash: e for e in entities}
    fqn_to_entity = {e.name: e for e in entities}
    
    G = nx.DiGraph()
    
    # Add nodes (restrict to essential types)
    valid_labels = {"DISTRIBUTION_PACKAGE", "IMPORT_PACKAGE", "MODULE", "CLASS", "METHOD", "FUNCTION"}
    for e in entities:
        if any(l in valid_labels for l in e.labels):
            G.add_node(e.name, labels=e.labels)
        
    # Add structural relations (HAS_...)
    for rel in relations:
        u = rel.from_entity
        v = rel.to_entity
        
        if u.name not in G or v.name not in G:
             continue
        
        simple_name = v.name.split('.')[-1]
        
        G.add_edge(u.name, v.name, label=simple_name, type="canonical")

    # Add other relations
    for rel_type, rel_list in other_relations.items():
        if rel_type not in ["INHERITS", "INTERNAL_INHERITS", "EXTERNAL_INHERITS", "EXPOSES", "PUBLISHES", "EXPOSES_ALL", "PUBLISHES_ALL"]:
            continue
            
        for u_hash, v_ref in rel_list:
            if u_hash not in hash_to_entity:
                continue
            u = hash_to_entity[u_hash]
            
            if v_ref.name not in fqn_to_entity:
                continue
            v = fqn_to_entity[v_ref.name]
             
            if u.name not in G or v.name not in G:
                continue

            if "INHERITS" in rel_type:
                G.add_edge(u.name, v.name, label=None, type="inherits")
                
            elif "EXPOSES" in rel_type or "PUBLISHES" in rel_type:
                alias_name = v_ref.alias
                if not alias_name:
                    alias_name = v.name.split('.')[-1]
                
                G.add_edge(u.name, v.name, label=alias_name, type="alias")

    # Identify root nodes to start traversal
    start_nodes = []
    for e in entities:
        if "DISTRIBUTION_PACKAGE" in e.labels:
            start_nodes.append(e.name)
            
    # Remove duplicates
    start_nodes = list(set(start_nodes))
    if not start_nodes and entities:
        start_nodes = [n for n, d in G.in_degree() if d == 0]

    # BFS Traversal to accumulate aliases
    aliases: Dict[str, Set[str]] = {e.name: set() for e in entities}
    
    # Pre-calculate defined members for blocking overrides
    # Scope: HAS_METHOD/HAS_CLASS from CLASS entities only
    node_defined_members = {n: set() for n in G.nodes()}
    for rel in relations:
        u = rel.from_entity
        v = rel.to_entity
        
        if u.name not in G: continue
        
        if "CLASS" in u.labels:
             if rel.label in ["HAS_METHOD", "HAS_CLASS"]:
                 simple_name = v.name.split('.')[-1]
                 node_defined_members[u.name].add(simple_name)

    # Queue: (node, path_parts, visited, blocked_members, is_inheriting)
    # blocked_members: Members defined by subclasses that should be hidden
    queue = deque()
    for root in start_nodes:
        if root not in G: continue
        root_simple = root.split('.')[-1]
        queue.append((root, [root_simple], {root}, set(), False))
    
    while queue:
        u, parts, visited, blocked, is_inheriting = queue.popleft()
        
        if not is_inheriting:
             alias_str = ".".join(parts)
             aliases[u].add(alias_str)
            
        if u not in G:
            continue

        for v in G[u]:
            if v in visited:
                continue
            
            edge_data = G[u][v]
            label = edge_data.get('label')
            edge_type = edge_data.get('type')
            
            if edge_type == 'inherits':
                # INHERITS: Transition to parent, carrying blocked members
                new_blocked = blocked | node_defined_members[u]
                new_visited = visited | {v}
                queue.append((v, parts, new_visited, new_blocked, True))
            
            else:
                # CANONICAL/ALIAS: Transition to child/member
                # If we are in inheritance mode, check constraints
                if is_inheriting:
                    # BLOCKING: If member is overridden by subclass
                    # Exception: Private members (mangled) do not override each other across classes
                    # because they have different effective names (_Child__x vs _Parent__x)
                    is_mangled_private = label.startswith("__") and not label.endswith("__")
                    
                    if label in blocked and not is_mangled_private:
                        continue
                    
                    # BLOCKING: Private methods (strict double underscore) and Name Mangling
                    v_node = G.nodes[v]
                    v_labels = v_node.get('labels', [])
                    
                    is_private = "PRIVATE" in v_labels or (label.startswith("__") and not label.endswith("__"))
                    
                    if is_private:
                        # Private members are not inherited by raw name (Safety feature preventing accidental overrides)
                        # However, they are accessible via the mangled name of the defining class (u)
                        if "CLASS" in G.nodes[u].get('labels', []):
                             class_simple_name = u.split('.')[-1]
                             if not label.startswith(f"_{class_simple_name}__"):
                                 mangled_label = f"_{class_simple_name}{label}"
                                 mangled_parts = parts + [mangled_label]
                                 # Traverse to v using the mangled name
                                 queue.append((v, mangled_parts, visited | {v}, set(), False))

                        # Block the raw name collision
                        continue
                
                # If valid, traverse
                if label:
                    # Handle name mangling for PRIVATE members on the defining class itself
                    # (This is not inheritance, just regular access on the class that defines it)
                    # We add the mangled alias: _ClassName__privateMember so it can be resolved externally
                    
                    v_node = G.nodes[v]
                    v_labels = v_node.get('labels', [])
                    is_private = "PRIVATE" in v_labels or (label.startswith("__") and not label.endswith("__"))
                    
                    if is_private and not is_inheriting:
                        # Extract class name from current node u
                        # u is the class defining the member v
                        if "CLASS" in G.nodes[u].get('labels', []):
                             class_simple_name = u.split('.')[-1]
                             # Don't mangle if it's already mangled
                             if not label.startswith(f"_{class_simple_name}__"):
                                 mangled_label = f"_{class_simple_name}{label}"
                                 mangled_parts = parts + [mangled_label]
                                 
                                 # This is a valid alias path for the private member (v)
                                 # But we must continue traversal from v as if we arrived there
                                 queue.append((v, mangled_parts, visited | {v}, set(), False))
                    else:
                        # Normal public/protected members OR non-class members
                        # For private members in defining class, we skip adding the raw name path
                        # to strictly enforce that external access should use mangled name.
                        new_parts = parts + [label]
                        new_visited = visited | {v}
                        queue.append((v, new_parts, new_visited, set(), False))

    # Convert sets to sorted lists
    return {k: sorted(list(v)) for k, v in aliases.items()}
