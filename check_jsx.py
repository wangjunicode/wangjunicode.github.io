import re

files = [
    ('ECS', 'src/content/posts/ECS实体生命周期扩展钩子系统-AddComponent与GetComponent与Deserialize与Reset系统接口完整解析.md'),
    ('BattleLog', 'src/content/posts/游戏战斗日志分层系统-BattleLogTag枚举与LogFilterType标志位与LogKey结构体的完整设计解析.md')
]

for name, f in files:
    with open(f, encoding='utf-8') as fp:
        lines = fp.readlines()
    print(f'=== {name} ===')
    in_code_block = False
    problematic = []
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped.startswith('```'):
            in_code_block = not in_code_block
        if not in_code_block and '<' in line and re.search(r'<[A-Z]', line):
            problematic.append((i, line.rstrip()))
    if problematic:
        print(f"  OUTSIDE CODE BLOCKS ({len(problematic)} lines):")
        for lineno, content in problematic:
            print(f"  L{lineno}: {content[:120]}")
    else:
        print("  No problematic JSX-like tags outside code blocks!")
    print()
