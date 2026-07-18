"""
Diamond Dilemma - Pentagonal Bipyramid Board Geometry
Builds geometry from spec, runs self-tests, writes geometry.json and tiles.json.
"""

import json
import re
from itertools import product
from collections import defaultdict

# ---------------------------------------------------------------------------
# 1.  FACE DEFINITIONS
# ---------------------------------------------------------------------------
# Vertices: U (top apex), D (bottom apex), E0..E4 (equatorial, cyclic mod 5)
# Top faces Ti = (U, Ei, Ei+1)  – clockwise from outside
# Bottom faces Bi must be oriented so that each face-level edge is traversed
# once in each direction across the whole surface.
#
# Face-level edge inventory (directed, top faces first):
#   Ti goes U->Ei->Ei+1->U
#   So directed face-edges from Ti: (U,Ei), (Ei,Ei+1), (Ei+1,U)
#
# For Bi we need:
#   - The equatorial edge (Ei,Ei+1) must be traversed as (Ei+1,Ei) by Bi
#     (since Ti already uses (Ei,Ei+1))
#   - The "vertical" edge (D,Ei) must be traversed by Bi in one direction;
#     Bi-1 uses (D,Ei) in the other direction if it goes (D,Ei,Ei-1,...).
#     Let Bi = (D, Ei+1, Ei).
#     Then Bi directed edges: (D,Ei+1), (Ei+1,Ei), (Ei,D)
#
# Verify: equatorial (Ei,Ei+1) from Ti and (Ei+1,Ei) from Bi — OK, opposite dirs.
#         vertical (D,Ei): from Bi-1=(D,Ei,Ei-1) we get edge (D,Ei); from Bi=(D,Ei+1,Ei) we get (Ei,D) — OK.
#         (U,Ei): from Ti=(U,Ei,Ei+1) we get (U,Ei); from Ti-1=(U,Ei-1,Ei) we get (Ei,U) — OK.
#
# So: Ti = (U, Ei, E(i+1 mod 5))
#     Bi = (D, E(i+1 mod 5), Ei)

VERTICES = ['U', 'D'] + [f'E{i}' for i in range(5)]  # 7 vertices

def V(name):
    return name  # just use the string as the vertex label

def top_face(i):
    """Corners of top face Ti in CW-from-outside order."""
    return ('U', f'E{i % 5}', f'E{(i+1) % 5}')

def bot_face(i):
    """Corners of bottom face Bi in CW-from-outside order."""
    return ('D', f'E{(i+1) % 5}', f'E{i % 5}')

FACES = []  # list of (name, (A, B, C))
for i in range(5):
    FACES.append((f'T{i}', top_face(i)))
for i in range(5):
    FACES.append((f'B{i}', bot_face(i)))

# Face adjacency at face level: which face-edge (A,B) is shared between face pairs?
# Ti-T(i+1): share (U, E(i+1))  — Ti has directed edge (E(i+1)->U), T(i+1) has (U->E(i+1))
# Ti-Bi:     share (Ei, E(i+1)) — Ti has (Ei->E(i+1)), Bi has (E(i+1)->Ei)
# Bi-B(i+1): share (D, E(i+1))  — Bi has (D->E(i+1)), B(i+1) has (E(i+1)->D)...
#            wait, let me recheck.
#            Bi=(D,E(i+1),Ei): directed edges (D->E(i+1)), (E(i+1)->Ei), (Ei->D)
#            B(i+1)=(D,E(i+2),E(i+1)): directed edges (D->E(i+2)), (E(i+2)->E(i+1)), (E(i+1)->D)
#            Shared vertices: D and E(i+1). Edge (D,E(i+1)): Bi has (D->E(i+1)), B(i+1) has (E(i+1)->D). OK!

# ---------------------------------------------------------------------------
# 2.  GLOBAL POINT ID SYSTEM
# ---------------------------------------------------------------------------
# A lattice point (a,b,c) on face (A,B,C) with a+b+c=4:
#   - corner: one coord=4 -> vertex label (e.g. A if a=4)
#   - edge between corners X,Y: two nonzero coords, one zero
#       if a=0: point is on edge B-C, parameterized as b*B+c*C with b+c=4
#           parameter from B is b... but we need to track global edge direction
#       The face's directed edges are A->B, B->C, C->A (CW from outside).
#       Edge between B and C (a=0): "edge(B,C), k from B" where k=b (1..3)
#       Edge between A and C (b=0): "edge(A,C), k from A" where k=a (1..3)  -- wait, a coord means from A
#           Actually if b=0, the point is on the A-C edge. coord a means "a steps from A toward C"
#           so parameter from A is a (since (a*A+c*C)/4 with a+c=4).
#       Edge between A and B (c=0): "edge(A,B), k from A" where k=a (1..3)
#   - interior: all three coords nonzero, unique to face

def global_point_id(face_name, corners, a, b, c):
    """
    Return a canonical global point ID for barycentric coords (a,b,c) on face
    with corners (A,B,C).
    """
    A, B, C = corners
    assert a + b + c == 4
    assert a >= 0 and b >= 0 and c >= 0

    # Corner points
    if a == 4:
        return A
    if b == 4:
        return B
    if c == 4:
        return C

    # Edge points (exactly one coord is 0)
    if a == 0:
        # On edge B-C, parameter b from B (b in 1..3)
        return canonical_edge_point(B, C, b)
    if b == 0:
        # On edge A-C, parameter a from A (a in 1..3)
        # Edge goes A->C (since CW order is A->B->C->A, the edge A-C is C->A directed,
        # but for the undirected edge we just use canonical form)
        return canonical_edge_point(A, C, a)
    if c == 0:
        # On edge A-B, parameter a from A (a in 1..3)
        return canonical_edge_point(A, B, a)

    # Interior point: private to this face
    return (face_name, a, b, c)


def canonical_edge_point(X, Y, k_from_X):
    """
    Canonical ID for the point k_from_X/4 of the way from X to Y.
    We canonicalize by putting the 'smaller' vertex first (alphabetically),
    adjusting k accordingly.
    """
    # Canonical order: sort vertices lexicographically
    if X < Y:
        return ('edge', X, Y, k_from_X)
    else:
        # reverse: k from Y = 4 - k_from_X
        return ('edge', Y, X, 4 - k_from_X)


# ---------------------------------------------------------------------------
# 3.  BUILD ALL SLOTS (small triangles)
# ---------------------------------------------------------------------------
# Each face F with corners (A,B,C) in CW order has 16 slots:
#  - 10 up-triangles: for a+b+c=3, up-tri = {(a+1,b,c),(a,b+1,c),(a,b,c+1)}
#    In CW order (inheriting the face's CW orientation): (a+1,b,c), (a,b+1,c), (a,b,c+1)
#    This is: corner0=(a+1,b,c) has more 'a', corner1=(a,b+1,c), corner2=(a,b,c+1)
#    Direction: going from corner0 to corner1 to corner2 to corner0.
#    We need to verify these are CW when viewed from outside.
#    The face (A,B,C) is CW. An up-triangle at (a,b,c) with a+b+c=3
#    points in the same orientation as the face (up = same orientation as big triangle).
#  - 6 down-triangles: for a+b+c=2, down-tri = {(a,b+1,c+1),(a+1,b,c+1),(a+1,b+1,c)}
#    In CW order (down-triangles have reversed orientation relative to up-triangles):
#    (a+1,b+1,c), (a+1,b,c+1), (a,b+1,c+1)
#    (reversed from the "natural" order to maintain CW-from-outside)

def up_triangle_corners(a, b, c):
    """Returns the 3 corners of an up-triangle in CW-from-outside order."""
    return [(a+1, b, c), (a, b+1, c), (a, b, c+1)]

def down_triangle_corners(a, b, c):
    """Returns the 3 corners of a down-triangle in CW-from-outside order."""
    # The order (a,b+1,c+1),(a+1,b,c+1),(a+1,b+1,c) has the SAME winding as the
    # face (A,B,C): with A=(0,0),B=(1,0),C=(0,1), successive corner differences
    # are (A-B)/4=(-1,0) then (B-C)/4=(1,-1), cross = +1, identical to the
    # up-triangle winding. Down-triangles point the other way but wind the same.
    return [(a, b+1, c+1), (a+1, b, c+1), (a+1, b+1, c)]

SLOTS = []  # list of dicts

for face_name, corners in FACES:
    A, B, C = corners
    # Up-triangles
    for a in range(4):
        for b in range(4):
            c = 3 - a - b
            if c < 0:
                continue
            pts = up_triangle_corners(a, b, c)
            global_pts = [global_point_id(face_name, corners, *p) for p in pts]
            SLOTS.append({
                'face': face_name,
                'type': 'up',
                'bary': (a, b, c),  # base barycentric for the up-tri
                'corners_bary': pts,
                'corners': global_pts,
            })
    # Down-triangles
    for a in range(3):
        for b in range(3):
            c = 2 - a - b
            if c < 0:
                continue
            pts = down_triangle_corners(a, b, c)
            global_pts = [global_point_id(face_name, corners, *p) for p in pts]
            SLOTS.append({
                'face': face_name,
                'type': 'down',
                'bary': (a, b, c),
                'corners_bary': pts,
                'corners': global_pts,
            })

assert len(SLOTS) == 160, f"Expected 160 slots, got {len(SLOTS)}"

# Assign slot indices
for idx, slot in enumerate(SLOTS):
    slot['idx'] = idx

# ---------------------------------------------------------------------------
# 4.  BUILD GLOBAL POINTS AND VERIFY COUNT
# ---------------------------------------------------------------------------
all_point_ids = set()
for slot in SLOTS:
    for pt in slot['corners']:
        all_point_ids.add(pt)

# Encode points for JSON serialization
def encode_pt(pt):
    if isinstance(pt, str):
        return pt
    if isinstance(pt, tuple):
        return list(pt)
    return pt

# Verify counts
vertex_pts = [p for p in all_point_ids if isinstance(p, str)]
edge_pts = [p for p in all_point_ids if isinstance(p, tuple) and p[0] == 'edge']
interior_pts = [p for p in all_point_ids if isinstance(p, tuple) and p[0] != 'edge']

print(f"Vertex points: {len(vertex_pts)} (expected 7)")
print(f"Edge points: {len(edge_pts)} (expected 45)")
print(f"Interior points: {len(interior_pts)} (expected 30)")
print(f"Total points: {len(all_point_ids)} (expected 82)")

# ---------------------------------------------------------------------------
# 5.  BUILD SMALL EDGES AND ADJACENCY
# ---------------------------------------------------------------------------
# Each slot has 3 directed edges: (corners[0]->corners[1]), (corners[1]->corners[2]), (corners[2]->corners[0])
# Two slots are adjacent iff they share an undirected edge.
# The shared edge must be traversed in opposite directions by the two slots
# (consistent orientation = each undirected edge appears once in each direction).

# Map from frozenset of 2 points -> list of (slot_idx, edge_index)
edge_to_slots = defaultdict(list)

for slot in SLOTS:
    pts = slot['corners']
    for ei in range(3):
        u = pts[ei]
        v = pts[(ei + 1) % 3]
        key = (u, v)  # directed
        undirected = frozenset([id(u) if False else str(u), str(v)])
        # Use a canonical undirected key
        ukey = tuple(sorted([str(u), str(v)]))
        edge_to_slots[ukey].append((slot['idx'], ei, u, v))

# Build adjacency: each undirected edge should have exactly 2 directed traversals (in opposite dirs)
EDGES = []  # list of ((slotA, eA), (slotB, eB), within_face)

def pt_str(pt):
    return str(pt)

edge_map = defaultdict(list)
for slot in SLOTS:
    pts = slot['corners']
    for ei in range(3):
        u = pts[ei]
        v = pts[(ei + 1) % 3]
        ukey = tuple(sorted([pt_str(u), pt_str(v)]))
        edge_map[ukey].append((slot['idx'], ei, pt_str(u), pt_str(v)))

double_cover_ok = True
for ukey, entries in edge_map.items():
    if len(entries) != 2:
        print(f"ERROR: edge {ukey} has {len(entries)} traversals (expected 2)")
        double_cover_ok = False
        continue
    (sA, eA, uA, vA), (sB, eB, uB, vB) = entries
    # Check opposite directions
    if not (uA == vB and vA == uB):
        print(f"ERROR: edge {ukey} not traversed in opposite directions: {uA}->{vA} and {uB}->{vB}")
        double_cover_ok = False
    within = SLOTS[sA]['face'] == SLOTS[sB]['face']
    EDGES.append(((sA, eA), (sB, eB), within))

# ---------------------------------------------------------------------------
# 6.  SELF-TEST 1: COUNTS
# ---------------------------------------------------------------------------
print("\n--- SELF-TEST 1: Counts ---")
n_slots = len(SLOTS)
n_edges = len(EDGES)
n_points = len(all_point_ids)
euler = n_points - n_edges + n_slots

print(f"Slots: {n_slots} (expected 160) -> {'PASS' if n_slots == 160 else 'FAIL'}")
print(f"Edges: {n_edges} (expected 240) -> {'PASS' if n_edges == 240 else 'FAIL'}")
print(f"Points: {n_points} (expected 82) -> {'PASS' if n_points == 82 else 'FAIL'}")
print(f"Euler: {n_points} - {n_edges} + {n_slots} = {euler} (expected 2) -> {'PASS' if euler == 2 else 'FAIL'}")

TEST1 = (n_slots == 160 and n_edges == 240 and n_points == 82 and euler == 2)

# ---------------------------------------------------------------------------
# 7.  SELF-TEST 2: DOUBLE COVER
# ---------------------------------------------------------------------------
print("\n--- SELF-TEST 2: Double Cover ---")
# Already checked above; verify all edges have exactly 2 traversals in opposite dirs
all_directed = []
for slot in SLOTS:
    pts = slot['corners']
    for ei in range(3):
        u = pt_str(pts[ei])
        v = pt_str(pts[(ei + 1) % 3])
        all_directed.append((u, v))

directed_counts = defaultdict(int)
for u, v in all_directed:
    directed_counts[(u, v)] += 1

bad_directed = [(e, c) for e, c in directed_counts.items() if c != 1]
TEST2 = len(bad_directed) == 0 and double_cover_ok
print(f"Double cover (each directed edge exactly once): {'PASS' if TEST2 else 'FAIL'}")
if not TEST2:
    for e, c in bad_directed[:5]:
        print(f"  {e}: {c} times")

# ---------------------------------------------------------------------------
# 8.  SELF-TEST 3: WITHIN/CROSS-FACE EDGE COUNTS
# ---------------------------------------------------------------------------
print("\n--- SELF-TEST 3: Within/Cross-Face Edges ---")
within_edges = [(e, w) for e, w in [(e[:2], e[2]) for e in EDGES] if w]
cross_edges = [(e, w) for e, w in [(e[:2], e[2]) for e in EDGES] if not w]

n_within = sum(1 for e in EDGES if e[2])
n_cross = sum(1 for e in EDGES if not e[2])

print(f"Within-face edges: {n_within} (expected 180) -> {'PASS' if n_within == 180 else 'FAIL'}")
print(f"Cross-face edges: {n_cross} (expected 60) -> {'PASS' if n_cross == 60 else 'FAIL'}")

# Each face-pair that is adjacent should have exactly 4 cross-face edges
# Find face pairs
face_pair_counts = defaultdict(int)
for e in EDGES:
    if not e[2]:  # cross-face
        sA, eA = e[0]
        sB, eB = e[1]
        fA = SLOTS[sA]['face']
        fB = SLOTS[sB]['face']
        pair = tuple(sorted([fA, fB]))
        face_pair_counts[pair] += 1

print(f"Number of adjacent face-pairs: {len(face_pair_counts)} (expected 15)")
bad_pairs = [(p, c) for p, c in face_pair_counts.items() if c != 4]
print(f"Face-pairs with != 4 cross-edges: {len(bad_pairs)} (expected 0) -> {'PASS' if len(bad_pairs) == 0 else 'FAIL'}")

# Each face should have 12 boundary (cross-face) small-edges and 4 per neighbor
face_cross = defaultdict(lambda: defaultdict(int))
for e in EDGES:
    if not e[2]:
        sA, eA = e[0]
        sB, eB = e[1]
        fA = SLOTS[sA]['face']
        fB = SLOTS[sB]['face']
        face_cross[fA][fB] += 1
        face_cross[fB][fA] += 1

face_boundary_ok = True
for fname, neighbors in face_cross.items():
    total = sum(neighbors.values())
    if total != 12:
        print(f"  Face {fname} has {total} boundary edges (expected 12)")
        face_boundary_ok = False
    for nf, cnt in neighbors.items():
        if cnt != 4:
            print(f"  Face {fname}-{nf} has {cnt} shared edges (expected 4)")
            face_boundary_ok = False

print(f"All faces have 12 boundary edges, 4 per neighbor: {'PASS' if face_boundary_ok else 'FAIL'}")

TEST3 = (n_within == 180 and n_cross == 60 and len(face_pair_counts) == 15 and
         len(bad_pairs) == 0 and face_boundary_ok)

# ---------------------------------------------------------------------------
# 9.  SYMMETRY GROUP
# ---------------------------------------------------------------------------
# The rotation group of the pentagonal bipyramid has order 10.
# Generators:
#   rho: Ei -> E(i+1 mod 5), U->U, D->D (rotation by 2pi/5 around the U-D axis)
#   tau: U<->D, E0->E0, E1<->E4, E2<->E3 (C2 rotation through E0 and midpoint of E2-E3)
#
# First, build the 10 group elements as permutations of global points.
# Then induce permutations on slots.

# Assign integer IDs to all global points
point_list = sorted(all_point_ids, key=lambda x: str(x))
point_to_idx = {p: i for i, p in enumerate(point_list)}
n_pts = len(point_list)

def apply_vertex_map(vm, pt):
    """Apply a vertex permutation vm (dict) to a global point."""
    if isinstance(pt, str):
        return vm.get(pt, pt)
    if isinstance(pt, tuple):
        if pt[0] == 'edge':
            _, X, Y, k = pt
            nX = vm.get(X, X)
            nY = vm.get(Y, Y)
            # canonical_edge_point(nX, nY, k)
            return canonical_edge_point(nX, nY, k)
        else:
            # interior point: (face_name, a, b, c)
            # need to apply the face permutation
            face_name, a, b, c = pt
            new_face, new_abc = apply_face_map_interior(vm, face_name, a, b, c)
            return (new_face, *new_abc)
    raise ValueError(f"Unknown point type: {pt}")

def apply_face_map_interior(vm, face_name, a, b, c):
    """
    For an interior point on face face_name with barycentric (a,b,c),
    compute the image face and new barycentric coords under vertex map vm.
    """
    # Find the face
    face_dict = {fn: cs for fn, cs in FACES}
    corners = face_dict[face_name]
    A, B, C = corners
    nA = vm.get(A, A)
    nB = vm.get(B, B)
    nC = vm.get(C, C)
    # Find the image face (the face with corners being a permutation of (nA, nB, nC))
    target_corners = {nA, nB, nC}
    new_face_name = None
    new_corners = None
    for fn, cs in FACES:
        if set(cs) == target_corners:
            new_face_name = fn
            new_corners = cs
            break
    assert new_face_name is not None, f"No face found for {target_corners}"
    # The image face has corners (nA', nB', nC') in some CW order.
    # We need to find the permutation of (a,b,c) coords.
    # The physical point is (a*A + b*B + c*C)/4.
    # Image physical point is (a*nA + b*nB + c*nC)/4.
    # Express in terms of new_corners:
    nA_idx = new_corners.index(nA)
    nB_idx = new_corners.index(nB)
    nC_idx = new_corners.index(nC)
    new_abc = [0, 0, 0]
    new_abc[nA_idx] += a
    new_abc[nB_idx] += b
    new_abc[nC_idx] += c
    return new_face_name, tuple(new_abc)

# Build the 10 group elements
# rho: Ei -> E(i+1 mod 5), U->U, D->D
def make_rho(k):
    """rho^k"""
    vm = {'U': 'U', 'D': 'D'}
    for i in range(5):
        vm[f'E{i}'] = f'E{(i + k) % 5}'
    return vm

# tau: U<->D, E0->E0, E1<->E4, E2<->E3
tau_vm = {'U': 'D', 'D': 'U', 'E0': 'E0', 'E1': 'E4', 'E4': 'E1', 'E2': 'E3', 'E3': 'E2'}

def compose_vm(vm1, vm2):
    """Apply vm1 then vm2."""
    result = {}
    for v in VERTICES:
        result[v] = vm2.get(vm1.get(v, v), vm1.get(v, v))
    return result

# Generate all 10 group elements: rho^k for k=0..4, and tau*rho^k for k=0..4
identity_vm = {v: v for v in VERTICES}
GROUP_VMS = []
for k in range(5):
    GROUP_VMS.append(make_rho(k))
for k in range(5):
    GROUP_VMS.append(compose_vm(tau_vm, make_rho(k)))

assert len(GROUP_VMS) == 10

# For each group element, compute the point permutation (as dict: point -> point)
def build_point_perm(vm):
    """Build permutation of all global points under vertex map vm."""
    perm = {}
    for pt in all_point_ids:
        perm[pt] = apply_vertex_map(vm, pt)
    return perm

print("\nBuilding point permutations...")
point_perms = [build_point_perm(vm) for vm in GROUP_VMS]

# Verify all image points are in all_point_ids
for gi, perm in enumerate(point_perms):
    for pt, img in perm.items():
        if img not in all_point_ids:
            print(f"  ERROR: group element {gi}: image {img} not in point set")

# Now induce slot permutations
# A slot is identified by its (face, type, bary) or equivalently its 3 corners.
# Under a symmetry, the 3 corners are permuted, mapping to a new slot.

# Build a dict from frozenset of corners -> slot index
corners_to_slot = {}
for slot in SLOTS:
    key = tuple(sorted(str(p) for p in slot['corners']))
    corners_to_slot[key] = slot['idx']

def build_slot_perm(point_perm):
    """
    Build a permutation of slots (and edge-index mapping) from a point permutation.
    Returns (slot_perm, edge_perm) where:
      slot_perm[i] = j means slot i maps to slot j
      edge_perm[i] = list of 3 ints: edge k of slot i maps to edge edge_perm[i][k] of slot slot_perm[i]
    """
    slot_perm = {}
    edge_idx_perm = {}

    for slot in SLOTS:
        src_idx = slot['idx']
        src_pts = slot['corners']
        # Map each corner
        img_pts = [point_perm[p] for p in src_pts]
        key = tuple(sorted(str(p) for p in img_pts))
        if key not in corners_to_slot:
            print(f"  ERROR: image of slot {src_idx} not found: {key}")
            return None, None
        dst_idx = corners_to_slot[key]
        slot_perm[src_idx] = dst_idx

        # Determine edge-index mapping
        # Slot's directed edges: (pts[0]->pts[1], pts[1]->pts[2], pts[2]->pts[0])
        # Image slot's directed edges: (dst_pts[0]->dst_pts[1], ...)
        dst_slot = SLOTS[dst_idx]
        dst_pts = dst_slot['corners']
        # Find where each img_pt appears in dst_pts
        # The image of edge k (img_pts[k] -> img_pts[(k+1)%3]) should correspond
        # to some edge of dst_slot.
        # Since proper rotations preserve orientation, the cyclic order should be preserved.
        # Find the position of img_pts[0] in dst_pts
        try:
            pos0 = dst_pts.index(img_pts[0])
        except ValueError:
            # img_pts[0] might not match directly due to point representation
            # Try string matching
            img_strs = [str(p) for p in img_pts]
            dst_strs = [str(p) for p in dst_pts]
            pos0 = dst_strs.index(img_strs[0])

        # Check that the cyclic order matches
        edge_map_local = {}
        img_strs = [str(p) for p in img_pts]
        dst_strs = [str(p) for p in dst_pts]
        for k in range(3):
            img_u = img_strs[k]
            img_v = img_strs[(k + 1) % 3]
            # Find this directed edge in dst_slot
            found = False
            for ek in range(3):
                if dst_strs[ek] == img_u and dst_strs[(ek + 1) % 3] == img_v:
                    edge_map_local[k] = ek
                    found = True
                    break
            if not found:
                print(f"  ERROR: edge {k} of slot {src_idx} not found in dst slot {dst_idx}")
                print(f"    img_pts: {img_strs}")
                print(f"    dst_pts: {dst_strs}")
        edge_idx_perm[src_idx] = edge_map_local

    return slot_perm, edge_idx_perm

print("Building slot permutations...")
slot_perms = []
edge_idx_perms = []
for gi, pp in enumerate(point_perms):
    sp, ep = build_slot_perm(pp)
    slot_perms.append(sp)
    edge_idx_perms.append(ep)

# ---------------------------------------------------------------------------
# 10.  SELF-TEST 4: SYMMETRY
# ---------------------------------------------------------------------------
print("\n--- SELF-TEST 4: Symmetry ---")

# Group closure: composing any two elements gives an element in the group
def compose_slot_perms(sp1, sp2):
    """sp1 then sp2."""
    return {i: sp2[sp1[i]] for i in range(160)}

sym_ok = True

# Check group closure
def slot_perm_to_tuple(sp):
    return tuple(sp[i] for i in range(160))

group_set = set(slot_perm_to_tuple(sp) for sp in slot_perms)
for i in range(10):
    for j in range(10):
        comp = compose_slot_perms(slot_perms[i], slot_perms[j])
        if slot_perm_to_tuple(comp) not in group_set:
            print(f"  ERROR: composition of element {i} and {j} not in group")
            sym_ok = False
            break

print(f"Group closure (10 elements): {'PASS' if sym_ok else 'FAIL'}")

# Check slot maps to slot (already done above by construction)
# Check adjacency preservation
adj_set = set()
for e in EDGES:
    (sA, eA), (sB, eB), within = e
    adj_set.add(frozenset([sA, sB]))

adj_pres = True
for gi, sp in enumerate(slot_perms):
    for fs in adj_set:
        fs_list = list(fs)
        img_fs = frozenset([sp[fs_list[0]], sp[fs_list[1]]])
        if img_fs not in adj_set:
            print(f"  ERROR: element {gi} does not preserve adjacency: {fs} -> {img_fs}")
            adj_pres = False
            break
    if not adj_pres:
        break
print(f"Adjacency preservation: {'PASS' if adj_pres else 'FAIL'}")

# Check orientation preservation (edge-index mapping is a cyclic shift, not reversal)
orient_ok = True
for gi in range(10):
    ep = edge_idx_perms[gi]
    for slot_idx in range(160):
        em = ep[slot_idx]
        # em should be a cyclic shift: em[k] = (k + shift) % 3
        shifts = [(em[k] - k) % 3 for k in range(3)]
        if len(set(shifts)) != 1:
            print(f"  ERROR: element {gi}, slot {slot_idx}: edge map {em} is not a cyclic shift")
            orient_ok = False
            break
    if not orient_ok:
        break
print(f"Orientation preservation (cyclic edge maps): {'PASS' if orient_ok else 'FAIL'}")

# Check no nontrivial element fixes any slot
no_fixed = True
for gi in range(1, 10):
    sp = slot_perms[gi]
    fixed = [i for i in range(160) if sp[i] == i]
    if fixed:
        print(f"  ERROR: element {gi} fixes slots {fixed}")
        no_fixed = False
print(f"No nontrivial element fixes any slot: {'PASS' if no_fixed else 'FAIL'}")

# Check 16 orbits of size 10
from collections import defaultdict
orbit_map = {}
visited = set()
orbits = []
for start in range(160):
    if start in visited:
        continue
    orbit = set()
    queue = [start]
    while queue:
        s = queue.pop()
        if s in orbit:
            continue
        orbit.add(s)
        for gi in range(10):
            img = slot_perms[gi][s]
            if img not in orbit:
                queue.append(img)
    orbits.append(orbit)
    visited |= orbit

orbit_sizes = [len(o) for o in orbits]
orbit_ok = len(orbits) == 16 and all(s == 10 for s in orbit_sizes)
print(f"16 orbits of size 10: {len(orbits)} orbits, sizes {set(orbit_sizes)} -> {'PASS' if orbit_ok else 'FAIL'}")

TEST4 = sym_ok and adj_pres and orient_ok and no_fixed and orbit_ok

# ---------------------------------------------------------------------------
# 11.  PARSE TILES
# ---------------------------------------------------------------------------
print("\n--- Parsing Tiles ---")

with open('diamonddilemma.txt', 'r') as f:
    raw = f.read()

tiles = []
# Each data line has exactly 3 space-separated 11-bit strings (possibly with a comment)
pattern = re.compile(r'\b([01]{11})\s+([01]{11})\s+([01]{11})\b')
for line in raw.split('\n'):
    # Skip prose/blank lines
    m = pattern.search(line)
    if m:
        tiles.append([m.group(1), m.group(2), m.group(3)])

print(f"Tiles parsed: {len(tiles)} (expected 160)")

# ---------------------------------------------------------------------------
# 12.  SELF-TEST 5: TILES
# ---------------------------------------------------------------------------
print("\n--- SELF-TEST 5: Tiles ---")

t5_count = len(tiles) == 160
print(f"160 tiles: {'PASS' if t5_count else 'FAIL'}")

# Even bit count per tile
def bit_count(s):
    return s.count('1')

all_bits_even = True
for i, t in enumerate(tiles):
    total = sum(bit_count(e) for e in t)
    if total % 2 != 0:
        print(f"  Tile {i} has odd bit count: {total}")
        all_bits_even = False
print(f"Each tile has even total bit count: {'PASS' if all_bits_even else 'FAIL'}")

# Grand total bits
grand_total = sum(bit_count(e) for t in tiles for e in t)
print(f"Grand total bits: {grand_total} (expected 730) -> {'PASS' if grand_total == 730 else 'FAIL'}")

# Distinct patterns
all_patterns = [e for t in tiles for e in t]
distinct = len(set(all_patterns))
print(f"Distinct patterns: {distinct} (expected 83) -> {'PASS' if distinct == 83 else 'FAIL'}")

TEST5 = t5_count and all_bits_even and grand_total == 730 and distinct == 83

# ---------------------------------------------------------------------------
# 13.  SUMMARY OF TESTS
# ---------------------------------------------------------------------------
print("\n=== TEST SUMMARY ===")
print(f"TEST 1 (Counts + Euler): {'PASS' if TEST1 else 'FAIL'}")
print(f"TEST 2 (Double Cover): {'PASS' if TEST2 else 'FAIL'}")
print(f"TEST 3 (Within/Cross-Face): {'PASS' if TEST3 else 'FAIL'}")
print(f"TEST 4 (Symmetry): {'PASS' if TEST4 else 'FAIL'}")
print(f"TEST 5 (Tiles): {'PASS' if TEST5 else 'FAIL'}")
all_pass = TEST1 and TEST2 and TEST3 and TEST4 and TEST5
print(f"ALL TESTS: {'PASS' if all_pass else 'FAIL'}")

# ---------------------------------------------------------------------------
# 14.  WRITE JSON OUTPUT
# ---------------------------------------------------------------------------
print("\n--- Writing JSON files ---")

# Point serialization helper
def pt_to_json(pt):
    if isinstance(pt, str):
        return pt
    if isinstance(pt, tuple):
        return list(pt)
    return str(pt)

# geometry.json
slots_json = []
for slot in SLOTS:
    pts = slot['corners']
    directed_edges = []
    for ei in range(3):
        u = pts[ei]
        v = pts[(ei + 1) % 3]
        directed_edges.append([pt_to_json(u), pt_to_json(v)])
    slots_json.append({
        'idx': slot['idx'],
        'face': slot['face'],
        'type': slot['type'],
        'bary': list(slot['bary']),
        'corners': [pt_to_json(p) for p in pts],
        'directed_edges': directed_edges,
    })

edges_json = []
for e in EDGES:
    (sA, eA), (sB, eB), within = e
    edges_json.append({
        'slotA': sA,
        'edgeA': eA,
        'slotB': sB,
        'edgeB': eB,
        'within_face': within,
    })

symmetry_json = []
for gi in range(10):
    sp = slot_perms[gi]
    ep = edge_idx_perms[gi]
    symmetry_json.append({
        'slot_perm': [sp[i] for i in range(160)],
        'edge_perm': [[ep[i][k] for k in range(3)] for i in range(160)],
    })

geometry = {
    'slots': slots_json,
    'edges': edges_json,
    'symmetry': symmetry_json,
}

with open('geometry.json', 'w') as f:
    json.dump(geometry, f, indent=2)
print("Written geometry.json")

# tiles.json
with open('tiles.json', 'w') as f:
    json.dump(tiles, f, indent=2)
print("Written tiles.json")

print("\nDone.")
