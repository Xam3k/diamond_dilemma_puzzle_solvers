"""
Self-contained: parses diamonddilemma.txt, computes all analyses,
writes analysis.json and ANALYSIS.md directly.

Run with: python compute_and_write.py
(no dependencies beyond stdlib)
"""

import json, re
from collections import defaultdict, Counter

# ── Parse tiles ──────────────────────────────────────────────────────────────
def parse_tiles(path):
    tiles = []
    with open(path) as f:
        for line in f:
            line = re.sub(r'#.*$', '', line).strip()
            toks = re.findall(r'[01]{11}', line)
            if len(toks) == 3:
                tiles.append(tuple(toks))
    return tiles

TILES = parse_tiles(r'diamonddilemma.txt')
assert len(TILES) == 160, f"Got {len(TILES)} tiles"

ALL_EDGES = [(t, ei, pat) for t, tile in enumerate(TILES) for ei, pat in enumerate(tile)]
assert len(ALL_EDGES) == 480

# ── Helpers ───────────────────────────────────────────────────────────────────
def rev(p): return p[::-1]
def is_pal(p): return p == p[::-1]

# ── 1. Pattern census ─────────────────────────────────────────────────────────
pcnt = Counter(pat for _,_,pat in ALL_EDGES)
distinct = sorted(pcnt)
total_bits = sum(p.count('1')*c for p,c in pcnt.items())
ZERO = '0'*11

# matching invariant
inv_ok = all(pcnt[p] == pcnt.get(rev(p),0) for p in distinct)

print(f"Tiles: {len(TILES)}, distinct patterns: {len(distinct)}, total bits: {total_bits}")
print(f"Zero-pattern count: {pcnt[ZERO]}, matching invariant: {inv_ok}")

census = {p: {'count': pcnt[p], 'reverse': rev(p),
               'reverse_count': pcnt.get(rev(p),0), 'is_palindrome': is_pal(p)}
          for p in distinct}

# ── 2. Forced adjacencies ─────────────────────────────────────────────────────
p2e = defaultdict(list)  # pattern -> [(tile_id, edge_idx)]
for t,ei,pat in ALL_EDGES:
    p2e[pat].append((t,ei))

forced = []
impossible = []

# singletons: count(P)=count(rev P)=1, P!=rev P
for p in distinct:
    rp = rev(p)
    if p >= rp: continue
    if pcnt[p]==1 and pcnt.get(rp,0)==1:
        e1 = p2e[p][0]; e2 = p2e[rp][0]
        pair = {'pattern':p,'rev_pattern':rp,
                'edge_a':{'tile_id':e1[0],'edge_index':e1[1]},
                'edge_b':{'tile_id':e2[0],'edge_index':e2[1]},
                'type':'singleton_pair'}
        forced.append(pair)
        if e1[0]==e2[0]: impossible.append(pair)

# palindromes count==2
for p in distinct:
    if is_pal(p) and pcnt[p]==2:
        e1,e2 = p2e[p]
        pair = {'pattern':p,'rev_pattern':p,
                'edge_a':{'tile_id':e1[0],'edge_index':e1[1]},
                'edge_b':{'tile_id':e2[0],'edge_index':e2[1]},
                'type':'palindrome_pair'}
        forced.append(pair)
        if e1[0]==e2[0]: impossible.append(pair)

print(f"Forced pairs: {len(forced)}, impossibilities: {len(impossible)}")
if impossible:
    for fp in impossible:
        print(f"  *** IMPOSSIBLE: {fp}")

# ── 3. Near-forced ────────────────────────────────────────────────────────────
near = []
for p in distinct:
    rp = rev(p)
    if p >= rp: continue
    if pcnt[p]==2 and pcnt.get(rp,0)==2:
        pe = [{'tile_id':e[0],'edge_index':e[1]} for e in p2e[p]]
        re_ = [{'tile_id':e[0],'edge_index':e[1]} for e in p2e[rp]]
        near.append({'pattern':p,'rev_pattern':rp,'p_edges':pe,'rp_edges':re_,'possible_pairings':2})

print(f"Near-forced: {len(near)}")

# ── 4. Forced-cluster graph (Union-Find) ──────────────────────────────────────
par = list(range(160)); rnk = [0]*160

def find(x):
    while par[x]!=x: par[x]=par[par[x]]; x=par[x]
    return x

def union(a,b):
    a,b = find(a),find(b)
    if a==b: return
    if rnk[a]<rnk[b]: a,b=b,a
    par[b]=a
    if rnk[a]==rnk[b]: rnk[a]+=1

for fp in forced:
    union(fp['edge_a']['tile_id'], fp['edge_b']['tile_id'])

comp = defaultdict(list)
for t in range(160): comp[find(t)].append(t)
clusters = sorted([sorted(v) for v in comp.values()], key=lambda c:-len(c))
size_dist = Counter(len(c) for c in clusters)
print(f"Clusters: {len(clusters)}, largest: {len(clusters[0])}, singletons: {size_dist[1]}")
print(f"Size distribution: {dict(sorted(size_dist.items()))}")

# ── 5. Partner counts ─────────────────────────────────────────────────────────
partner_info = {}
for t,ei,pat in ALL_EDGES:
    rp = rev(pat)
    partners = [(a,b) for a,b in p2e.get(rp,[]) if (a,b)!=(t,ei)]
    partner_info[(t,ei)] = {'pattern':pat,'rev_pattern':rp,
                             'partner_count':len(partners),
                             'partners':[{'tile_id':a,'edge_index':b} for a,b in partners]}

pcounts = [v['partner_count'] for v in partner_info.values()]
hist = Counter(pcounts)
one_partner = [(t,ei) for (t,ei),v in partner_info.items() if v['partner_count']==1]
print(f"Partner histogram: {dict(sorted(hist.items()))}")
print(f"1-partner edges: {len(one_partner)}, min: {min(pcounts)}, max: {max(pcounts)}, mean: {sum(pcounts)/480:.3f}")

# ── 6. Zero edges ─────────────────────────────────────────────────────────────
zero_tiles = [{'tile_id':t,'zero_edge_count':tile.count(ZERO),'edges':list(tile)}
              for t,tile in enumerate(TILES) if tile.count(ZERO)>=1]
multi_zero = [z for z in zero_tiles if z['zero_edge_count']>=2]
print(f"Zero-edge total: {pcnt[ZERO]}, tiles with >=1 zero: {len(zero_tiles)}, >=2 zeros: {len(multi_zero)}")

# ── 7. Branching estimates ─────────────────────────────────────────────────────
# B1: weighted avg branching with 1 constrained edge
# When slot needs rev(P), candidates = pcnt[rev(P)] (each tile-edge = one (tile,rotation) candidate)
weighted_b1 = sum(c * pcnt.get(rev(p),0) for p,c in pcnt.items()) / 480

# B2: two adjacent constrained edges
# For each (tile,rot), record (e_at_pos0, e_at_pos1)
pair_cnt = Counter()
for t,tile in enumerate(TILES):
    for rot in range(3):
        e0 = tile[rot%3]; e1 = tile[(rot+1)%3]
        pair_cnt[(e0,e1)] += 1

# B2(P0,P1) = pair_cnt[(rev(P0),rev(P1))]
weighted_b2 = sum(c * pair_cnt.get((rev(p0),rev(p1)),0)
                  for (p0,p1),c in pair_cnt.items()) / sum(pair_cnt.values())

b2_dist = Counter()
for (p0,p1),c in pair_cnt.items():
    b2_dist[pair_cnt.get((rev(p0),rev(p1)),0)] += c

print(f"B1: {weighted_b1:.4f}, B2: {weighted_b2:.4f}")

# ── Assemble JSON ─────────────────────────────────────────────────────────────
analysis = {
    'meta': {
        'tile_count': 160,
        'edge_count': 480,
        'distinct_patterns': len(distinct),
        'total_set_bits': total_bits,
        'zero_pattern_count': pcnt[ZERO],
        'matching_invariant_ok': inv_ok,
    },
    'census': {p: {'count':c['count'],'reverse':c['reverse'],
                   'reverse_count':c['reverse_count'],'is_palindrome':c['is_palindrome']}
               for p,c in census.items()},
    'forced_pairs': forced,
    'impossibility_flags': impossible,
    'near_forced': near,
    'clusters': {
        'count': len(clusters),
        'components': clusters,
        'size_distribution': {str(k):v for k,v in sorted(size_dist.items())},
    },
    'partner_counts': {f"{t}:{ei}": {'tile_id':t,'edge_index':ei,**v}
                       for (t,ei),v in partner_info.items()},
    'partner_count_histogram': {str(k):v for k,v in sorted(hist.items())},
    'edges_with_one_partner': [{'tile_id':t,'edge_index':ei} for t,ei in one_partner],
    'empty_edges': {
        'zero_pattern': ZERO,
        'total_zero_edges': pcnt[ZERO],
        'tiles_with_zero_edge': zero_tiles,
        'multi_zero_tiles': multi_zero,
        'zero_zero_adjacencies_required': pcnt[ZERO]//2,
    },
    'branching': {
        'weighted_avg_b1': round(weighted_b1,4),
        'weighted_avg_b2': round(weighted_b2,4),
        'b2_distribution': {str(k):v for k,v in sorted(b2_dist.items())},
        'note': 'B1=candidates with 1 edge constrained; B2=candidates with 2 adjacent edges constrained',
    },
    'search_advice': {
        'seed_cluster': clusters[0],
        'seed_cluster_size': len(clusters[0]),
        'two_edge_frontier_achievable': True,
        'expected_b1': round(weighted_b1,2),
        'expected_b2': round(weighted_b2,2),
    },
}

with open(r'analysis.json','w') as f:
    json.dump(analysis, f, indent=2)
print("Wrote analysis.json")

# ── Write ANALYSIS.md ─────────────────────────────────────────────────────────
pals = [p for p in distinct if is_pal(p)]
seed = clusters[0]

def fmt_sizes(clusters):
    d = Counter(len(c) for c in clusters)
    return '; '.join(f"{d[s]} cluster(s) of size {s}" for s in sorted(d,reverse=True))

lines = []
A = lines.append

A("# Diamond Dilemma Gold Challenge – Tile-Set Analysis")
A("")
A("## 0. Quick-Reference Metrics")
A("")
A("| Metric | Value |")
A("|--------|-------|")
A(f"| Tiles | 160 |")
A(f"| Total tile-edges | 480 |")
A(f"| Distinct patterns | {len(distinct)} |")
A(f"| Total set bits | {total_bits} |")
A(f"| All-zero pattern count | {pcnt[ZERO]} |")
A(f"| Matching invariant | {'OK' if inv_ok else 'VIOLATED'} |")
A(f"| Forced adjacency pairs | {len(forced)} |")
A(f"| Near-forced pairs | {len(near)} |")
A(f"| Forced-graph clusters | {len(clusters)} |")
A(f"| Largest forced cluster | {len(clusters[0])} tiles |")
A(f"| Tile-edges with 1 partner | {len(one_partner)} |")
A(f"| Weighted-avg B1 | {weighted_b1:.3f} |")
A(f"| Weighted-avg B2 | {weighted_b2:.3f} |")
A("")

A("## 1. Pattern Census")
A("")
A(f"There are **{len(distinct)} distinct** 11-bit edge patterns across 480 tile-edges.")
A(f"Total set bits: **{total_bits}**. All-zero pattern: **{pcnt[ZERO]} occurrences**.")
A(f"Matching invariant `count(P) == count(rev(P))` for all P: **{'HOLDS' if inv_ok else 'VIOLATED'}**.")
A("")
A(f"**Palindromic patterns** (pattern equals its own reverse): {len(pals)}")
A("")
for p in pals:
    A(f"- `{p}` — count {pcnt[p]}")
A("")
A("<details>")
A("<summary>Full census table (click to expand)</summary>")
A("")
A("| Pattern | Count | Reverse | Rev Count | Palindrome |")
A("|---------|-------|---------|-----------|------------|")
for p in distinct:
    c = census[p]
    A(f"| `{p}` | {c['count']} | `{c['reverse']}` | {c['reverse_count']} | {'Y' if c['is_palindrome'] else 'N'} |")
A("")
A("</details>")
A("")

A("## 2. Forced Adjacencies")
A("")
A(f"**{len(forced)} forced adjacency pairs** — in ANY valid solution these tile-edges must face each other:")
A(f"- Singleton pairs (unique P + unique rev(P)): {sum(1 for f in forced if f['type']=='singleton_pair')}")
A(f"- Palindrome pairs (palindrome, count=2): {sum(1 for f in forced if f['type']=='palindrome_pair')}")
A("")
if impossible:
    A(f"**⚠ IMPOSSIBILITY FLAGS: {len(impossible)}** — a forced pair shares a tile!")
    for fp in impossible:
        A(f"- Pattern `{fp['pattern']}` on tile {fp['edge_a']['tile_id']}: "
          f"edges {fp['edge_a']['edge_index']} and {fp['edge_b']['edge_index']} forced to face each other. **PUZZLE HAS NO SOLUTION.**")
else:
    A("Sanity check: no forced pair shares the same tile. No immediate impossibility detected.")
A("")
A("| # | Pattern | Rev Pattern | Tile A | Edge A | Tile B | Edge B | Type |")
A("|---|---------|-------------|--------|--------|--------|--------|------|")
for i,fp in enumerate(forced):
    A(f"| {i+1} | `{fp['pattern']}` | `{fp['rev_pattern']}` | "
      f"{fp['edge_a']['tile_id']} | {fp['edge_a']['edge_index']} | "
      f"{fp['edge_b']['tile_id']} | {fp['edge_b']['edge_index']} | {fp['type']} |")
A("")

A("## 3. Near-Forced Pairs (count = 2 each)")
A("")
A(f"**{len(near)} near-forced pairs** — each has exactly 2 possible pairings. Try both branches.")
A("")
A("| # | Pattern | Rev Pattern | P-edge 0 | P-edge 1 | Rev-edge 0 | Rev-edge 1 |")
A("|---|---------|-------------|----------|----------|------------|------------|")
for i,nf in enumerate(near):
    pe=nf['p_edges']; re_=nf['rp_edges']
    A(f"| {i+1} | `{nf['pattern']}` | `{nf['rev_pattern']}` | "
      f"T{pe[0]['tile_id']}:E{pe[0]['edge_index']} | T{pe[1]['tile_id']}:E{pe[1]['edge_index']} | "
      f"T{re_[0]['tile_id']}:E{re_[0]['edge_index']} | T{re_[1]['tile_id']}:E{re_[1]['edge_index']} |")
A("")

A("## 4. Forced-Cluster Graph")
A("")
A(f"Union-Find on {len(forced)} forced adjacencies yields **{len(clusters)} connected components**.")
A(f"Size distribution: {fmt_sizes(clusters)}")
A("")
A("| Component # | Size | Tile IDs |")
A("|-------------|------|----------|")
for i,c in enumerate(clusters):
    A(f"| {i+1} | {len(c)} | {', '.join(map(str,c))} |")
A("")

A("## 5. Compatibility Degrees")
A("")
A("Partner count for a tile-edge = number of other tile-edges carrying the reverse pattern.")
A("")
A("| Partner count | # tile-edges |")
A("|---------------|--------------|")
for k in sorted(hist):
    A(f"| {k} | {hist[k]} |")
A("")
A(f"Min: {min(pcounts)}, Max: {max(pcounts)}, Mean: {sum(pcounts)/480:.3f}")
A(f"Tile-edges with exactly 1 partner: **{len(one_partner)}**")
A("")
if one_partner:
    A("| Tile | Edge | Pattern | Partner tile | Partner edge |")
    A("|------|------|---------|-------------|--------------|")
    for t,ei in one_partner:
        v = partner_info[(t,ei)]
        pt = v['partners'][0]['tile_id'] if v['partners'] else '—'
        pe_ = v['partners'][0]['edge_index'] if v['partners'] else '—'
        A(f"| {t} | {ei} | `{v['pattern']}` | {pt} | {pe_} |")
    A("")

A("## 6. Empty (Zero) Edges")
A("")
A(f"Pattern `00000000000` appears **{pcnt[ZERO]} times** across {len(zero_tiles)} tiles.")
A(f"These must form **{pcnt[ZERO]//2} zero-zero adjacencies** (rev(0...0)=0...0).")
A("")
if multi_zero:
    A("### Tiles with 2+ zero edges")
    A("")
    A("| Tile ID | Zero-edge count | Edges |")
    A("|---------|-----------------|-------|")
    for z in multi_zero:
        tile = TILES[z['tile_id']]
        A(f"| {z['tile_id']} | {z['zero_edge_count']} | `{'` `'.join(tile)}` |")
    A("")
else:
    A("No tile has 2 or more zero edges.")
    A("")
A("The 23 required zero-zero adjacencies consume exactly the 46 zero-edge occurrences. "
  "Zero-edge tiles have no line endpoints on that face — 'invisible' edges in the solved puzzle.")
A("")

A("## 7. Branching Estimates")
A("")
A("### B1 — single-edge constraint")
A("")
A(f"When a new slot has exactly one incoming constrained edge (pattern P), "
  f"the number of compatible (tile, rotation) candidates equals the count of tile-edges "
  f"carrying rev(P). The **weighted average B1 = {weighted_b1:.3f}** (weighted by pattern frequency).")
A("")
A("### B2 — two-edge constraint")
A("")
A(f"When two adjacent edges of a new slot are constrained (patterns P0 at position 0, P1 at position 1), "
  f"candidates = pairs (tile, rotation) where position 0 carries rev(P0) AND position 1 carries rev(P1). "
  f"The **weighted average B2 = {weighted_b2:.3f}**.")
A("")
A("### B2 candidate-count distribution")
A("")
A("| Candidates | # slot configs (weighted by pair frequency) |")
A("|------------|----------------------------------------------|")
for k in sorted(b2_dist):
    A(f"| {k} | {b2_dist[k]} |")
A("")

A("## 8. Search Advice")
A("")
A(f"**(a) Seed:** Use the largest forced cluster as the search root — "
  f"**{len(seed)} tiles** (IDs: {', '.join(map(str,seed[:20]))}"
  f"{'...' if len(seed)>20 else ''}). These tiles are connected by forced-pair constraints, "
  f"so their relative orientations are completely fixed. Place them as a rigid unit.")
A("")
A(f"**(b) Two-edge frontier:** On a closed triangular surface, once the seed cluster is placed, "
  f"the expansion frontier can be managed so that most new triangles touch two already-placed "
  f"neighbours. This requires keeping the active boundary convex / strip-shaped. "
  f"With care, 2-edge constraint is achievable for the majority of placements.")
A("")
A(f"**(c) Effective branching factor:** B1 ≈ {weighted_b1:.2f} (poor), B2 ≈ {weighted_b2:.2f} (manageable). "
  f"The {len(forced)} forced pairs and {len(near)} near-forced pairs (2 choices each) provide "
  f"hard constraints that must be satisfied in any solution; assign these first. "
  f"Starting from the {len(seed)}-tile forced cluster and maintaining a 2-edge constrained frontier "
  f"gives an effective branching factor around {weighted_b2:.1f}, making exhaustive or "
  f"heuristic search feasible.")
A("")

A("---")
A("")
A("## Summary")
A("")
A(
    f"The 160-tile Diamond Dilemma Gold set has **{len(distinct)} distinct edge patterns** across 480 "
    f"tile-edges (total set bits: {total_bits}; all-zero pattern: {pcnt[ZERO]} occurrences forming "
    f"{pcnt[ZERO]//2} forced zero-zero adjacencies). The matching invariant count(P)=count(rev(P)) "
    f"holds for all patterns — the tile set is globally consistent. "
    f"**{len(forced)} forced adjacency pairs** (singletons + palindrome-pairs) are identified; these "
    f"link tiles into **{len(clusters)} forced clusters** via Union-Find, the largest comprising "
    f"**{len(clusters[0])} tiles** with fully fixed relative orientations — the natural search seed. "
    f"**{len(near)} near-forced pairs** (count=2 each) reduce to binary branch decisions. "
    f"The weighted-average branching factor with one constrained edge is **B1 ≈ {weighted_b1:.1f}**, "
    f"dropping to **B2 ≈ {weighted_b2:.1f}** when two adjacent edges are constrained — confirming "
    f"that a 2-constrained-edge frontier strategy is essential for a tractable combinatorial search."
)
A("")

with open(r'ANALYSIS.md','w') as f:
    f.write('\n'.join(lines))
print("Wrote ANALYSIS.md")
print("DONE.")
