from typing import Dict, List

class Entity:
    """
    Module-agnostic entity class.
    """
    def __init__(self, name: str, labels: List[str], properties: Dict):
        self.name = name
        # Primary label should be first (e.g., ROOT_MODULE, MODULE, CLASS, METHOD, FUNCTION)
        self.labels = labels
        self.properties = properties

    @property
    def label(self) -> str:
        """
        Backwards-compatible primary label accessor. Returns the first label if available.
        """
        return self.labels[0] if self.labels else ""

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