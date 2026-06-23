import os
p = '"\\\\162.70.125.120\\InternalBuilds\\OpenGrid_2.3.10\\P07HF01\\ARM\\ARM2.3.10.7[1]\\OpenGrid 2.3.10.7[1] Product Release Notes.pdf" '
p = p.strip('\"\'')
print(f'Path: {p}')
print(f'Exists: {os.path.exists(p)}')
