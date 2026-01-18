"""
Compare two COMExtractor JSON outputs and generate git-diff style reports.

This module provides utilities to compare two extraction results from the same
library/version and identify discrepancies in entities, relations, and other relationships.
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, Tuple, Optional


def _normalize_entity(entity: Dict[str, Any]) -> Tuple[str, ...]:
    """Create a normalized tuple key for entity comparison."""
    return (
        entity.get('name', ''),
        tuple(sorted(entity.get('labels', []))),
        tuple(sorted((k, str(v)) for k, v in entity.get('properties', {}).items()))
    )


def _normalize_relation(relation: Dict[str, Any]) -> Tuple[str, ...]:
    """Create a normalized tuple key for relation comparison."""
    return (
        relation.get('from', ''),
        relation.get('to', ''),
        relation.get('type', ''),
        tuple(sorted((k, str(v)) for k, v in relation.get('properties', {}).items()))
    )


def _normalize_other_relation(rel: Dict[str, Any]) -> Tuple[str, str]:
    """Create a normalized tuple key for other_relation comparison."""
    to_val = rel.get('to', {})
    if isinstance(to_val, dict):
        to_str = f"{to_val.get('name', '')}@{to_val.get('version', '')}"
    else:
        to_str = str(to_val)
    return (rel.get('from', ''), to_str)


def _format_entity(entity: Dict[str, Any], indent: int = 2) -> str:
    """Format an entity for display."""
    ind = " " * indent
    lines = [f"{ind}Entity: {entity.get('name', 'N/A')}"]
    labels = entity.get('labels', [])
    if labels:
        lines.append(f"{ind}  Labels: [{', '.join(labels)}]")
    props = entity.get('properties', {})
    if props:
        lines.append(f"{ind}  Properties:")
        for k, v in sorted(props.items()):
            v_str = str(v)[:80] + '...' if len(str(v)) > 80 else str(v)
            lines.append(f"{ind}    {k}: {v_str}")
    return '\n'.join(lines)


def _format_relation(relation: Dict[str, Any], indent: int = 2) -> str:
    """Format a relation for display."""
    ind = " " * indent
    lines = [f"{ind}Relation: {relation.get('from', 'N/A')} --[{relation.get('type', 'N/A')}]--> {relation.get('to', 'N/A')}"]
    props = relation.get('properties', {})
    if props:
        lines.append(f"{ind}  Properties:")
        for k, v in sorted(props.items()):
            lines.append(f"{ind}    {k}: {v}")
    return '\n'.join(lines)


def _format_other_relation(rel: Dict[str, Any], rel_type: str, indent: int = 2) -> str:
    """Format an other_relation for display."""
    ind = " " * indent
    to_val = rel.get('to', {})
    if isinstance(to_val, dict):
        to_str = f"{to_val.get('name', 'N/A')} (v{to_val.get('version', 'N/A')})"
    else:
        to_str = str(to_val)
    return f"{ind}{rel_type}: {rel.get('from', 'N/A')} --> {to_str}"


def compare_extractions(
    file1_path: str,
    file2_path: str,
    output_path: Optional[str] = None,
    json_output_path: Optional[str] = None
) -> Dict[str, Any]:
    """
    Compare two extraction JSON files and generate diff reports.
    
    Args:
        file1_path: Path to first JSON file (baseline)
        file2_path: Path to second JSON file (comparison)
        output_path: Path to save human-readable diff report (optional)
        json_output_path: Path to save structured JSON diff (optional)
        
    Returns:
        Dictionary containing comparison results and statistics
    """
    logging.info(f"Loading extraction file 1: {file1_path}")
    with open(file1_path, 'r', encoding='utf-8') as f:
        data1 = json.load(f)
    
    logging.info(f"Loading extraction file 2: {file2_path}")
    with open(file2_path, 'r', encoding='utf-8') as f:
        data2 = json.load(f)
    
    # Validate metadata compatibility
    meta1 = data1.get('metadata', {})
    meta2 = data2.get('metadata', {})
    
    if meta1.get('name') != meta2.get('name'):
        logging.warning(f"Package names differ: {meta1.get('name')} vs {meta2.get('name')}")
    
    if meta1.get('version') != meta2.get('version'):
        logging.warning(f"Versions differ: {meta1.get('version')} vs {meta2.get('version')}")
    
    # Compare entities
    entities1 = {_normalize_entity(e): e for e in data1.get('entities', [])}
    entities2 = {_normalize_entity(e): e for e in data2.get('entities', [])}
    
    entities_only_in_1 = set(entities1.keys()) - set(entities2.keys())
    entities_only_in_2 = set(entities2.keys()) - set(entities1.keys())
    entities_common = set(entities1.keys()) & set(entities2.keys())
    
    # Compare relations
    relations1 = {_normalize_relation(r): r for r in data1.get('relations', [])}
    relations2 = {_normalize_relation(r): r for r in data2.get('relations', [])}
    
    relations_only_in_1 = set(relations1.keys()) - set(relations2.keys())
    relations_only_in_2 = set(relations2.keys()) - set(relations1.keys())
    relations_common = set(relations1.keys()) & set(relations2.keys())
    
    # Compare other_relations
    other_rel_diffs = {}
    for rel_type in set(data1.get('other_relations', {}).keys()) | set(data2.get('other_relations', {}).keys()):
        rels1 = {_normalize_other_relation(r): r for r in data1.get('other_relations', {}).get(rel_type, [])}
        rels2 = {_normalize_other_relation(r): r for r in data2.get('other_relations', {}).get(rel_type, [])}
        
        only_in_1 = set(rels1.keys()) - set(rels2.keys())
        only_in_2 = set(rels2.keys()) - set(rels1.keys())
        
        if only_in_1 or only_in_2:
            other_rel_diffs[rel_type] = {
                'only_in_1': [rels1[k] for k in only_in_1],
                'only_in_2': [rels2[k] for k in only_in_2]
            }
    
    # Build comparison results
    results = {
        'metadata': {
            'file1': file1_path,
            'file2': file2_path,
            'package_name': meta1.get('name'),
            'version': meta1.get('version')
        },
        'entities': {
            'only_in_file1': [entities1[k] for k in entities_only_in_1],
            'only_in_file2': [entities2[k] for k in entities_only_in_2],
            'common': len(entities_common)
        },
        'relations': {
            'only_in_file1': [relations1[k] for k in relations_only_in_1],
            'only_in_file2': [relations2[k] for k in relations_only_in_2],
            'common': len(relations_common)
        },
        'other_relations': other_rel_diffs,
        'summary': {
            'entities_added': len(entities_only_in_2),
            'entities_removed': len(entities_only_in_1),
            'entities_unchanged': len(entities_common),
            'relations_added': len(relations_only_in_2),
            'relations_removed': len(relations_only_in_1),
            'relations_unchanged': len(relations_common),
            'other_relations_changed': len(other_rel_diffs)
        }
    }
    
    # Generate human-readable diff report
    if output_path:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_path, 'w', encoding='utf-8') as f:
            # Header
            f.write("=" * 80 + "\n")
            f.write("EXTRACTION COMPARISON REPORT\n")
            f.write("=" * 80 + "\n\n")
            
            f.write(f"Package: {meta1.get('name', 'N/A')}\n")
            f.write(f"Version: {meta1.get('version', 'N/A')}\n\n")
            
            f.write(f"File 1 (Baseline): {file1_path}\n")
            f.write(f"File 2 (Comparison): {file2_path}\n")
            f.write("\n" + "=" * 80 + "\n\n")
            
            # Entities section
            f.write("ENTITIES\n")
            f.write("-" * 80 + "\n\n")
            
            if entities_only_in_1:
                f.write(f"❌ REMOVED ({len(entities_only_in_1)} entities only in File 1):\n")
                for key in sorted(entities_only_in_1, key=lambda k: entities1[k].get('name', '')):
                    f.write("- " + _format_entity(entities1[key]).replace('\n', '\n  ') + "\n\n")
            
            if entities_only_in_2:
                f.write(f"✅ ADDED ({len(entities_only_in_2)} entities only in File 2):\n")
                for key in sorted(entities_only_in_2, key=lambda k: entities2[k].get('name', '')):
                    f.write("+ " + _format_entity(entities2[key]).replace('\n', '\n  ') + "\n\n")
            
            f.write(f"  UNCHANGED: {len(entities_common)} entities common to both files\n\n")
            f.write("=" * 80 + "\n\n")
            
            # Relations section
            f.write("RELATIONS\n")
            f.write("-" * 80 + "\n\n")
            
            if relations_only_in_1:
                f.write(f"❌ REMOVED ({len(relations_only_in_1)} relations only in File 1):\n")
                for key in sorted(relations_only_in_1, key=lambda k: (relations1[k].get('from', ''), relations1[k].get('to', ''))):
                    f.write("- " + _format_relation(relations1[key]).replace('\n', '\n  ') + "\n\n")
            
            if relations_only_in_2:
                f.write(f"✅ ADDED ({len(relations_only_in_2)} relations only in File 2):\n")
                for key in sorted(relations_only_in_2, key=lambda k: (relations2[k].get('from', ''), relations2[k].get('to', ''))):
                    f.write("+ " + _format_relation(relations2[key]).replace('\n', '\n  ') + "\n\n")
            
            f.write(f"  UNCHANGED: {len(relations_common)} relations common to both files\n\n")
            f.write("=" * 80 + "\n\n")
            
            # Other relations section
            if other_rel_diffs:
                f.write("OTHER RELATIONS (INHERITS/EXPOSES/PUBLISHES)\n")
                f.write("-" * 80 + "\n\n")
                
                for rel_type, diffs in sorted(other_rel_diffs.items()):
                    f.write(f"{rel_type}:\n")
                    
                    only_in_1 = diffs.get('only_in_1', [])
                    only_in_2 = diffs.get('only_in_2', [])
                    
                    if only_in_1:
                        f.write(f"  ❌ REMOVED ({len(only_in_1)}):\n")
                        for rel in sorted(only_in_1, key=lambda r: r.get('from', '')):
                            f.write("  - " + _format_other_relation(rel, rel_type, 0) + "\n")
                        f.write("\n")
                    
                    if only_in_2:
                        f.write(f"  ✅ ADDED ({len(only_in_2)}):\n")
                        for rel in sorted(only_in_2, key=lambda r: r.get('from', '')):
                            f.write("  + " + _format_other_relation(rel, rel_type, 0) + "\n")
                        f.write("\n")
                
                f.write("=" * 80 + "\n\n")
            
            # Summary
            f.write("SUMMARY\n")
            f.write("-" * 80 + "\n\n")
            summary = results['summary']
            f.write(f"Entities:\n")
            f.write(f"  ✅ Added:     {summary['entities_added']}\n")
            f.write(f"  ❌ Removed:   {summary['entities_removed']}\n")
            f.write(f"  ⚪ Unchanged: {summary['entities_unchanged']}\n")
            f.write(f"  📊 Total:     {summary['entities_added'] + summary['entities_removed'] + summary['entities_unchanged']}\n\n")
            
            f.write(f"Relations:\n")
            f.write(f"  ✅ Added:     {summary['relations_added']}\n")
            f.write(f"  ❌ Removed:   {summary['relations_removed']}\n")
            f.write(f"  ⚪ Unchanged: {summary['relations_unchanged']}\n")
            f.write(f"  📊 Total:     {summary['relations_added'] + summary['relations_removed'] + summary['relations_unchanged']}\n\n")
            
            f.write(f"Other Relations:\n")
            f.write(f"  🔄 Changed Types: {summary['other_relations_changed']}\n\n")
            
            f.write("=" * 80 + "\n")
        
        logging.info(f"Human-readable diff saved to: {output_path.absolute()}")
    
    # Save JSON diff
    if json_output_path:
        json_output_path = Path(json_output_path)
        json_output_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(json_output_path, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        
        logging.info(f"JSON diff saved to: {json_output_path.absolute()}")
    
    return results


def main():
    """Command-line interface for comparing extraction files."""
    import argparse
    import sys
    
    parser = argparse.ArgumentParser(
        description="Compare two COMExtractor JSON outputs and generate diff reports."
    )
    parser.add_argument(
        "file1",
        help="Path to first JSON file (baseline)"
    )
    parser.add_argument(
        "file2",
        help="Path to second JSON file (comparison)"
    )
    parser.add_argument(
        "--output",
        "-o",
        default=None,
        help="Path to save human-readable diff report (default: <package>_diff.txt)"
    )
    parser.add_argument(
        "--json-output",
        "-j",
        default=None,
        help="Path to save structured JSON diff (default: <package>_diff.json)"
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Directory to save output files (default: current directory)"
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Logging level (default: INFO)"
    )
    
    args = parser.parse_args()
    
    # Configure logging
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s - %(levelname)s - %(message)s"
    )
    
    try:
        # Determine output paths
        if args.output or args.output_dir:
            if args.output:
                output_path = args.output
                if not Path(output_path).is_absolute() and args.output_dir:
                    output_path = str(Path(args.output_dir) / output_path)
            else:
                # Generate default from file1
                with open(args.file1, 'r', encoding='utf-8') as f:
                    meta = json.load(f).get('metadata', {})
                package_name = meta.get('name', 'unknown').replace('.', '_')
                filename = f"{package_name}_diff.txt"
                output_path = str(Path(args.output_dir or '.') / filename)
        else:
            output_path = None
        
        if args.json_output or args.output_dir:
            if args.json_output:
                json_output_path = args.json_output
                if not Path(json_output_path).is_absolute() and args.output_dir:
                    json_output_path = str(Path(args.output_dir) / json_output_path)
            else:
                # Generate default from file1
                with open(args.file1, 'r', encoding='utf-8') as f:
                    meta = json.load(f).get('metadata', {})
                package_name = meta.get('name', 'unknown').replace('.', '_')
                filename = f"{package_name}_diff.json"
                json_output_path = str(Path(args.output_dir or '.') / filename)
        else:
            json_output_path = None
        
        # Perform comparison
        results = compare_extractions(
            args.file1,
            args.file2,
            output_path=output_path,
            json_output_path=json_output_path
        )
        
        # Print summary to console
        print("\n" + "=" * 80)
        print("COMPARISON SUMMARY")
        print("=" * 80)
        summary = results['summary']
        print(f"Entities:  +{summary['entities_added']} -{summary['entities_removed']} ={summary['entities_unchanged']}")
        print(f"Relations: +{summary['relations_added']} -{summary['relations_removed']} ={summary['relations_unchanged']}")
        print(f"Other Relations: {summary['other_relations_changed']} type(s) changed")
        print("=" * 80 + "\n")
        
        if output_path:
            print(f"Diff report: {output_path}")
        if json_output_path:
            print(f"JSON diff:   {json_output_path}")
        
    except Exception as e:
        logging.error(f"Error comparing files: {e}")
        import traceback
        logging.error(traceback.format_exc())
        sys.exit(1)


if __name__ == "__main__":
    main()
