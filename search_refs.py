# Temporary script to search for 'from config import' occurrences
import pathlib
import re
root = pathlib.Path('.')
for path in root.rglob('*.py'):
    with path.open('r', encoding='utf-8') as f:
        for i,line in enumerate(f, start=1):
            if 'from config import' in line or 'import config' in line:
                print(path, i, line.strip())