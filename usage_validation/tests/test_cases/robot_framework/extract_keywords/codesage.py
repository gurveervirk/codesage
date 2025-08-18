import os
from robot.libdoc import LibraryDocumentation

# Define a placeholder path for a resource file.
# In a real application, this path should point to your actual .robot resource file.
# For this example, we'll assume a file exists at this location.
# You might need to create a dummy file for the code to run without error.
# Example dummy resource file content (e.g., in 'my_resource.robot'):
# *** Keywords ***
# My First Keyword
#     Log    Hello from first keyword
#
# Another Keyword
#     Log    Hello from another keyword
#
resource_file_path = 'my_resource.robot'

# --- Create a dummy resource file for demonstration if it doesn't exist ---
# This part is just to make the example runnable.
# In a real scenario, you would use your existing resource file.
if not os.path.exists(resource_file_path):
    print(f"Creating a dummy resource file: {resource_file_path}")
    dummy_content = """
*** Keywords ***
My First Keyword
    Log    This is the first keyword

Another Keyword With Args
    [Arguments]    ${arg1}    ${arg2}
    Log    Args: ${arg1}, ${arg2}

Keyword Without Steps
    [Documentation]    This keyword has no steps.
"""
    with open(resource_file_path, 'w') as f:
        f.write(dummy_content.strip())
    print("Dummy file created.")
# --- End of dummy file creation ---


try:
    # Use LibraryDocumentation to parse the resource file
    # The first argument is the path to the resource file
    lib_doc = LibraryDocumentation(resource_file_path)

    print(f"Successfully processed resource file: {resource_file_path}")
    print(f"Resource Name (from file): {lib_doc.name}") # LibraryDoc also has a name attribute

    # Access the keywords attribute which is a list of keyword objects
    keywords = lib_doc.keywords

    if keywords:
        print("\nKeywords found:")
        # Iterate through the keyword objects and print their names
        for kw in keywords:
            print(f"- {kw.name}")
    else:
        print("\nNo keywords found in the resource file.")

except Exception as e:
    print(f"An error occurred while processing the resource file: {e}")
    print(f"Please ensure '{resource_file_path}' is a valid Robot Framework resource file.")

finally:
    # --- Clean up the dummy file ---
    # This part is just for the example's cleanup.
    if os.path.exists(resource_file_path) and "Creating a dummy resource file" in locals().get('dummy_content', ''):
         print(f"\nCleaning up dummy resource file: {resource_file_path}")
         os.remove(resource_file_path)
    # --- End of cleanup ---