"""Phase 0: data integrity + necessary-condition checks for Diamond Dilemma Gold."""
import re
from collections import Counter

def parse(path):
    tiles = []
    for line in open(path, encoding="utf-8", errors="replace"):
        m = re.findall(r"\b[01]{11}\b", line)
        if len(m) == 3:
            tiles.append(tuple(m))
    return tiles

za3k = parse("diamonddilemma.txt")
doc = parse(r"diamond_dilemma_prompt.md")

print(f"za3k tiles: {len(za3k)}, doc tiles: {len(doc)}")
diffs = [i + 1 for i, (a, b) in enumerate(zip(za3k, doc)) if a != b]
print(f"tiles differing between doc and za3k: {diffs if diffs else 'NONE'}")

# Per-tile parity: each line connects two sides -> even endpoint count per tile
odd = [(i + 1, sum(e.count('1') for e in t)) for i, t in enumerate(za3k)
       if sum(e.count('1') for e in t) % 2 == 1]
print(f"tiles with ODD endpoint count: {odd if odd else 'NONE'}")

# Endpoint count distribution per tile and per edge
tile_counts = Counter(sum(e.count('1') for e in t) for t in za3k)
edge_counts = Counter(e.count('1') for t in za3k for e in t)
print(f"per-tile endpoint distribution: {dict(sorted(tile_counts.items()))}")
print(f"per-edge endpoint distribution: {dict(sorted(edge_counts.items()))}")
print(f"total endpoints: {sum(e.count('1') for t in za3k for e in t)}")

# Global matching invariant: 480 edge patterns must pair up as (P, reverse(P))
edges = [e for t in za3k for e in t]
cnt = Counter(edges)
print(f"distinct edge patterns: {len(cnt)} / 480 edges")
violations = []
for p, c in sorted(cnt.items()):
    r = p[::-1]
    if p == r:
        if c % 2:
            violations.append((p, c, "palindrome with odd count"))
    else:
        if c != cnt.get(r, 0):
            violations.append((p, c, f"reverse count {cnt.get(r, 0)}"))
print("MATCHING INVARIANT:", "VIOLATED" if violations else "SATISFIED (necessary condition for Gold holds)")
for v in violations:
    print("  ", v)

# Pattern multiplicity profile (how tight is the matching?)
mult = Counter(cnt.values())
print(f"pattern multiplicity profile {{count: #patterns}}: {dict(sorted(mult.items()))}")
print(f"empty-edge (all zeros) count: {cnt.get('0' * 11, 0)}")
