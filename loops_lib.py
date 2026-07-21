"""loops_lib.py -- shared closed-gold-loop detection for the solvers.

A board containing a CLOSED gold sub-loop can never be extended to the single
required loop, so loop-aware optimizers must reject any placement that closes
one. count_closed(pl) is fast enough to call after every repair.
"""
import json
from collections import defaultdict

_g = json.load(open("geometry.json"))
_arcs = json.load(open("arcs.json"))

_edge_of = {}
for _i, _e in enumerate(_g["edges"]):
    _edge_of[(_e["slotA"], _e["edgeA"])] = (_i, True)
    _edge_of[(_e["slotB"], _e["edgeB"])] = (_i, False)


def count_closed(pl, arcs=None):
    """Number of CLOSED loops in board pl ({slot: (tile, rot)})."""
    A = arcs if arcs is not None else _arcs
    adj = defaultdict(list)
    for s, (t, r) in pl.items():
        for (a_, b_) in A[t]:
            ends = []
            for (e, p) in (a_, b_):
                j = (e - r) % 3
                i, is_a = _edge_of[(s, j)]
                ends.append((i, p if is_a else 10 - p))
            adj[ends[0]].append(ends[1])
            adj[ends[1]].append(ends[0])
    seen, closed = set(), 0
    for start in adj:
        if start in seen:
            continue
        comp, stack = [], [start]
        seen.add(start)
        while stack:
            n = stack.pop()
            comp.append(n)
            for m in adj[n]:
                if m not in seen:
                    seen.add(m)
                    stack.append(m)
        if all(len(adj[n]) == 2 for n in comp):
            closed += 1
    return closed


def closed_loop_slots(pl, arcs=None):
    """Set of slots lying on a CLOSED loop (empty if the board is loop-feasible)."""
    A = arcs if arcs is not None else _arcs
    adj = defaultdict(list)
    owner = defaultdict(set)
    for s, (t, r) in pl.items():
        for (a_, b_) in A[t]:
            ends = []
            for (e, p) in (a_, b_):
                j = (e - r) % 3
                i, is_a = _edge_of[(s, j)]
                ends.append((i, p if is_a else 10 - p))
            adj[ends[0]].append(ends[1])
            adj[ends[1]].append(ends[0])
            owner[frozenset(ends)].add(s)
    seen, bad = set(), set()
    for start in adj:
        if start in seen:
            continue
        comp, stack = [], [start]
        seen.add(start)
        while stack:
            n = stack.pop()
            comp.append(n)
            for m in adj[n]:
                if m not in seen:
                    seen.add(m)
                    stack.append(m)
        if all(len(adj[n]) == 2 for n in comp):
            cs = set(comp)
            for key, ss in owner.items():
                if key <= cs:
                    bad |= ss
    return bad
