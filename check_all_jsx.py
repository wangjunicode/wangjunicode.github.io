import re
import glob
import os

all_files = glob.glob('src/content/posts/*.md')
problems = []

for f in all_files:
    with open(f, encoding='utf-8') as fp:
        lines = fp.readlines()
    in_code_block = False
    file_problems = []
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped.startswith('```'):
            in_code_block = not in_code_block
        if not in_code_block:
            # match <Word> or <Word1Word2> style tags outside code blocks (not single chars)
            matches = re.findall(r'<([A-Z][A-Za-z]{1,})[^a-z]', line)
            if matches:
                file_problems.append((i, line.rstrip()[:120], matches))
    if file_problems:
        problems.append((os.path.basename(f), file_problems))

print(f"Files with potential JSX-like tags outside code blocks: {len(problems)}")
for fname, issues in problems:
    print(f"\n=== {fname[:60]} ===")
    for lineno, content, tags in issues[:5]:
        print(f"  L{lineno} {tags}: {content[:100]}")
