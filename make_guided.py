"""Build a guided-seed variant of a synthetic instance: seed slots = {planted slot
of seed tile}, and the seed tile's patterns cyclically shifted so planted rot = 0.
Usage: python make_guided.py <instance.txt> <planted.txt> <out.txt>
"""
import sys

inst, planted, out = sys.argv[1], sys.argv[2], sys.argv[3]
lines = [l.rstrip("\n") for l in open(inst)]
data = [l for l in lines if l.strip()]
n_slots, n_edges = map(int, data[0].split())
adj_lines = data[1:1 + n_slots]
tile_lines = data[1 + n_slots:1 + 2 * n_slots]
seed_tile = int(data[-1])

assign = {}
for tok in open(planted).read().split():
    s, t, r = map(int, tok.split(":"))
    assign[s] = (t, r)
slot_of = {t: (s, r) for s, (t, r) in assign.items()}
ps, pr = slot_of[seed_tile]
print(f"seed tile {seed_tile} planted at slot {ps} rot {pr}")

# shift seed tile patterns: new[e] = old[(e + pr) % 3] so that placing with rot 0
# puts old[(j+pr)%3] on slot edge j, identical to planted rot pr.
pats = tile_lines[seed_tile].split()
new_pats = [pats[(e + pr) % 3] for e in range(3)]
tile_lines[seed_tile] = " ".join(new_pats)

with open(out, "w") as f:
    f.write(f"{n_slots} {n_edges}\n")
    for l in adj_lines:
        f.write(l + "\n")
    for l in tile_lines:
        f.write(l + "\n")
    f.write("1\n")
    f.write(f"{ps}\n")
    f.write(f"{seed_tile}\n")
print(f"wrote {out}")
