"""Compare constraint tightness: distinct patterns, multiplicity profile, and the
key metric -- average number of (tile,rot) candidates a non-blank edge admits.
Lower = more constrained = easier to solve. Random synthetics tend to be FLATTER
(more collisions) hence HARDER than the real puzzle."""
import sys
from collections import Counter, defaultdict
from sat_solver import load_instance

for inst in sys.argv[1:]:
    n, adj, tiles, seed_slots, seed_tile = load_instance(inst)
    rev = lambda p: p[::-1]
    pats = [tiles[t][e] for t in range(n) for e in range(3)]
    cnt = Counter(pats)
    ZERO = "0" * 11
    # candidates that can sit opposite a given pattern p = placements with rev(p)
    by_pat = defaultdict(int)
    for t in range(n):
        for r in range(3):
            for j in range(3):
                by_pat[tiles[t][(j + r) % 3]] += 1
    # avg partner placements over NON-blank tile-edges (weighted by occurrence)
    nonblank = [p for p in pats if p != ZERO]
    avg_partners = sum(by_pat[rev(p)] for p in nonblank) / max(1, len(nonblank))
    blank_partners = by_pat[ZERO]
    print(f"{inst}:")
    print(f"  distinct patterns: {len(cnt)} / 480   blank tile-edges: {cnt[ZERO]}")
    print(f"  avg partner-placements per NON-blank edge: {avg_partners:.1f} "
          f"(lower=tighter=easier)")
    print(f"  partner-placements for a BLANK edge: {blank_partners} (this is the hard part)")
    top = cnt.most_common(4)
    print(f"  most common patterns: {[(p, c) for p, c in top]}")
