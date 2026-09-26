with open(r'C:\Users\Fabio\Documents\Default Project\garimpador-leads\backend\main.py', 'r') as f:
    lines = f.readlines()

# Fix indentation: lines 2949-2954 (0-indexed 2948-2953) have 17 spaces, should be 16
for i in range(2948, 2955):  # 0-indexed lines 2948-2954
    if i < len(lines):
        line = lines[i]
        if line.startswith('                 '):  # 17 spaces
            lines[i] = ' ' * 16 + line[17:]

with open(r'C:\Users\Fabio\Documents\Default Project\garimpador-leads\backend\main.py', 'w') as f:
    f.writelines(lines)
print('Fixed')