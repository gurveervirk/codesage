# %%
import sys
from pathlib import Path

backend_path = Path(__file__).parent.parent / "backend"
sys.path.append(str(backend_path))

# %%
from lib_sage.com_extractor import process_package

# %%
entities, relations, other_relations = process_package("pytest", "7.0.0")

# %%
other_relations["EXPOSES"]

# %%
# Search for entity given name
search_name = 'pytest'
found = [e for e in entities if e.name.endswith(search_name)]
print(f'Found {len(found)} entities matching "{search_name}":')
for e in found:
    print(e.name)
    print(e.content_hash)
    print('  labels:', e.labels)
    if 'signature' in e.properties:
        print('  signature:', e.properties.get('signature'))
    if 'resolved_signature' in e.properties:
        print('  resolved_signature:', e.properties.get('resolved_signature'))
    if 'overload_signatures' in e.properties:
        print('  overload_signatures:', e.properties.get('overload_signatures'))
    if 'resolved_overload_signatures' in e.properties:
        print('  resolved_overload_signatures:', e.properties.get('resolved_overload_signatures'))
    if 'source' in e.properties:
        print('  source:', e.properties.get('source'))
    if 'found_types' in e.properties:
        print('  found_types:', e.properties.get('found_types'))
    if 'content_hash' in e.properties:
        print('  content_hash:', e.properties.get('content_hash'))
    print()


