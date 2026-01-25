"""
Analyze comparison JSON file produced between 2 COMExtractor runs.
"""

import logging
from typing import Any, Dict, Optional

def analyze_name_diffs(
    comparison_data: Dict[str, Any],
    logger: Optional[logging.Logger] = None
) -> None:
    """
    Analyze name differences in the comparison data. Optionally log all info in a file.

    Args:
        comparison_data (Dict[str, Any]): The comparison data loaded from JSON.

    Returns:
        None
    """
    entities_in_1_only = comparison_data.get("entities", {}).get("only_in_file1", [])
    entities_in_2_only = comparison_data.get("entities", {}).get("only_in_file2", [])

    entity_names_in_1_only = {entity['name'] for entity in entities_in_1_only if '::' not in entity['name']}
    entity_names_in_2_only = {entity['name'] for entity in entities_in_2_only if '::' not in entity['name']}

    if logger:
        logger.info("Entities only in file 1:")
        for name in entity_names_in_1_only:
            logger.info(f" - {name}")
        
        logger.info("Entities only in file 2:")
        for name in entity_names_in_2_only:
            logger.info(f" - {name}")

    common_entity_names = entity_names_in_1_only.intersection(entity_names_in_2_only)
    if common_entity_names:
        if logger:
            logger.info("Entities with same names found in both files:")
            for name in common_entity_names:
                logger.info(f" - {name}")
        else:
            logging.info("Entities with same names found in both files:")
        for name in common_entity_names:
            if not logger:
                logging.info(f" - {name}")
            else:
                logger.info(f" - {name}")
    else:
        if logger:
            logger.info("No entities with the same names found in both files.")
        else:
            logging.info("No entities with the same names found in both files.")