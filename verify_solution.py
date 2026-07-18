#!/usr/bin/env python3
"""
verify_solution.py -- Verify solutions for the Diamond Dilemma solver.

Usage:
  python verify_solution.py <instance_file> <solutions_file>

For each line in the solutions file, checks that:
  1. All 160 slots are assigned exactly one tile each.
  2. Each tile is used exactly once.
  3. Every edge match holds: the pattern on slot s's edge j (as given by tile placement)
     equals the REVERSE of the pattern on the neighbor slot's facing edge.

Pattern placement convention (same as solver.c):
  Placing tile t with rotation r in slot s puts tile edge (j + r) mod 3 onto slot edge j.

Edge match condition:
  pattern(slotA, edgeA) == reverse(pattern(slotB, edgeB))

Prints "PASS" or "FAIL <reason>" for each solution line.
"""

import sys

def reverse_pattern(p):
    return p[::-1]

def parse_instance(fname):
    with open(fname, encoding="ascii") as f:
        lines = [l.rstrip('\n') for l in f]

    idx = 0
    n_slots, n_edges = map(int, lines[idx].split())
    idx += 1

    # Adjacency: neighbor[s][j] = (n, k)
    neighbor = []
    for s in range(n_slots):
        parts = lines[idx].split()
        idx += 1
        neighbor.append([
            (int(parts[0]), int(parts[1])),
            (int(parts[2]), int(parts[3])),
            (int(parts[4]), int(parts[5])),
        ])

    # Tiles: tile_patterns[t][j] = 11-char string
    tile_patterns = []
    for t in range(n_slots):
        parts = lines[idx].split()
        idx += 1
        assert len(parts) == 3, f"Tile {t}: expected 3 patterns, got {len(parts)}"
        tile_patterns.append(parts)

    return n_slots, n_edges, neighbor, tile_patterns

def verify_solution_line(line, n_slots, neighbor, tile_patterns):
    """
    Parse and verify one solution line.
    Returns (ok: bool, reason: str).
    """
    line = line.strip()
    if not line:
        return False, "empty line"

    parts = line.split()
    if len(parts) != n_slots:
        return False, f"expected {n_slots} entries, got {len(parts)}"

    slot_tile = [-1] * n_slots
    slot_rot  = [-1] * n_slots
    used_tiles = set()

    for entry in parts:
        sub = entry.split(':')
        if len(sub) != 3:
            return False, f"malformed entry '{entry}' (expected slot:tile:rot)"
        s, t, r = int(sub[0]), int(sub[1]), int(sub[2])
        if s < 0 or s >= n_slots:
            return False, f"slot {s} out of range"
        if t < 0 or t >= n_slots:
            return False, f"tile {t} out of range"
        if r < 0 or r > 2:
            return False, f"rotation {r} out of range"
        if slot_tile[s] != -1:
            return False, f"slot {s} assigned twice"
        if t in used_tiles:
            return False, f"tile {t} used twice"
        slot_tile[s] = t
        slot_rot[s]  = r
        used_tiles.add(t)

    # Check all slots assigned
    for s in range(n_slots):
        if slot_tile[s] == -1:
            return False, f"slot {s} not assigned"

    # Check all tiles used
    if len(used_tiles) != n_slots:
        return False, f"only {len(used_tiles)} distinct tiles used"

    # Check edge matches
    # We only need to check each undirected edge once;
    # iterate over all slot/edge pairs but deduplicate.
    checked = set()
    for s in range(n_slots):
        t = slot_tile[s]
        r = slot_rot[s]
        for j in range(3):
            nb, kb = neighbor[s][j]
            edge_key = (min(s, nb), max(s, nb))
            if edge_key in checked:
                continue
            checked.add(edge_key)

            # Pattern that slot s puts on its edge j:
            # tile edge (j + r) mod 3
            pat_s = tile_patterns[t][(j + r) % 3]

            # Pattern that neighbor nb puts on its edge kb:
            tnb = slot_tile[nb]
            rnb = slot_rot[nb]
            pat_nb = tile_patterns[tnb][(kb + rnb) % 3]

            # Match condition
            if pat_s != reverse_pattern(pat_nb):
                return False, (
                    f"edge mismatch: slot {s} edge {j} (tile {t} rot {r}) "
                    f"has pattern {pat_s}, but neighbor slot {nb} edge {kb} "
                    f"(tile {tnb} rot {rnb}) has pattern {pat_nb} "
                    f"(expected reverse = {reverse_pattern(pat_nb)})"
                )

    return True, "ok"

def main():
    if len(sys.argv) < 3:
        print("Usage: python verify_solution.py <instance_file> <solutions_file>",
              file=sys.stderr)
        sys.exit(1)

    instance_file = sys.argv[1]
    solutions_file = sys.argv[2]

    n_slots, n_edges, neighbor, tile_patterns = parse_instance(instance_file)
    print(f"Instance: {n_slots} slots, {n_edges} edges, {n_slots} tiles")

    with open(solutions_file, encoding="ascii") as f:
        sol_lines = f.readlines()

    n_pass = 0
    n_fail = 0
    for i, line in enumerate(sol_lines):
        line = line.rstrip('\n')
        if not line:
            continue
        ok, reason = verify_solution_line(line, n_slots, neighbor, tile_patterns)
        if ok:
            print(f"Solution {i+1}: PASS")
            n_pass += 1
        else:
            print(f"Solution {i+1}: FAIL -- {reason}")
            n_fail += 1

    print(f"\nTotal: {n_pass} PASS, {n_fail} FAIL")

if __name__ == "__main__":
    main()
