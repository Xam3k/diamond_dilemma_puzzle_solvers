#!/usr/bin/env python3
"""
gen_synthetic.py -- Generate a synthetic test instance with a planted solution.

Usage: python gen_synthetic.py <seed>

Outputs:
  instance_synth_<seed>.txt       -- instance file in same format as instance_gold.txt
  instance_synth_<seed>.planted.txt -- the planted solution (same format as solutions_gold.txt)

The planted solution is constructed as follows:
  1. For each of the 240 board edges, sample a random 11-bit pattern
     (with bit counts distributed roughly like the real data: 0->19%, 1->36%, 2->38%, 3->7%).
     Each board edge has two directed sides (slotA's view and slotB's view); the patterns
     are mutually reversed.
  2. Each slot gets three patterns (one per directed slot-edge). These form the "slot patterns."
  3. The 160 slot-pattern-triples become the 160 tiles, but scrambled:
     - Apply a random permutation of tile ids (tile i -> slot perm_inv[i]).
     - Apply a random rotation r_i (cyclic shift of the 3 patterns by r_i).
  4. The planted solution assigns tile perm[s] with rotation rot[s] to slot s.

Pattern direction convention:
  - Each undirected board edge has a canonical direction: slotA's directed_edge reading.
  - slotA sees the canonical bits in order (pattern = canonical_bits).
  - slotB sees the reversed bits (pattern = canonical_bits reversed).
  - A directed_edge [start_vertex, end_vertex] gives the traversal direction for the slot.
    The 11 bits are the edge sub-positions from start to end.

Bit-count distribution (from real data analysis):
  0 bits set: ~19%, 1 bit: ~36%, 2 bits: ~38%, 3 bits: ~7%
  We use a multinomial: choose k in {0,1,2,3} then choose k positions from 11.

Instance file format (same as instance_gold.txt):
  Line 1: "160 240"
  Lines 2..161: adjacency (n0 k0 n1 k1 n2 k2) per slot
  Lines 162..321: tile patterns (three 11-char strings per line)
  Line 322: S (number of seed slots = 160 for synthetic)
  Line 323: all 160 slot indices (0..159)
  Line 324: seed tile = tile assigned to slot 0 in the planted solution
"""

import json
import random
import sys
from itertools import combinations

def reverse_pattern(p):
    """Reverse an 11-char bit string."""
    return p[::-1]

WEIGHTS = [10, 36, 47, 7]  # real per-tile-edge distribution: {0:46,1:172,2:228,3:34}/480

def sample_bit_pattern(rng):
    """
    Sample a random 11-bit pattern; P(k bits set) given by WEIGHTS (k=0..3).
    """
    weights = WEIGHTS
    total = sum(weights)
    r = rng.random() * total
    cumul = 0
    k = 0
    for i, w in enumerate(weights):
        cumul += w
        if r < cumul:
            k = i
            break
    # Choose k positions out of 11
    positions = list(range(11))
    chosen = rng.sample(positions, k)
    bits = ['0'] * 11
    for pos in chosen:
        bits[pos] = '1'
    return ''.join(bits)

def main():
    if len(sys.argv) < 2:
        print("Usage: python gen_synthetic.py <seed> [w0,w1,w2,w3]", file=sys.stderr)
        sys.exit(1)

    seed = int(sys.argv[1])
    if len(sys.argv) >= 3:
        global WEIGHTS
        WEIGHTS = [int(x) for x in sys.argv[2].split(",")]
        assert len(WEIGHTS) == 4
    rng = random.Random(seed)

    with open("geometry.json", encoding="utf-8") as f:
        geo = json.load(f)

    slots = geo["slots"]   # 160
    edges = geo["edges"]   # 240
    n_slots = len(slots)
    n_edges = len(edges)
    assert n_slots == 160 and n_edges == 240

    # ---------------------------------------------------------------------------
    # Build adjacency
    # ---------------------------------------------------------------------------
    neighbor = [[-1, -1, -1] for _ in range(n_slots)]
    for e in edges:
        sA, eA, sB, eB = e["slotA"], e["edgeA"], e["slotB"], e["edgeB"]
        neighbor[sA][eA] = [sB, eB]
        neighbor[sB][eB] = [sA, eA]

    # ---------------------------------------------------------------------------
    # Assign canonical bit patterns to all 240 board edges
    # canonical[edge_idx] = 11-char string (the pattern as seen by slotA)
    # slotB sees the reverse.
    # ---------------------------------------------------------------------------
    canonical = [sample_bit_pattern(rng) for _ in range(n_edges)]

    # Map (slotA, edgeA) -> edge index, and (slotB, edgeB) -> edge index
    # so we can look up which canonical pattern a slot sees on its j-th edge.
    # edge_of[s][j] = (edge_idx, is_canonical_side)
    # is_canonical_side = True if this slot is slotA for that edge
    edge_of = [[None]*3 for _ in range(n_slots)]
    for idx, e in enumerate(edges):
        sA, eA, sB, eB = e["slotA"], e["edgeA"], e["slotB"], e["edgeB"]
        edge_of[sA][eA] = (idx, True)   # slotA sees canonical
        edge_of[sB][eB] = (idx, False)  # slotB sees reversed

    # slot_patterns[s] = [p0, p1, p2] the three 11-char patterns for slot s
    slot_patterns = []
    for s in range(n_slots):
        pats = []
        for j in range(3):
            eidx, is_canon = edge_of[s][j]
            raw = canonical[eidx]
            p = raw if is_canon else reverse_pattern(raw)
            pats.append(p)
        slot_patterns.append(pats)

    # ---------------------------------------------------------------------------
    # Create scrambled tiles: random permutation + random rotation
    # tile_perm[t] = s means tile t came from slot s (i.e., tile t has slot s's patterns)
    # tile_rot[t] = r means tile t's patterns are cyclically shifted by r
    # The planted solution: slot s gets tile tile_inv[s] with rotation (3 - rot) mod 3
    # Actually let's define directly:
    #   perm[t] = s  : tile t is a scrambled version of slot s's patterns
    #   tile[t][j] = slot_patterns[s][(j + r) mod 3]  (cyclic shift by r)
    #   To recover: slot s needs tile t = perm_inv[s], rotation r = ... such that
    #     tile[t][(j + r) mod 3] = slot_patterns[s][j]  for all j
    #     i.e., placing tile t with rotation (3 - r) mod 3 in slot s:
    #       tile[t][(j + (3-r)) mod 3] = slot_patterns[perm[t]][j]
    #     We need slot s's pattern on slot-edge j to equal tile edge (j + rot_placed) mod 3
    #     i.e., slot_patterns[s][j] = tile[t][(j + rot_placed) mod 3]
    #         = slot_patterns[perm[t]][(j + rot_placed + r) mod 3]
    #     = slot_patterns[s][j] when perm[t]=s and (rot_placed + r) mod 3 = 0
    #     => rot_placed = (3 - r) mod 3
    # ---------------------------------------------------------------------------
    # tile_perm: random permutation of 0..159
    tile_perm = list(range(n_slots))
    rng.shuffle(tile_perm)
    # tile_perm[t] = s: tile t's "true slot" is s
    perm_inv = [0] * n_slots
    for t, s in enumerate(tile_perm):
        perm_inv[s] = t  # tile assigned to slot s is t

    # random rotations for each tile
    tile_r = [rng.randint(0, 2) for _ in range(n_slots)]

    # Build tile patterns array
    # tile_patterns[t][j] = slot_patterns[tile_perm[t]][(j + tile_r[t]) mod 3]
    tile_patterns = []
    for t in range(n_slots):
        s = tile_perm[t]
        r = tile_r[t]
        pats = [slot_patterns[s][(j + r) % 3] for j in range(3)]
        tile_patterns.append(pats)

    # Planted solution: slot s gets tile perm_inv[s] with rotation (3 - tile_r[perm_inv[s]]) mod 3
    planted = []  # planted[s] = (tile_id, rotation)
    for s in range(n_slots):
        t = perm_inv[s]
        r_placed = (3 - tile_r[t]) % 3
        planted.append((t, r_placed))

    # Verify planted solution: slot s's edge j should equal tile edge (j + r_placed) mod 3
    for s in range(n_slots):
        t, r_placed = planted[s]
        for j in range(3):
            expected = slot_patterns[s][j]
            got = tile_patterns[t][(j + r_placed) % 3]
            assert expected == got, f"Planted error at slot {s} edge {j}"

    # Verify matching: for each board edge, the two slots' patterns must be reversed
    for e in edges:
        sA, eA, sB, eB = e["slotA"], e["edgeA"], e["slotB"], e["edgeB"]
        pA = slot_patterns[sA][eA]
        pB = slot_patterns[sB][eB]
        assert pA == reverse_pattern(pB), \
            f"Edge ({sA},{eA})-({sB},{eB}): {pA} vs {pB} not reversed"

    print(f"Seed {seed}: planted solution verified OK.")

    # ---------------------------------------------------------------------------
    # Write instance file
    # ---------------------------------------------------------------------------
    out_lines = []
    out_lines.append(f"{n_slots} {n_edges}")
    for s in range(n_slots):
        row = []
        for j in range(3):
            ns, ks = neighbor[s][j]
            row.append(f"{ns} {ks}")
        out_lines.append(" ".join(row))
    for t in range(n_slots):
        out_lines.append(" ".join(tile_patterns[t]))
    # All 160 slots as seed slots (no symmetry assumption for synthetic)
    out_lines.append(str(n_slots))
    out_lines.append(" ".join(str(s) for s in range(n_slots)))
    # Seed tile = tile assigned to slot 0 in planted solution
    seed_tile = planted[0][0]
    out_lines.append(str(seed_tile))

    fname = f"instance_synth_{seed}.txt"
    with open(fname, "w", encoding="ascii", newline="\n") as f:
        f.write("\n".join(out_lines) + "\n")
    print(f"Wrote {fname}")

    # ---------------------------------------------------------------------------
    # Write planted solution
    # ---------------------------------------------------------------------------
    sol_parts = []
    for s in range(n_slots):
        t, r = planted[s]
        sol_parts.append(f"{s}:{t}:{r}")
    planted_fname = f"instance_synth_{seed}.planted.txt"
    with open(planted_fname, "w", encoding="ascii", newline="\n") as f:
        f.write(" ".join(sol_parts) + "\n")
    print(f"Wrote {planted_fname}")

if __name__ == "__main__":
    main()
