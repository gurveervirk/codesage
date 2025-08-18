from typing import Dict

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