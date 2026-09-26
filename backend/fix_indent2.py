with open(r'C:\Users\Fabio\Documents\Default Project\garimpador-leads\backend\main.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Fix indentation for the enrichment try block (lines 2948-2954 in 1-indexed = 2947-2953 0-indexed)
# The try: block is at line 2948 (index 2947)
# The content inside should be indented 16 spaces (4 levels), but currently has 17 spaces (one extra)
for i in range(2947, 2955):  # lines 2948-2955 (1-indexed)
    if i < len(lines):
        line = lines[i]
        if line.startswith('                 '):  # 17 spaces
            lines[i] = ' ' * 16 + line[17:]

with open(r'C:\Users\Fabio\Documents\Default Project\garimpador-leads\backend\main.py', 'w', encoding='utf-8') as f:
    f.writelines(lines)
print('Fixed indentation')
