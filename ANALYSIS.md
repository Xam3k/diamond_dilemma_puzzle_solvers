# Diamond Dilemma Gold Challenge – Tile Analysis

## 0. Quick Reference

| Metric | Value |
|--------|-------|
| Tiles | 160 |
| Total tile-edges | 480 |
| Distinct patterns | 83 |
| Total set bits | 730 |
| Zero-edges | 46 |
| Matching invariant | OK |
| Forced pairs | 7 |
| Near-forced pairs | 5 |
| Forced clusters | 153 |
| Largest cluster | 2 tiles |
| Weighted avg B1 | 12.95 |
| Weighted avg B2 | 0.35 |

## 1. Pattern Census

There are **83 distinct** 11-bit edge patterns across 480 tile-edges.
The all-zero pattern appears **46 times**.
Total set bits: **730**.
Matching invariant (count(P) == count(rev(P)) for all P): **HOLDS**.

### Palindromic patterns
There are **7** palindromic patterns (their own reverse).
- `00000000000` × 46
- `00000100000` × 10
- `00001010000` × 2
- `00010001000` × 6
- `00100000100` × 14
- `01000000010` × 2
- `10000000001` × 4

### Full census table (sorted by pattern)

| Pattern | Count | Reverse | Rev Count | Palindrome |
|---------|-------|---------|-----------|------------|
| `00000000000` | 46 | `00000000000` | 46 | Y |
| `00000000001` | 16 | `10000000000` | 16 | N |
| `00000000010` | 19 | `01000000000` | 19 | N |
| `00000000011` | 7 | `11000000000` | 7 | N |
| `00000000100` | 14 | `00100000000` | 14 | N |
| `00000000101` | 2 | `10100000000` | 2 | N |
| `00000000110` | 1 | `01100000000` | 1 | N |
| `00000001000` | 12 | `00010000000` | 12 | N |
| `00000001001` | 4 | `10010000000` | 4 | N |
| `00000001010` | 5 | `01010000000` | 5 | N |
| `00000001100` | 6 | `00110000000` | 6 | N |
| `00000010000` | 20 | `00001000000` | 20 | N |
| `00000010001` | 5 | `10001000000` | 5 | N |
| `00000010010` | 3 | `01001000000` | 3 | N |
| `00000010100` | 4 | `00101000000` | 4 | N |
| `00000011000` | 3 | `00011000000` | 3 | N |
| `00000100000` | 10 | `00000100000` | 10 | Y |
| `00000100001` | 3 | `10000100000` | 3 | N |
| `00000100010` | 6 | `01000100000` | 6 | N |
| `00000100100` | 6 | `00100100000` | 6 | N |
| `00000101000` | 3 | `00010100000` | 3 | N |
| `00000110000` | 2 | `00001100000` | 2 | N |
| `00000110001` | 1 | `10001100000` | 1 | N |
| `00001000000` | 20 | `00000010000` | 20 | N |
| `00001000001` | 5 | `10000010000` | 5 | N |
| `00001000010` | 3 | `01000010000` | 3 | N |
| `00001000100` | 5 | `00100010000` | 5 | N |
| `00001001000` | 4 | `00010010000` | 4 | N |
| `00001010000` | 2 | `00001010000` | 2 | Y |
| `00001100000` | 2 | `00000110000` | 2 | N |
| `00001100001` | 1 | `10000110000` | 1 | N |
| `00010000000` | 12 | `00000001000` | 12 | N |
| `00010000001` | 5 | `10000001000` | 5 | N |
| `00010000010` | 3 | `01000001000` | 3 | N |
| `00010000100` | 4 | `00100001000` | 4 | N |
| `00010001000` | 6 | `00010001000` | 6 | Y |
| `00010010000` | 4 | `00001001000` | 4 | N |
| `00010010001` | 1 | `10001001000` | 1 | N |
| `00010100000` | 3 | `00000101000` | 3 | N |
| `00011000000` | 3 | `00000011000` | 3 | N |
| `00100000000` | 14 | `00000000100` | 14 | N |
| `00100000001` | 7 | `10000000100` | 7 | N |
| `00100000010` | 3 | `01000000100` | 3 | N |
| `00100000100` | 14 | `00100000100` | 14 | Y |
| `00100000101` | 4 | `10100000100` | 4 | N |
| `00100000110` | 2 | `01100000100` | 2 | N |
| `00100001000` | 4 | `00010000100` | 4 | N |
| `00100010000` | 5 | `00001000100` | 5 | N |
| `00100100000` | 6 | `00000100100` | 6 | N |
| `00100100001` | 2 | `10000100100` | 2 | N |
| `00100100010` | 2 | `01000100100` | 2 | N |
| `00101000000` | 4 | `00000010100` | 4 | N |
| `00110000000` | 6 | `00000001100` | 6 | N |
| `01000000000` | 19 | `00000000010` | 19 | N |
| `01000000001` | 1 | `10000000010` | 1 | N |
| `01000000010` | 2 | `01000000010` | 2 | Y |
| `01000000100` | 3 | `00100000010` | 3 | N |
| `01000001000` | 3 | `00010000010` | 3 | N |
| `01000010000` | 3 | `00001000010` | 3 | N |
| `01000100000` | 6 | `00000100010` | 6 | N |
| `01000100100` | 2 | `00100100010` | 2 | N |
| `01001000000` | 3 | `00000010010` | 3 | N |
| `01001000001` | 4 | `10000010010` | 4 | N |
| `01010000000` | 5 | `00000001010` | 5 | N |
| `01100000000` | 1 | `00000000110` | 1 | N |
| `01100000100` | 2 | `00100000110` | 2 | N |
| `10000000000` | 16 | `00000000001` | 16 | N |
| `10000000001` | 4 | `10000000001` | 4 | Y |
| `10000000010` | 1 | `01000000001` | 1 | N |
| `10000000100` | 7 | `00100000001` | 7 | N |
| `10000001000` | 5 | `00010000001` | 5 | N |
| `10000010000` | 5 | `00001000001` | 5 | N |
| `10000010010` | 4 | `01001000001` | 4 | N |
| `10000100000` | 3 | `00000100001` | 3 | N |
| `10000100100` | 2 | `00100100001` | 2 | N |
| `10000110000` | 1 | `00001100001` | 1 | N |
| `10001000000` | 5 | `00000010001` | 5 | N |
| `10001001000` | 1 | `00010010001` | 1 | N |
| `10001100000` | 1 | `00000110001` | 1 | N |
| `10010000000` | 4 | `00000001001` | 4 | N |
| `10100000000` | 2 | `00000000101` | 2 | N |
| `10100000100` | 4 | `00100000101` | 4 | N |
| `11000000000` | 7 | `00000000011` | 7 | N |

## 2. Forced Adjacencies

**7 forced pairs** identified:
- Singleton pairs (unique P and unique rev(P)): 5
- Palindrome pairs (palindrome with count 2): 2

Sanity check passed: no forced pair shares a tile (no immediate impossibility).

### Forced pair listing

| # | Pattern | Rev | Tile A | Edge A | Tile B | Edge B | Type |
|---|---------|-----|--------|--------|--------|--------|------|
| 1 | `00000000110` | `01100000000` | 86 | 2 | 139 | 2 | singleton_pair |
| 2 | `00000110001` | `10001100000` | 47 | 2 | 150 | 0 | singleton_pair |
| 3 | `00001100001` | `10000110000` | 107 | 2 | 44 | 2 | singleton_pair |
| 4 | `00010010001` | `10001001000` | 23 | 2 | 25 | 0 | singleton_pair |
| 5 | `01000000001` | `10000000010` | 106 | 2 | 121 | 0 | singleton_pair |
| 6 | `00001010000` | `00001010000` | 55 | 1 | 152 | 2 | palindrome_pair |
| 7 | `01000000010` | `01000000010` | 80 | 1 | 141 | 1 | palindrome_pair |

## 3. Near-Forced Pairs (count = 2 each)

**5 near-forced pairs** — each has exactly 2 possible pairings.

| # | Pattern | Rev | P-edge 0 | P-edge 1 | Rev-edge 0 | Rev-edge 1 |
|---|---------|-----|----------|----------|------------|------------|
| 1 | `00000000101` | `10100000000` | T7:E2 | T53:E0 | T26:E1 | T116:E2 |
| 2 | `00000110000` | `00001100000` | T13:E0 | T37:E1 | T29:E0 | T132:E0 |
| 3 | `00100000110` | `01100000100` | T1:E0 | T50:E2 | T17:E2 | T91:E2 |
| 4 | `00100100001` | `10000100100` | T58:E2 | T115:E0 | T97:E1 | T127:E0 |
| 5 | `00100100010` | `01000100100` | T94:E0 | T97:E2 | T71:E1 | T126:E2 |

## 4. Forced-Cluster Graph

Union-Find over 7 forced adjacencies yields **153 connected components**.

Size distribution: 7 cluster(s) of size 2; 146 cluster(s) of size 1

### Component listing (largest first)

| # | Size | Tile IDs |
|---|------|----------|
| 1 | 2 | 23, 25 |
| 2 | 2 | 44, 107 |
| 3 | 2 | 47, 150 |
| 4 | 2 | 55, 152 |
| 5 | 2 | 80, 141 |
| 6 | 2 | 86, 139 |
| 7 | 2 | 106, 121 |
| 8 | 1 | 0 |
| 9 | 1 | 1 |
| 10 | 1 | 2 |
| 11 | 1 | 3 |
| 12 | 1 | 4 |
| 13 | 1 | 5 |
| 14 | 1 | 6 |
| 15 | 1 | 7 |
| 16 | 1 | 8 |
| 17 | 1 | 9 |
| 18 | 1 | 10 |
| 19 | 1 | 11 |
| 20 | 1 | 12 |
| 21 | 1 | 13 |
| 22 | 1 | 14 |
| 23 | 1 | 15 |
| 24 | 1 | 16 |
| 25 | 1 | 17 |
| 26 | 1 | 18 |
| 27 | 1 | 19 |
| 28 | 1 | 20 |
| 29 | 1 | 21 |
| 30 | 1 | 22 |
| 31 | 1 | 24 |
| 32 | 1 | 26 |
| 33 | 1 | 27 |
| 34 | 1 | 28 |
| 35 | 1 | 29 |
| 36 | 1 | 30 |
| 37 | 1 | 31 |
| 38 | 1 | 32 |
| 39 | 1 | 33 |
| 40 | 1 | 34 |
| 41 | 1 | 35 |
| 42 | 1 | 36 |
| 43 | 1 | 37 |
| 44 | 1 | 38 |
| 45 | 1 | 39 |
| 46 | 1 | 40 |
| 47 | 1 | 41 |
| 48 | 1 | 42 |
| 49 | 1 | 43 |
| 50 | 1 | 45 |
| 51 | 1 | 46 |
| 52 | 1 | 48 |
| 53 | 1 | 49 |
| 54 | 1 | 50 |
| 55 | 1 | 51 |
| 56 | 1 | 52 |
| 57 | 1 | 53 |
| 58 | 1 | 54 |
| 59 | 1 | 56 |
| 60 | 1 | 57 |
| 61 | 1 | 58 |
| 62 | 1 | 59 |
| 63 | 1 | 60 |
| 64 | 1 | 61 |
| 65 | 1 | 62 |
| 66 | 1 | 63 |
| 67 | 1 | 64 |
| 68 | 1 | 65 |
| 69 | 1 | 66 |
| 70 | 1 | 67 |
| 71 | 1 | 68 |
| 72 | 1 | 69 |
| 73 | 1 | 70 |
| 74 | 1 | 71 |
| 75 | 1 | 72 |
| 76 | 1 | 73 |
| 77 | 1 | 74 |
| 78 | 1 | 75 |
| 79 | 1 | 76 |
| 80 | 1 | 77 |
| 81 | 1 | 78 |
| 82 | 1 | 79 |
| 83 | 1 | 81 |
| 84 | 1 | 82 |
| 85 | 1 | 83 |
| 86 | 1 | 84 |
| 87 | 1 | 85 |
| 88 | 1 | 87 |
| 89 | 1 | 88 |
| 90 | 1 | 89 |
| 91 | 1 | 90 |
| 92 | 1 | 91 |
| 93 | 1 | 92 |
| 94 | 1 | 93 |
| 95 | 1 | 94 |
| 96 | 1 | 95 |
| 97 | 1 | 96 |
| 98 | 1 | 97 |
| 99 | 1 | 98 |
| 100 | 1 | 99 |
| 101 | 1 | 100 |
| 102 | 1 | 101 |
| 103 | 1 | 102 |
| 104 | 1 | 103 |
| 105 | 1 | 104 |
| 106 | 1 | 105 |
| 107 | 1 | 108 |
| 108 | 1 | 109 |
| 109 | 1 | 110 |
| 110 | 1 | 111 |
| 111 | 1 | 112 |
| 112 | 1 | 113 |
| 113 | 1 | 114 |
| 114 | 1 | 115 |
| 115 | 1 | 116 |
| 116 | 1 | 117 |
| 117 | 1 | 118 |
| 118 | 1 | 119 |
| 119 | 1 | 120 |
| 120 | 1 | 122 |
| 121 | 1 | 123 |
| 122 | 1 | 124 |
| 123 | 1 | 125 |
| 124 | 1 | 126 |
| 125 | 1 | 127 |
| 126 | 1 | 128 |
| 127 | 1 | 129 |
| 128 | 1 | 130 |
| 129 | 1 | 131 |
| 130 | 1 | 132 |
| 131 | 1 | 133 |
| 132 | 1 | 134 |
| 133 | 1 | 135 |
| 134 | 1 | 136 |
| 135 | 1 | 137 |
| 136 | 1 | 138 |
| 137 | 1 | 140 |
| 138 | 1 | 142 |
| 139 | 1 | 143 |
| 140 | 1 | 144 |
| 141 | 1 | 145 |
| 142 | 1 | 146 |
| 143 | 1 | 147 |
| 144 | 1 | 148 |
| 145 | 1 | 149 |
| 146 | 1 | 151 |
| 147 | 1 | 153 |
| 148 | 1 | 154 |
| 149 | 1 | 155 |
| 150 | 1 | 156 |
| 151 | 1 | 157 |
| 152 | 1 | 158 |
| 153 | 1 | 159 |

## 5. Compatibility Degrees

For each tile-edge, the partner count = number of other tile-edges carrying the reverse pattern.

### Histogram

| Partner count | # tile-edges |
|---------------|--------------|
| 1 | 14 |
| 2 | 20 |
| 3 | 46 |
| 4 | 48 |
| 5 | 56 |
| 6 | 36 |
| 7 | 28 |
| 9 | 10 |
| 12 | 24 |
| 13 | 14 |
| 14 | 28 |
| 16 | 32 |
| 19 | 38 |
| 20 | 40 |
| 45 | 46 |

- Min: 1, Max: 45, Mean: 12.78
- Tile-edges with exactly 1 partner: **14**

  | Tile | Edge | Pattern | Partner tile | Partner edge |
  |------|------|---------|-------------|--------------|
  | 23 | 2 | `00010010001` | 25 | 0 |
  | 25 | 0 | `10001001000` | 23 | 2 |
  | 44 | 2 | `10000110000` | 107 | 2 |
  | 47 | 2 | `00000110001` | 150 | 0 |
  | 55 | 1 | `00001010000` | 152 | 2 |
  | 80 | 1 | `01000000010` | 141 | 1 |
  | 86 | 2 | `00000000110` | 139 | 2 |
  | 106 | 2 | `01000000001` | 121 | 0 |
  | 107 | 2 | `00001100001` | 44 | 2 |
  | 121 | 0 | `10000000010` | 106 | 2 |
  | 139 | 2 | `01100000000` | 86 | 2 |
  | 141 | 1 | `01000000010` | 80 | 1 |
  | 150 | 0 | `10001100000` | 47 | 2 |
  | 152 | 2 | `00001010000` | 55 | 1 |

## 6. Empty (Zero) Edges

The all-zero pattern `00000000000` occurs **46 times** across 45 tiles.
These must pair into **23 zero-zero adjacencies** (since rev(0...0) = 0...0).

### Tiles with 2+ zero edges

| Tile ID | Zero edges | Patterns |
|---------|-----------|---------|
| 89 | 2 | `00000000000` `00000000000` `00001000010` |

Implication: zero-zero adjacencies contribute 23 'invisible' edges in the solution; tiles with zero edges have more placement flexibility but must pair with the correct set of zero-carrying tiles.

## 7. Branching Estimates

### Single-edge constraint (B1)

When one edge of a new slot is constrained to pattern P (needing rev(P) on the incoming tile-edge), the expected number of (tile, rotation) candidates is **B1 = 12.95** (weighted average over all observed patterns).

### Two-edge constraint (B2)

When two adjacent edges of a new slot are constrained to patterns (P0, P1) (needing rev(P0) at position 0 and rev(P1) at position 1), the expected candidates is **B2 = 0.35** (weighted over all co-occurring adjacent pairs).

### B2 distribution

| Candidates | # slot configs (weighted) |
|------------|--------------------------|
| 0 | 360 |
| 1 | 89 |
| 2 | 23 |
| 3 | 3 |
| 5 | 5 |

## 8. Search Advice

**(a) Seed:** Start from the forced cluster of size **2** (tiles: 23, 25). Its tiles are linked by forced-pair constraints, so their relative orientations are fixed — the cluster can be placed as a rigid unit.

**(b) Two-edge frontier:** On a triangular closed surface, expanding from a placed cluster along its boundary can maintain 2 constrained edges per new slot when the frontier is kept convex/strip-like. This is achievable with care; each new triangle in the interior of the expansion touches 2 already-placed triangles.

**(c) Effective branching factor:** B1 ≈ 12.9, B2 ≈ 0.4. Using a 2-edge frontier drops the branching dramatically. With 7 absolutely forced adjacencies and 5 near-forced (2-choice) assignments, the search tree is substantially pruned before the main search begins. Estimate total nodes at the solver stage: roughly B2^(160 - seed_cluster_size) ≈ 0.4^158 in the worst case, but forced/near-forced assignments further collapse this.

---

## Summary

The 160-tile Diamond Dilemma set has **83 distinct edge patterns** across 480 tile-edges (total 730 set bits; 46 zero-edges forming 23 forced zero-zero adjacencies). The matching invariant count(P)=count(rev(P)) holds for all patterns. **7 forced adjacency pairs** are identified (tiles whose edges carry a pattern that appears exactly once, uniquely determining which tile-edge it must face); these link tiles into **153 forced clusters**, the largest having **2 tiles** with fixed relative orientations — use this as the search seed. **5 near-forced pairs** (count=2) have only 2 possible pairings each. The weighted-average branching factor when 1 edge is constrained is **B1≈12.9**; when 2 adjacent edges are constrained (achievable with a convex frontier) it drops to **B2≈0.4**, making a two-constrained-edge frontier strategy essential for a tractable search.
