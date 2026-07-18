#!/usr/bin/env python3
"""
gen_instance.py -- Generate instance_gold.txt for the Diamond Dilemma solver.

Reads geometry.json and tiles.json from the current directory.
Writes instance_gold.txt with the following layout:

  Line 1:   "160 240"   (n_slots n_edges)
  Lines 2..161:  for slot s (0-indexed):
                 "n0 k0 n1 k1 n2 k2"
                 where n_j = neighbor slot index of slot s's edge j,
                       k_j = that neighbor's edge index facing slot s.
  Lines 162..321: for tile t (0-indexed):
                 "p0 p1 p2"   (three 11-char 0/1 strings, clockwise order)
  Line 322:  "S"   (number of symmetry-breaking seed slots)
  Line 323:  S slot indices (space-separated) = one orbit representative per orbit
             (minimum-index slot from each orbit under the 10 symmetry slot_perms).
  Line 324:  seed tile id (0-indexed) = 23
             (tile 23 is part of a forced cluster with tile 25)

Conventions used by solver.c:
  - Placement convention: tile t with rotation r in slot s puts
    tile edge (j + r) mod 3  onto slot edge j, for j = 0,1,2.
  - Match condition: the pattern on slot-edge j from slot s must equal
    the REVERSE (bit-flip of the 11-char string) of the pattern on
    slot-edge k_j from neighbor slot n_j.
"""

import json
import sys

def main():
    with open("geometry.json", encoding="utf-8") as f:
        geo = json.load(f)
    with open("tiles.json", encoding="utf-8") as f:
        tiles = json.load(f)

    slots = geo["slots"]      # list of 160 slot dicts
    edges = geo["edges"]      # list of 240 edge dicts
    symmetries = geo["symmetry"]  # list of 10 symmetry dicts

    n_slots = len(slots)   # 160
    n_edges = len(edges)   # 240

    assert n_slots == 160, f"Expected 160 slots, got {n_slots}"
    assert n_edges == 240, f"Expected 240 edges, got {n_edges}"
    assert len(tiles) == 160, f"Expected 160 tiles, got {len(tiles)}"

    # ---------------------------------------------------------------------------
    # Build adjacency: for each (slot, edge_index) find (neighbor_slot, neighbor_edge_index)
    # ---------------------------------------------------------------------------
    # neighbor[s][j] = (n, k)  where n is neighbor slot, k is neighbor's edge index
    neighbor = [[-1, -1, -1] for _ in range(n_slots)]  # neighbor[s][j] = [n, k]

    for e in edges:
        sA, eA = e["slotA"], e["edgeA"]
        sB, eB = e["slotB"], e["edgeB"]
        assert neighbor[sA][eA] == -1, f"Duplicate edge for slot {sA} edge {eA}"
        assert neighbor[sB][eB] == -1, f"Duplicate edge for slot {sB} edge {eB}"
        neighbor[sA][eA] = [sB, eB]
        neighbor[sB][eB] = [sA, eA]

    # Verify all slot edges are covered
    for s in range(n_slots):
        for j in range(3):
            assert neighbor[s][j] != -1, f"Slot {s} edge {j} has no neighbor!"

    # ---------------------------------------------------------------------------
    # Compute symmetry orbits of slots (under the 10 slot_perms)
    # Pick the minimum-index slot in each orbit as the representative.
    # ---------------------------------------------------------------------------
    # Union-Find
    parent = list(range(n_slots))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x, y):
        rx, ry = find(x), find(y)
        if rx != ry:
            # merge: keep smaller index as root for determinism
            if rx < ry:
                parent[ry] = rx
            else:
                parent[rx] = ry

    for sym in symmetries:
        perm = sym["slot_perm"]
        for s in range(n_slots):
            union(s, perm[s])

    # Group slots by orbit representative
    orbit_rep = {}  # rep -> list of members
    for s in range(n_slots):
        rep = find(s)
        orbit_rep.setdefault(rep, []).append(s)

    # Orbit representatives = minimum slot in each orbit (already the root since we merged small->root)
    seed_slots = sorted(orbit_rep.keys())
    n_orbits = len(seed_slots)
    print(f"Number of orbits: {n_orbits}")
    print(f"Seed slots (orbit reps): {seed_slots}")

    # The seed tile: tile 23 (0-indexed), part of the forced cluster {23, 25}
    seed_tile = 23

    # ---------------------------------------------------------------------------
    # Write instance_gold.txt
    # ---------------------------------------------------------------------------
    lines = []

    # Line 1: n_slots n_edges
    lines.append(f"{n_slots} {n_edges}")

    # Lines 2..161: adjacency for each slot
    for s in range(n_slots):
        row = []
        for j in range(3):
            n_s, k_s = neighbor[s][j]
            row.append(f"{n_s} {k_s}")
        lines.append(" ".join(row))

    # Lines 162..321: tile patterns
    for t in tiles:
        lines.append(" ".join(t))

    # Line 322: number of seed slots
    lines.append(str(n_orbits))

    # Line 323: seed slot indices
    lines.append(" ".join(str(s) for s in seed_slots))

    # Line 324: seed tile id
    lines.append(str(seed_tile))

    with open("instance_gold.txt", "w", encoding="ascii", newline="\n") as f:
        f.write("\n".join(lines) + "\n")

    print("Wrote instance_gold.txt")
    print(f"  {n_slots} slots, {n_edges} edges, {n_orbits} seed slots, seed tile {seed_tile}")

if __name__ == "__main__":
    main()
