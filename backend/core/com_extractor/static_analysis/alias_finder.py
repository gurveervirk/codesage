from collections import deque, defaultdict
from typing import Dict, List, Optional, Tuple

from ..models import Entity, Relationship, ExternalEntityRef


def _compute_internal_mro(
    cls_fqn: str,
    class_bases: Dict[str, List[Tuple[str, bool, int]]],
    fqn_to_entity: Dict,
    _visiting: Optional[frozenset] = None,
) -> List[str]:
    """
    Return an ordered list of internal ancestor FQNs using a BFS with
    'keep-last-occurrence' deduplication — a practical approximation of C3
    linearization that correctly handles diamond inheritance.

    External/unknown bases are skipped. Cycles are broken via _visiting.
    """
    if _visiting is None:
        _visiting = frozenset()
    if cls_fqn in _visiting:
        return []
    visiting = _visiting | {cls_fqn}

    q: deque = deque()
    for base_fqn, is_internal, _ in class_bases.get(cls_fqn, []):
        if is_internal and base_fqn in fqn_to_entity:
            q.append((base_fqn, visiting))

    order: List[str] = []
    while q:
        cur, vis = q.popleft()
        if cur in vis:
            continue
        order.append(cur)
        new_vis = vis | {cur}
        for base_fqn, is_internal, _ in class_bases.get(cur, []):
            if is_internal and base_fqn in fqn_to_entity and base_fqn not in vis:
                q.append((base_fqn, new_vis))

    seen: set = set()
    result: List[str] = []
    for item in reversed(order):
        if item not in seen:
            seen.add(item)
            result.append(item)
    result.reverse()
    return result


def find_aliases_static(
    entities: List[Entity],
    relations: List[Relationship],
    other_relations: Dict[str, List[Tuple[str, ExternalEntityRef]]]
) -> Dict[str, List[str]]:
    """Find aliases from static extraction using structural and export propagation."""

    valid_labels = {"DISTRIBUTION_PACKAGE", "IMPORT_PACKAGE", "MODULE", "CLASS", "METHOD", "FUNCTION"}
    fqn_to_entity = {
        e.name: e
        for e in entities
        if "::" not in e.name and any(label in valid_labels for label in e.labels)
    }
    hash_to_fqn = {e.content_hash: e.name for e in entities}

    structure_graph = defaultdict(set)
    alias_graph = defaultdict(set)
    inheritors = defaultdict(list)
    class_bases: Dict[str, List[Tuple[str, bool, int]]] = defaultdict(list)
    defined_members = defaultdict(set)
    module_exports = defaultdict(set)
    exposes_all_edges = []
    module_alias_edges = []

    module_nodes = {
        e.name for e in entities
        if "MODULE" in e.labels or "IMPORT_PACKAGE" in e.labels
    }

    for rel in relations:
        u_name = rel.from_entity.name
        v_name = rel.to_entity.name

        if rel.label in ["HAS_SUBMODULE", "HAS_CLASS", "HAS_FUNCTION", "HAS_METHOD"]:
            simple_name = v_name.split('.')[-1]
            structure_graph[u_name].add(simple_name)

            if "CLASS" in rel.from_entity.labels and rel.label in ["HAS_CLASS", "HAS_METHOD"]:
                defined_members[u_name].add(simple_name)

    for module_name, module_entity in fqn_to_entity.items():
        if "MODULE" in module_entity.labels or "IMPORT_PACKAGE" in module_entity.labels:
            for child_name in structure_graph.get(module_name, set()):
                if not child_name.startswith("_"):
                    module_exports[module_name].add(child_name)

    if "INTERNAL_INHERITS" in other_relations:
        for src_hash, target_ref in other_relations["INTERNAL_INHERITS"]:
            derived_fqn = hash_to_fqn.get(src_hash)
            if derived_fqn:
                mro_idx = target_ref.attributes.get("mro_index", 0) if target_ref.attributes else 0
                inheritors[target_ref.name].append(derived_fqn)
                class_bases[derived_fqn].append((target_ref.name, True, mro_idx))

    if "EXTERNAL_INHERITS" in other_relations:
        for src_hash, target_ref in other_relations["EXTERNAL_INHERITS"]:
            derived_fqn = hash_to_fqn.get(src_hash)
            if derived_fqn:
                mro_idx = target_ref.attributes.get("mro_index", 0) if target_ref.attributes else 0
                class_bases[derived_fqn].append((target_ref.name, False, mro_idx))

    for fqn in class_bases:
        class_bases[fqn].sort(key=lambda x: x[2])

    if "EXPOSES" in other_relations:
        for src_hash, target_ref in other_relations["EXPOSES"]:
            exporter_fqn = hash_to_fqn.get(src_hash)
            if not exporter_fqn:
                continue

            alias_name = target_ref.alias or target_ref.name.split('.')[-1]
            new_alias_fqn = f"{exporter_fqn}.{alias_name}"
            alias_graph[target_ref.name].add(new_alias_fqn)
            module_exports[exporter_fqn].add(alias_name)
            module_alias_edges.append((new_alias_fqn, target_ref.name))

    if "EXPOSES_ALL" in other_relations:
        for src_hash, target_ref in other_relations["EXPOSES_ALL"]:
            exporter_fqn = hash_to_fqn.get(src_hash)
            module_fqn = target_ref.name
            if not exporter_fqn:
                continue

            exposes_all_edges.append((exporter_fqn, module_fqn))

    module_alias_targets = defaultdict(set)
    for module_name in module_nodes:
        module_alias_targets[module_name].add(module_name)

    changed = True
    while changed:
        changed = False
        for alias_module, target_module in module_alias_edges:
            target_candidates = set(module_alias_targets.get(target_module, set()))
            if target_module in module_nodes:
                target_candidates.add(target_module)
            if not target_candidates:
                continue
            for target in target_candidates:
                if target not in module_alias_targets[alias_module]:
                    module_alias_targets[alias_module].add(target)
                    changed = True

    changed = True
    while changed:
        changed = False
        for exporter_fqn, module_fqn in exposes_all_edges:
            source_modules = set(module_alias_targets.get(module_fqn, set()))
            if module_fqn in module_exports:
                source_modules.add(module_fqn)
            for source_module in source_modules:
                for exported_name in module_exports.get(source_module, set()):
                    if exported_name.startswith("_"):
                        # TODO: include private names for EXPOSES_ALL when source module __all__ explicitly includes them.
                        continue
                    if exported_name not in module_exports[exporter_fqn]:
                        module_exports[exporter_fqn].add(exported_name)
                        changed = True

    for exporter_fqn, module_fqn in exposes_all_edges:
        source_modules = set(module_alias_targets.get(module_fqn, set()))
        if module_fqn in module_exports:
            source_modules.add(module_fqn)
        for source_module in source_modules:
            for exported_name in module_exports.get(source_module, set()):
                if exported_name.startswith("_"):
                    continue
                original = f"{source_module}.{exported_name}"
                new_alias = f"{exporter_fqn}.{exported_name}"
                alias_graph[original].add(new_alias)

    class_mro: Dict[str, List[str]] = {}
    for cls_fqn in class_bases:
        if cls_fqn in fqn_to_entity:
            class_mro[cls_fqn] = _compute_internal_mro(cls_fqn, class_bases, fqn_to_entity)

    entity_aliases = defaultdict(set)
    for name in fqn_to_entity:
        entity_aliases[name].add(name)

    queue = deque()
    for name in fqn_to_entity:
        queue.append((name, name))

    visited = set()
    for name in fqn_to_entity:
        visited.add((name, name))

    max_states = max(10000, len(fqn_to_entity) * 200)

    while queue:
        # if len(visited) > max_states:
        #     break
        def_fqn, curr_alias = queue.popleft()

        if curr_alias in alias_graph:
            for next_alias in alias_graph[curr_alias]:
                if (def_fqn, next_alias) not in visited:
                    visited.add((def_fqn, next_alias))
                    entity_aliases[def_fqn].add(next_alias)
                    queue.append((def_fqn, next_alias))

        alias_parts = curr_alias.split('.')
        for i in range(len(alias_parts), 0, -1):
            prefix = '.'.join(alias_parts[:i])
            suffix = '.'.join(alias_parts[i:])
            if prefix not in alias_graph:
                continue
            for mapped_prefix in alias_graph[prefix]:
                if mapped_prefix == prefix or mapped_prefix.startswith(f"{prefix}."):
                    continue
                remapped_alias = mapped_prefix if not suffix else f"{mapped_prefix}.{suffix}"
                if (def_fqn, remapped_alias) not in visited:
                    visited.add((def_fqn, remapped_alias))
                    entity_aliases[def_fqn].add(remapped_alias)
                    queue.append((def_fqn, remapped_alias))

        if def_fqn in structure_graph:
            for child_name in structure_graph[def_fqn]:
                child_def_fqn = f"{def_fqn}.{child_name}"
                child_alias = f"{curr_alias}.{child_name}"

                if child_def_fqn in fqn_to_entity:
                    if (child_def_fqn, child_alias) not in visited:
                        visited.add((child_def_fqn, child_alias))
                        entity_aliases[child_def_fqn].add(child_alias)
                        queue.append((child_def_fqn, child_alias))

        if curr_alias == def_fqn and def_fqn in class_mro:
            seen_members: set = set(defined_members.get(def_fqn, set()))
            for ancestor_fqn in class_mro[def_fqn]:
                for member in structure_graph.get(ancestor_fqn, set()):
                    if member.startswith("__") and not member.endswith("__"):
                        continue
                    if member in seen_members:
                        continue
                    seen_members.add(member)
                    member_def = f"{ancestor_fqn}.{member}"
                    member_alias = f"{def_fqn}.{member}"
                    if member_def in fqn_to_entity:
                        if (member_def, member_alias) not in visited:
                            visited.add((member_def, member_alias))
                            entity_aliases[member_def].add(member_alias)
                            queue.append((member_def, member_alias))

    cleaned_aliases = {}
    for entity_name, alias_set in entity_aliases.items():
        cleaned = sorted(a for a in alias_set if a != entity_name)
        if cleaned:
            cleaned_aliases[entity_name] = cleaned

    return cleaned_aliases
