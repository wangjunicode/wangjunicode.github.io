import re
import glob
import os

all_files = glob.glob('src/content/posts/*.md')
problems = []

for f in sorted(all_files, key=os.path.getmtime, reverse=True):
    with open(f, encoding='utf-8') as fp:
        lines = fp.readlines()
    in_code_block = False
    file_problems = []
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped.startswith('```'):
            in_code_block = not in_code_block
        if not in_code_block:
            # Remove inline code spans first (backtick-wrapped content)
            line_no_inline = re.sub(r'`[^`]*`', '', line)
            # Now check for JSX-like tags (Capital letter tags, 2+ chars)
            matches = re.findall(r'<([A-Z][A-Za-z]{1,})[^a-z]', line_no_inline)
            if matches:
                file_problems.append((i, line.rstrip()[:120], matches))
    if file_problems:
        problems.append((os.path.basename(f), file_problems))

print(f"Files with problematic JSX-like tags (outside code blocks AND inline code): {len(problems)}")
for fname, issues in problems:
    print(f"\n=== {fname[:65]} ===")
    for lineno, content, tags in issues[:5]:
        print(f"  L{lineno} {tags}: {content[:120]}")
