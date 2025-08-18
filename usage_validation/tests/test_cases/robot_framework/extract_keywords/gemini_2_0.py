from robot.api import get_resource_from_file, ResourceFile
from robot.libdocpkg.model import KeywordDoc


def extract_keywords_from_resource(resource_file_path: str) -> list[KeywordDoc]:
    """
    Extracts all keywords from a Robot Framework resource file, including their
    documentation and arguments.

    Args:
        resource_file_path: The path to the Robot Framework resource file (.resource).

    Returns:
        A list of KeywordDoc objects, each representing a keyword found in the resource file.
        Returns an empty list if the resource file is invalid or no keywords are found.
    """
    try:
        resource: ResourceFile = get_resource_from_file(resource_file_path)
    except Exception as e:
        print(f"Error parsing resource file: {e}")
        return []

    keywords: list[KeywordDoc] = resource.keywords

    return keywords


def print_keyword_details(keywords: list[KeywordDoc]) -> None:
    """
    Prints the details of each keyword extracted from a resource file.

    Args:
        keywords: A list of KeywordDoc objects.
    """
    if not keywords:
        print("No keywords found.")
        return

    for keyword in keywords:
        print("-" * 40)
        print(f"Keyword Name: {keyword.name}")
        print(f"Documentation: {keyword.doc}")
        print(f"Arguments: {keyword.args}")
        print(f"Source: {keyword.source}:{keyword.lineno}")
        print("-" * 40)


if __name__ == "__main__":
    # Replace 'path/to/your/resource.resource' with the actual path to your resource file
    resource_file_path = 'my_resource.resource'  # Example Path

    # Sample Resource file Creation for demo purpose (my_resource.resource)
    with open(resource_file_path, 'w') as f:
        f.write("""***Settings***
Documentation    Example resource file for keyword extraction.

***Keywords***
Log Message
    [Arguments]    ${message}
    Log    ${message}

Multiply Numbers
    [Arguments]    ${num1}    ${num2}
    ${result} =    Evaluate    ${num1} * ${num2}
    [Return]    ${result}

No Argument Keyword
    Log    This keyword has no arguments.
""")

    keywords = extract_keywords_from_resource(resource_file_path)
    print_keyword_details(keywords)