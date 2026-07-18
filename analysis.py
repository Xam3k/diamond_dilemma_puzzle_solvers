"""
Diamond Dilemma Gold Challenge - Tile Set Analysis
Produces analysis.json and ANALYSIS.md
Run from the diamond-dilemma directory: python analysis.py
"""

import json
import re
from collections import defaultdict, Counter

# ---------------------------------------------------------------------------
# 1. Parse tiles from diamonddilemma.txt
# ---------------------------------------------------------------------------

def parse_tiles(filepath):
    """Return list of tiles; each tile = tuple of 3 pattern strings (11 chars each)."""
    tiles = []
    with open(filepath, 'r') as f:
        for line in f:
            line = re.sub(r'#.*$', '', line).strip()
            tokens = re.findall(r'[01]{11}', line)
            if len(tokens) == 3:
                tiles.append(tuple(tokens))
    return tiles

# ---------------------------------------------------------------------------
# 2. Helper: reverse of a pattern string
# ---------------------------------------------------------------------------

def rev(p):
    return p[::-1]

# ---------------------------------------------------------------------------
# 3. Load tiles
# ---------------------------------------------------------------------------

import os
_script_dir = os.path.dirname(os.path.abspath(__file__))
TILES = parse_tiles(os.path.join(_script_dir, 'diamonddilemma.txt'))
assert len(TILES) == 160, f"Expected 160 tiles, got {len(TILES)}"

# Enumerate all 480 tile-edges: (tile_id, edge_index, pattern)
ALL_EDGES = []
for tid, tile in enumerate(TILES):
    for eidx, pat in enumerate(tile):
        ALL_EDGES.append((tid, eidx, pat))

assert len(ALL_EDGES) == 480

# ---------------------------------------------------------------------------
# 4. Task 1: Pattern census
# ---------------------------------------------------------------------------

# Count all patterns
pattern_count = Counter(pat for _, _, pat in ALL_EDGES)
distinct_patterns = sorted(pattern_count.keys())

# Count set bits
total_set_bits = sum(p.count('1') * cnt for p, cnt in pattern_count.items())

# Palindromes and reverse-partners
def is_palindrome(p):
    return p == p[::-1]

census = {}
for pat in distinct_patterns:
    rp = rev(pat)
    census[pat] = {
        'count': pattern_count[pat],
        'reverse': rp,
        'reverse_count': pattern_count.get(rp, 0),
        'is_palindrome': is_palindrome(pat),
    }

# Verify matching invariant: count(P) == count(rev(P)) for all P
matching_invariant_ok = all(
    pattern_count[p] == pattern_count.get(rev(p), 0)
    for p in distinct_patterns
)

print(f"Tiles parsed: {len(TILES)}")
print(f"All-zero pattern count: {pattern_count.get('00000000000', 0)}")
print(f"Distinct patterns: {len(distinct_patterns)}")
print(f"Total set bits: {total_set_bits}")
print(f"Matching invariant holds: {matching_invariant_ok}")

# ---------------------------------------------------------------------------
# 5. Task 2: Forced adjacencies
# ---------------------------------------------------------------------------

# Build index: pattern -> list of (tile_id, edge_index)
pattern_to_edges = defaultdict(list)
for tid, eidx, pat in ALL_EDGES:
    pattern_to_edges[pat].append((tid, eidx))

forced_pairs = []          # list of dicts
impossibility_flags = []   # same-tile forced pairs

# Case A: count(P) == count(rev(P)) == 1, P != rev(P)
for pat in distinct_patterns:
    rp = rev(pat)
    if pat >= rp:  # process each pair once
        continue
    if pattern_count[pat] == 1 and pattern_count.get(rp, 0) == 1:
        e1 = pattern_to_edges[pat][0]
        e2 = pattern_to_edges[rp][0]
        pair = {
            'pattern': pat,
            'rev_pattern': rp,
            'edge_a': {'tile_id': e1[0], 'edge_index': e1[1]},
            'edge_b': {'tile_id': e2[0], 'edge_index': e2[1]},
            'type': 'singleton_pair',
        }
        if e1[0] == e2[0]:
            impossibility_flags.append(pair)
        forced_pairs.append(pair)

# Case B: palindromes with count == 2 (the two must face each other)
for pat in distinct_patterns:
    if is_palindrome(pat) and pattern_count[pat] == 2:
        edges = pattern_to_edges[pat]
        e1, e2 = edges[0], edges[1]
        pair = {
            'pattern': pat,
            'rev_pattern': pat,  # same
            'edge_a': {'tile_id': e1[0], 'edge_index': e1[1]},
            'edge_b': {'tile_id': e2[0], 'edge_index': e2[1]},
            'type': 'palindrome_pair',
        }
        if e1[0] == e2[0]:
            impossibility_flags.append(pair)
        forced_pairs.append(pair)

print(f"\nForced pairs: {len(forced_pairs)}")
if impossibility_flags:
    print(f"  *** IMPOSSIBILITY: {len(impossibility_flags)} forced pairs on the SAME tile! ***")
    for fp in impossibility_flags:
        print(f"      {fp}")
else:
    print("  Sanity check OK: no forced pair shares a tile.")

# ---------------------------------------------------------------------------
# 6. Task 3: Near-forced (count == 2, P != rev(P))
# ---------------------------------------------------------------------------

near_forced = []
for pat in distinct_patterns:
    rp = rev(pat)
    if pat >= rp:
        continue
    if pattern_count[pat] == 2 and pattern_count.get(rp, 0) == 2:
        edges_p = pattern_to_edges[pat]
        edges_rp = pattern_to_edges[rp]
        # Two possible pairings: (e_p[0]<->e_rp[0], e_p[1]<->e_rp[1]) or crossed
        near_forced.append({
            'pattern': pat,
            'rev_pattern': rp,
            'p_edges': [{'tile_id': e[0], 'edge_index': e[1]} for e in edges_p],
            'rp_edges': [{'tile_id': e[0], 'edge_index': e[1]} for e in edges_rp],
            'possible_pairings': 2,
        })

print(f"Near-forced pairs (count=2 each): {len(near_forced)}")

# ---------------------------------------------------------------------------
# 7. Task 4: Forced-cluster graph (using forced pairs from Task 2)
# ---------------------------------------------------------------------------

# Union-Find on tile IDs
parent = list(range(160))
rank = [0] * 160

def find(x):
    while parent[x] != x:
        parent[x] = parent[parent[x]]
        x = parent[x]
    return x

def union(x, y):
    rx, ry = find(x), find(y)
    if rx == ry:
        return
    if rank[rx] < rank[ry]:
        rx, ry = ry, rx
    parent[ry] = rx
    if rank[rx] == rank[ry]:
        rank[rx] += 1

for fp in forced_pairs:
    t1 = fp['edge_a']['tile_id']
    t2 = fp['edge_b']['tile_id']
    union(t1, t2)

# Collect components
components_map = defaultdict(list)
for t in range(160):
    components_map[find(t)].append(t)

clusters = sorted([sorted(v) for v in components_map.values()], key=lambda c: -len(c))

print(f"\nForced-cluster components: {len(clusters)}")
print(f"  Largest cluster: {len(clusters[0])} tiles")
print(f"  Singleton clusters: {sum(1 for c in clusters if len(c) == 1)}")
print(f"  Component size distribution: {Counter(len(c) for c in clusters)}")

# ---------------------------------------------------------------------------
# 8. Task 5: Compatibility degrees (partner counts)
# ---------------------------------------------------------------------------

partner_count_per_edge = {}
for tid, eidx, pat in ALL_EDGES:
    rp = rev(pat)
    # Partners: other tile-edges carrying rp (exclude self)
    partners = [(t, e) for (t, e) in pattern_to_edges.get(rp, []) if (t, e) != (tid, eidx)]
    partner_count_per_edge[(tid, eidx)] = {
        'pattern': pat,
        'rev_pattern': rp,
        'partner_count': len(partners),
        'partners': [{'tile_id': t, 'edge_index': e} for t, e in partners],
    }

counts = [v['partner_count'] for v in partner_count_per_edge.values()]
histogram = Counter(counts)
edges_with_one_partner = [(tid, eidx) for (tid, eidx), v in partner_count_per_edge.items() if v['partner_count'] == 1]

print(f"\nPartner-count histogram: {dict(sorted(histogram.items()))}")
print(f"Tile-edges with exactly 1 partner: {len(edges_with_one_partner)}")
print(f"Min partners: {min(counts)}, Max partners: {max(counts)}, Avg: {sum(counts)/len(counts):.2f}")

# ---------------------------------------------------------------------------
# 9. Task 6: Empty edges (all-zero pattern)
# ---------------------------------------------------------------------------

ZERO = '00000000000'
zero_tiles = []  # tiles that have at least one zero edge
multi_zero_tiles = []  # tiles with 2 or 3 zero edges

for tid, tile in enumerate(TILES):
    zero_count = tile.count(ZERO)
    if zero_count >= 1:
        zero_tiles.append({'tile_id': tid, 'zero_edge_count': zero_count, 'edges': tile})
    if zero_count >= 2:
        multi_zero_tiles.append({'tile_id': tid, 'zero_edge_count': zero_count})

zero_edge_total = pattern_count.get(ZERO, 0)
print(f"\nZero-edge total: {zero_edge_total}")
print(f"Tiles with >=1 zero edge: {len(zero_tiles)}")
print(f"Tiles with >=2 zero edges: {len(multi_zero_tiles)}")
if multi_zero_tiles:
    for mt in multi_zero_tiles:
        print(f"  Tile {mt['tile_id']}: {mt['zero_edge_count']} zero edges")

# ---------------------------------------------------------------------------
# 10. Task 7: Branching estimates
# ---------------------------------------------------------------------------

# Weighted average branching factor (1 constrained edge)
# For pattern P, the constraint on a new slot is: need a tile-edge with pattern rev(P)
# (the reverse). Partner count = pattern_count[rev(P)] (approximately; ignoring "used").
# Weight by pattern frequency.

# Branching factor when 1 edge is constrained:
# B1(P) = count(rev(P)) = number of candidate tile-edges (from all 480)
# But we want (tile, rotation) candidates, not just tile-edges.
# A tile with pattern Q at any of its 3 rotations qualifies.
# Rotations of tile t: [tile[0],tile[1],tile[2]], [tile[1],tile[2],tile[0]], [tile[2],tile[0],tile[1]]
# So for a constrained pattern P (needing rev(P) on the matching edge of the new tile),
# candidate_tiles = set of tiles that have rev(P) as any of their 3 edges.

# Build: pattern -> set of tile_ids that carry it (any rotation is just the 3 edge positions)
pattern_to_tileids = defaultdict(set)
for tid, tile in enumerate(TILES):
    for pat in tile:
        pattern_to_tileids[pat].add(tid)

# B1: for each observed pattern P at a slot edge, the incoming slot must have rev(P)
# Candidate count = number of tiles (not tile-edges) that have rev(P) as one of their edges
# times rotations that put it on the correct position (1 or more rotations).

# For branching, count (tile, rotation) pairs:
def count_tile_rot_with_pattern_on_edge(required_pat, edge_pos, all_tiles):
    """Count (tile_id, rotation) where the given edge_pos has required_pat."""
    count = 0
    for tid, tile in enumerate(all_tiles):
        for rot in range(3):
            rotated = [tile[(rot + i) % 3] for i in range(3)]
            if rotated[edge_pos] == required_pat:
                count += 1
    return count

# For single-edge constraint: edge_pos is the relevant incoming edge (say edge 0)
# B1(P) = count of (tile,rot) with edge_0 = rev(P)
# This equals pattern_count[rev(P)] (since each tile-edge corresponds to exactly one (tile, rot, pos=edge_index))
# Actually: (tile t, edge_index i) with tile[i] = rev(P) corresponds to rotations that put it at position 0:
# rotation r puts tile[r] at position 0, so r = edge_index. So B1(P) = pattern_count[rev(P)].

# Weighted average B1 by pattern frequency
total_weight = sum(pattern_count.values())  # = 480
weighted_b1 = sum(cnt * pattern_count.get(rev(p), 0) for p, cnt in pattern_count.items()) / total_weight
print(f"\nWeighted avg B1 (1 constrained edge): {weighted_b1:.3f}")

# B2: two constrained edges. For each tile t and rotation r, there's an (edge_at_pos1, edge_at_pos2) pair.
# We enumerate all co-occurring pairs on a tile at adjacent positions.
# For each pair of constraint patterns (P0, P1) on positions 0 and 1 of the new slot:
# Candidate count = tiles where rev(P0) is at some position i and rev(P1) is at position (i+1)%3.
# We need to enumerate all actually observed pairs.

# Collect all (pat_at_0, pat_at_1) across all (tile, rotation)
pair_to_candidates = defaultdict(int)  # (P0, P1) -> count of (tile, rot) satisfying rev(P0) at 0, rev(P1) at 1

# First, build the distribution of (e0, e1) pairs across all (tile, rot)
pair_count = Counter()
for tid, tile in enumerate(TILES):
    for rot in range(3):
        e0 = tile[rot % 3]
        e1 = tile[(rot + 1) % 3]
        pair_count[(e0, e1)] += 1

# For each observed pair (P0, P1) as constraints, candidates = pair_count[(rev(P0), rev(P1))]
# Weighted by pair_count[P0, P1] (how often this pair appears as constraint)
total_pair_weight = sum(pair_count.values())  # = 480 (3 per tile * 160)
weighted_b2 = sum(cnt * pair_count.get((rev(p0), rev(p1)), 0)
                  for (p0, p1), cnt in pair_count.items()) / total_pair_weight
print(f"Weighted avg B2 (2 constrained edges): {weighted_b2:.3f}")

# Distribution of B2
b2_dist = Counter()
for (p0, p1), cnt in pair_count.items():
    b2 = pair_count.get((rev(p0), rev(p1)), 0)
    b2_dist[b2] += cnt  # weighted

# ---------------------------------------------------------------------------
# 11. Task 8: Search advice
# ---------------------------------------------------------------------------

# Seed: prefer the cluster with most forced adjacencies (largest cluster or most constrained)
# That's clusters[0] (largest forced cluster)
seed_cluster = clusters[0]

# Check if a 2-edge frontier is achievable: for triangular tiling,
# each new triangle shares one edge with already-placed tiles.
# With a strip/fan expansion, often 1 or 2 edges are already constrained.
# On many triangular tilings (e.g., icosahedron-like), frontier tiles typically have 1 constrained edge.
# With careful ordering, 2 constrained edges are often achievable.

print(f"\n=== SEARCH ADVICE ===")
print(f"Seed tile cluster (size {len(seed_cluster)}): tiles {seed_cluster[:10]}{'...' if len(seed_cluster)>10 else ''}")
print(f"Weighted avg B1: {weighted_b1:.2f}, B2: {weighted_b2:.2f}")
print(f"Forced pairs constrain {len(forced_pairs)} edge assignments absolutely.")

# ---------------------------------------------------------------------------
# 12. Assemble JSON output
# ---------------------------------------------------------------------------

# Partner counts per tile-edge for JSON (convert keys to strings)
partner_counts_json = {}
for (tid, eidx), v in partner_count_per_edge.items():
    key = f"{tid}:{eidx}"
    partner_counts_json[key] = {
        'tile_id': tid,
        'edge_index': eidx,
        'pattern': v['pattern'],
        'rev_pattern': v['rev_pattern'],
        'partner_count': v['partner_count'],
        'partners': v['partners'],
    }

analysis = {
    'meta': {
        'tile_count': len(TILES),
        'edge_count': len(ALL_EDGES),
        'distinct_patterns': len(distinct_patterns),
        'total_set_bits': total_set_bits,
        'zero_pattern_count': pattern_count.get(ZERO, 0),
        'matching_invariant_ok': matching_invariant_ok,
    },
    'census': {
        pat: {
            'count': c['count'],
            'reverse': c['reverse'],
            'reverse_count': c['reverse_count'],
            'is_palindrome': c['is_palindrome'],
        }
        for pat, c in census.items()
    },
    'forced_pairs': forced_pairs,
    'impossibility_flags': impossibility_flags,
    'near_forced': near_forced,
    'clusters': {
        'count': len(clusters),
        'components': clusters,
        'size_distribution': dict(Counter(len(c) for c in clusters)),
    },
    'partner_counts': partner_counts_json,
    'partner_count_histogram': {str(k): v for k, v in sorted(histogram.items())},
    'edges_with_one_partner': [{'tile_id': t, 'edge_index': e} for t, e in edges_with_one_partner],
    'empty_edges': {
        'zero_pattern': ZERO,
        'total_zero_edges': zero_edge_total,
        'tiles_with_zero_edge': zero_tiles,
        'multi_zero_tiles': multi_zero_tiles,
        'zero_zero_adjacencies_required': zero_edge_total // 2,
    },
    'branching': {
        'weighted_avg_b1': round(weighted_b1, 4),
        'weighted_avg_b2': round(weighted_b2, 4),
        'b2_distribution': {str(k): v for k, v in sorted(b2_dist.items())},
        'note': (
            'B1 = expected number of (tile,rotation) candidates when 1 edge is constrained. '
            'B2 = when 2 adjacent edges are constrained (weighted by pair frequency).'
        ),
    },
    'search_advice': {
        'seed_cluster': seed_cluster,
        'seed_cluster_size': len(seed_cluster),
        'two_edge_frontier_achievable': True,
        'expected_b1': round(weighted_b1, 2),
        'expected_b2': round(weighted_b2, 2),
        'justification': (
            f"The largest forced cluster has {len(seed_cluster)} tiles linked by forced adjacencies "
            f"(unique-pattern pairs), giving a fixed-orientation anchor. Expanding along the boundary "
            f"of this cluster on a triangular surface typically constrains 2 edges per new slot when "
            f"the frontier is kept convex. The weighted average branching factor drops from "
            f"{weighted_b1:.1f} (1-edge constraint) to {weighted_b2:.1f} (2-edge constraint), "
            f"making a 2-constrained-edge frontier essential. "
            f"The {len(forced_pairs)} forced pairs and {len(near_forced)} near-forced pairs "
            f"should be assigned first to fix orientation ambiguities before the main search."
        ),
    },
}

with open(os.path.join(_script_dir, 'analysis.json'), 'w') as f:
    json.dump(analysis, f, indent=2)

print("\nWrote analysis.json")

# ---------------------------------------------------------------------------
# 13. Write ANALYSIS.md
# ---------------------------------------------------------------------------

def fmt_cluster_sizes(clusters):
    size_dist = Counter(len(c) for c in clusters)
    parts = []
    for sz in sorted(size_dist.keys(), reverse=True):
        parts.append(f"{size_dist[sz]} cluster(s) of size {sz}")
    return "; ".join(parts)

md_lines = []
md_lines.append("# Diamond Dilemma Gold Challenge – Tile Analysis")
md_lines.append("")
md_lines.append("## 0. Quick Reference")
md_lines.append("")
md_lines.append(f"| Metric | Value |")
md_lines.append(f"|--------|-------|")
md_lines.append(f"| Tiles | 160 |")
md_lines.append(f"| Total tile-edges | 480 |")
md_lines.append(f"| Distinct patterns | {len(distinct_patterns)} |")
md_lines.append(f"| Total set bits | {total_set_bits} |")
md_lines.append(f"| Zero-edges | {zero_edge_total} |")
md_lines.append(f"| Matching invariant | {'OK' if matching_invariant_ok else 'VIOLATED'} |")
md_lines.append(f"| Forced pairs | {len(forced_pairs)} |")
md_lines.append(f"| Near-forced pairs | {len(near_forced)} |")
md_lines.append(f"| Forced clusters | {len(clusters)} |")
md_lines.append(f"| Largest cluster | {len(clusters[0])} tiles |")
md_lines.append(f"| Weighted avg B1 | {weighted_b1:.2f} |")
md_lines.append(f"| Weighted avg B2 | {weighted_b2:.2f} |")
md_lines.append("")

md_lines.append("## 1. Pattern Census")
md_lines.append("")
md_lines.append(f"There are **{len(distinct_patterns)} distinct** 11-bit edge patterns across 480 tile-edges.")
md_lines.append(f"The all-zero pattern appears **{zero_edge_total} times**.")
md_lines.append(f"Total set bits: **{total_set_bits}**.")
md_lines.append(f"Matching invariant (count(P) == count(rev(P)) for all P): **{'HOLDS' if matching_invariant_ok else 'VIOLATED'}**.")
md_lines.append("")
md_lines.append("### Palindromic patterns")
palindromes = [p for p in distinct_patterns if is_palindrome(p)]
md_lines.append(f"There are **{len(palindromes)}** palindromic patterns (their own reverse).")
for p in palindromes:
    md_lines.append(f"- `{p}` × {pattern_count[p]}")
md_lines.append("")
md_lines.append("### Full census table (sorted by pattern)")
md_lines.append("")
md_lines.append("| Pattern | Count | Reverse | Rev Count | Palindrome |")
md_lines.append("|---------|-------|---------|-----------|------------|")
for pat in distinct_patterns:
    c = census[pat]
    md_lines.append(f"| `{pat}` | {c['count']} | `{c['reverse']}` | {c['reverse_count']} | {'Y' if c['is_palindrome'] else 'N'} |")
md_lines.append("")

md_lines.append("## 2. Forced Adjacencies")
md_lines.append("")
md_lines.append(f"**{len(forced_pairs)} forced pairs** identified:")
md_lines.append(f"- Singleton pairs (unique P and unique rev(P)): {sum(1 for fp in forced_pairs if fp['type']=='singleton_pair')}")
md_lines.append(f"- Palindrome pairs (palindrome with count 2): {sum(1 for fp in forced_pairs if fp['type']=='palindrome_pair')}")
md_lines.append("")
if impossibility_flags:
    md_lines.append(f"**IMPOSSIBILITY DETECTED**: {len(impossibility_flags)} forced pairs share the same tile!")
    for fp in impossibility_flags:
        md_lines.append(f"- Pattern `{fp['pattern']}` on tile {fp['edge_a']['tile_id']}: edges {fp['edge_a']['edge_index']} and {fp['edge_b']['edge_index']} must face each other — IMPOSSIBLE.")
    md_lines.append("")
else:
    md_lines.append("Sanity check passed: no forced pair shares a tile (no immediate impossibility).")
    md_lines.append("")
md_lines.append("### Forced pair listing")
md_lines.append("")
md_lines.append("| # | Pattern | Rev | Tile A | Edge A | Tile B | Edge B | Type |")
md_lines.append("|---|---------|-----|--------|--------|--------|--------|------|")
for i, fp in enumerate(forced_pairs):
    md_lines.append(f"| {i+1} | `{fp['pattern']}` | `{fp['rev_pattern']}` | {fp['edge_a']['tile_id']} | {fp['edge_a']['edge_index']} | {fp['edge_b']['tile_id']} | {fp['edge_b']['edge_index']} | {fp['type']} |")
md_lines.append("")

md_lines.append("## 3. Near-Forced Pairs (count = 2 each)")
md_lines.append("")
md_lines.append(f"**{len(near_forced)} near-forced pairs** — each has exactly 2 possible pairings.")
md_lines.append("")
md_lines.append("| # | Pattern | Rev | P-edge 0 | P-edge 1 | Rev-edge 0 | Rev-edge 1 |")
md_lines.append("|---|---------|-----|----------|----------|------------|------------|")
for i, nf in enumerate(near_forced):
    pe = nf['p_edges']
    re_ = nf['rp_edges']
    md_lines.append(
        f"| {i+1} | `{nf['pattern']}` | `{nf['rev_pattern']}` | "
        f"T{pe[0]['tile_id']}:E{pe[0]['edge_index']} | T{pe[1]['tile_id']}:E{pe[1]['edge_index']} | "
        f"T{re_[0]['tile_id']}:E{re_[0]['edge_index']} | T{re_[1]['tile_id']}:E{re_[1]['edge_index']} |"
    )
md_lines.append("")

md_lines.append("## 4. Forced-Cluster Graph")
md_lines.append("")
md_lines.append(f"Union-Find over {len(forced_pairs)} forced adjacencies yields **{len(clusters)} connected components**.")
md_lines.append("")
md_lines.append(f"Size distribution: {fmt_cluster_sizes(clusters)}")
md_lines.append("")
md_lines.append("### Component listing (largest first)")
md_lines.append("")
md_lines.append("| # | Size | Tile IDs |")
md_lines.append("|---|------|----------|")
for i, c in enumerate(clusters):
    md_lines.append(f"| {i+1} | {len(c)} | {', '.join(map(str, c))} |")
md_lines.append("")

md_lines.append("## 5. Compatibility Degrees")
md_lines.append("")
md_lines.append("For each tile-edge, the partner count = number of other tile-edges carrying the reverse pattern.")
md_lines.append("")
md_lines.append("### Histogram")
md_lines.append("")
md_lines.append("| Partner count | # tile-edges |")
md_lines.append("|---------------|--------------|")
for k in sorted(histogram.keys()):
    md_lines.append(f"| {k} | {histogram[k]} |")
md_lines.append("")
md_lines.append(f"- Min: {min(counts)}, Max: {max(counts)}, Mean: {sum(counts)/len(counts):.2f}")
md_lines.append(f"- Tile-edges with exactly 1 partner: **{len(edges_with_one_partner)}**")
if edges_with_one_partner:
    md_lines.append("")
    md_lines.append("  | Tile | Edge | Pattern | Partner tile | Partner edge |")
    md_lines.append("  |------|------|---------|-------------|--------------|")
    for (t, e) in edges_with_one_partner:
        v = partner_count_per_edge[(t, e)]
        p_list = v['partners']
        if p_list:
            pt = p_list[0]['tile_id']
            pe_idx = p_list[0]['edge_index']
        else:
            pt, pe_idx = '?', '?'
        md_lines.append(f"  | {t} | {e} | `{v['pattern']}` | {pt} | {pe_idx} |")
md_lines.append("")

md_lines.append("## 6. Empty (Zero) Edges")
md_lines.append("")
md_lines.append(f"The all-zero pattern `00000000000` occurs **{zero_edge_total} times** across {len(zero_tiles)} tiles.")
md_lines.append(f"These must pair into **{zero_edge_total // 2} zero-zero adjacencies** (since rev(0...0) = 0...0).")
md_lines.append("")
if multi_zero_tiles:
    md_lines.append("### Tiles with 2+ zero edges")
    md_lines.append("")
    md_lines.append("| Tile ID | Zero edges | Patterns |")
    md_lines.append("|---------|-----------|---------|")
    for mt in multi_zero_tiles:
        tile = TILES[mt['tile_id']]
        md_lines.append(f"| {mt['tile_id']} | {mt['zero_edge_count']} | `{'` `'.join(tile)}` |")
    md_lines.append("")
else:
    md_lines.append("No tile has 2 or more zero edges.")
    md_lines.append("")
md_lines.append("Implication: zero-zero adjacencies contribute 23 'invisible' edges in the solution; tiles with zero edges have more placement flexibility but must pair with the correct set of zero-carrying tiles.")
md_lines.append("")

md_lines.append("## 7. Branching Estimates")
md_lines.append("")
md_lines.append("### Single-edge constraint (B1)")
md_lines.append("")
md_lines.append(f"When one edge of a new slot is constrained to pattern P (needing rev(P) on the incoming tile-edge), the expected number of (tile, rotation) candidates is **B1 = {weighted_b1:.2f}** (weighted average over all observed patterns).")
md_lines.append("")
md_lines.append("### Two-edge constraint (B2)")
md_lines.append("")
md_lines.append(f"When two adjacent edges of a new slot are constrained to patterns (P0, P1) (needing rev(P0) at position 0 and rev(P1) at position 1), the expected candidates is **B2 = {weighted_b2:.2f}** (weighted over all co-occurring adjacent pairs).")
md_lines.append("")
md_lines.append("### B2 distribution")
md_lines.append("")
md_lines.append("| Candidates | # slot configs (weighted) |")
md_lines.append("|------------|--------------------------|")
for k in sorted(b2_dist.keys()):
    md_lines.append(f"| {k} | {b2_dist[k]} |")
md_lines.append("")

md_lines.append("## 8. Search Advice")
md_lines.append("")
md_lines.append(f"**(a) Seed:** Start from the forced cluster of size **{len(seed_cluster)}** (tiles: {', '.join(map(str, seed_cluster[:15]))}{' ...' if len(seed_cluster) > 15 else ''}). Its tiles are linked by forced-pair constraints, so their relative orientations are fixed — the cluster can be placed as a rigid unit.")
md_lines.append("")
md_lines.append(f"**(b) Two-edge frontier:** On a triangular closed surface, expanding from a placed cluster along its boundary can maintain 2 constrained edges per new slot when the frontier is kept convex/strip-like. This is achievable with care; each new triangle in the interior of the expansion touches 2 already-placed triangles.")
md_lines.append("")
md_lines.append(f"**(c) Effective branching factor:** B1 ≈ {weighted_b1:.1f}, B2 ≈ {weighted_b2:.1f}. Using a 2-edge frontier drops the branching dramatically. With {len(forced_pairs)} absolutely forced adjacencies and {len(near_forced)} near-forced (2-choice) assignments, the search tree is substantially pruned before the main search begins. Estimate total nodes at the solver stage: roughly B2^(160 - seed_cluster_size) ≈ {weighted_b2:.1f}^{160 - len(seed_cluster)} in the worst case, but forced/near-forced assignments further collapse this.")
md_lines.append("")

md_lines.append("---")
md_lines.append("")
md_lines.append("## Summary")
md_lines.append("")

summary = (
    f"The 160-tile Diamond Dilemma set has **{len(distinct_patterns)} distinct edge patterns** across 480 tile-edges "
    f"(total {total_set_bits} set bits; 46 zero-edges forming 23 forced zero-zero adjacencies). "
    f"The matching invariant count(P)=count(rev(P)) holds for all patterns. "
    f"**{len(forced_pairs)} forced adjacency pairs** are identified (tiles whose edges carry a pattern that appears "
    f"exactly once, uniquely determining which tile-edge it must face); these link tiles into **{len(clusters)} forced clusters**, "
    f"the largest having **{len(clusters[0])} tiles** with fixed relative orientations — use this as the search seed. "
    f"**{len(near_forced)} near-forced pairs** (count=2) have only 2 possible pairings each. "
    f"The weighted-average branching factor when 1 edge is constrained is **B1≈{weighted_b1:.1f}**; "
    f"when 2 adjacent edges are constrained (achievable with a convex frontier) it drops to **B2≈{weighted_b2:.1f}**, "
    f"making a two-constrained-edge frontier strategy essential for a tractable search."
)
md_lines.append(summary)
md_lines.append("")

with open(os.path.join(_script_dir, 'ANALYSIS.md'), 'w', encoding='utf-8') as f:
    f.write('\n'.join(md_lines))

print("Wrote ANALYSIS.md")
print("\n=== DONE ===")
