from robot.api import get_model
from robot.parsing.model.statements import Keyword

def extract_keywords_from_resource(file_path):
    model = get_model(file_path)
    keywords_data = []

    for section in model.sections:
        if hasattr(section, 'body'):
            for node in section.body:
                if isinstance(node, Keyword):
                    keyword_name = node.name
                    doc = ''
                    args = []

                    for child in node.body:
                        if child.type == 'DOCUMENTATION':
                            doc = child.value
                        elif child.type == 'ARGUMENTS':
                            args = child.values

                    keywords_data.append({
                        'name': keyword_name,
                        'documentation': doc,
                        'arguments': args
                    })

    return keywords_data

# Example usage
if __name__ == "__main__":
    file_path = "path/to/your/file.resource"
    keywords = extract_keywords_from_resource(file_path)

    for kw in keywords:
        print(f"Keyword: {kw['name']}")
        print(f"  Documentation: {kw['documentation']}")
        print(f"  Arguments: {kw['arguments']}")
        print()
