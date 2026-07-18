"""bp_solver.py -- Loopy belief-propagation (sum-product) + decimation solver
for the Diamond Dilemma edge-matching problem.

======================================================================
PROBLEM RECAP
======================================================================
n slots (160 for gold). Each slot s gets a placement (tile t, rotation r).
Constraints:
  (a) every tile used in exactly one slot (a permutation of tiles to slots)
  (b) for every board edge (s,j)-(b,k), the pattern tile t shows on slot-edge j
      (which is tiles[t][(j+r)%3]) must equal the REVERSE of whatever the
      neighbor shows on its facing edge k.
Placement convention: tile t at rotation r in slot s puts tile-edge (j+r)%3
onto slot-edge j (see sat_solver.py / verify_solution.py -- must match).

======================================================================
KEY EFFICIENCY TRICK: messages over PATTERNS, not over (tile,rot) pairs
======================================================================
A slot has up to n*3 (tile,rot) combinations (480 for gold), which is too
large to pass as dense messages along O(n) edges *and* it's wasteful: the
only thing a board edge factor cares about is which of the ~83 DISTINCT
EDGE PATTERNS the slot shows on that side. So:

  P            = sorted list of every distinct pattern string that appears
                 as some tiles[t][j] (both orientations are literal strings
                 already in the data; we do NOT need to add reverses of
                 patterns that never occur, but we do need revid to map a
                 pattern's reverse-string back to its OWN id if that reverse
                 string also happens to occur in P -- otherwise revid=-1,
                 meaning "no tile anywhere can face this pattern" i.e. any
                 slot showing this pattern on a boundary can never be
                 satisfied, a structural dead pattern).
  pat_at[t][r][j] = id in P of tiles[t][(j+r)%3]                 (480 x 3 gather table per tile... actually [n_tiles][3][3])
  revid[pid]      = id of reverse(P[pid]) in P, or -1 if that reverse
                    string is not itself a member of P.

Messages m_{edge}(p) are vectors of length |P| (~83 numbers), NOT length
480. This collapses the factor-graph message size from O(tiles*rot) to
O(|P|) per directed board edge -- the whole point of the assignment.

======================================================================
FACTOR GRAPH
======================================================================
Variable nodes: one per slot s, domain = list of surviving (t,r) pairs
  (shrinks during decimation as tiles get consumed / slots get fixed).
Factor nodes: one per undirected board edge (s,j)|(b,k), enforcing
  pat_at[t_s][r_s][j] == revid[pat_at[t_b][r_b][k]]  (compatibility).

Sum-product BP alternates two message types along every DIRECTED board edge
s -> b (there are 2*n_edges of these, 480 for gold):
  1. slot-to-pattern "what I show":  a length-|P| vector
         out_s->edge_j(p) = sum over (t,r) in dom(s) with pat_at[t][r][j]==p
                                 of belief_local(s,t,r; excluding this edge's
                                 own incoming message, i.e. divide it out)
     Implemented as a scatter-add (or one-hot matmul) over dom(s).
  2. pattern-to-slot "what you may show" = the factor just requires
     revid[p] to be the incoming pattern from the other side, so the
     MESSAGE b sends to s is simply: msg[p] = incoming_belief_b(revid[p])
     if revid[p] != -1 else 0 (a PERMUTATION of the neighbor's outgoing
     pattern-vector through revid, an O(|P|) gather -- no summation
     needed because a proper "edge factor" that's a 0/1 equality-after-
     revid map degenerates to routing, this *is* the sum-product update
     for an equality-type factor).

Per slot, the local (unnormalised) belief over its domain (t,r) is:
    b_s(t,r) = field[t] * prod_{j=0..2} incoming_msg_j( pat_at[t][r][j] )
where incoming_msg_j is the product of all OTHER slots' messages into edge j
of s -- for a tree/loopy BP with a single neighbor per edge slot j has only
ONE incoming message per edge (each slot-edge touches exactly one board
edge), so "excluding this edge's own message" for computing the outgoing
message on edge j means using the product over the OTHER TWO edges j'!=j,
still combined with field[t]. That's the standard sum-product cavity
computation but here it's especially cheap because each variable only has
3 attached factors (one per triangle edge).

======================================================================
TILE-UNIQUENESS ("done twice" as requested)
======================================================================
(a) SOFT FIELD: after each BP sweep, compute per-tile total "soft usage"
    u[t] = sum over unfixed slots s of belief_s(t) (belief_s(t) = sum_r
    normalised b_s(t,r)). Update field[t] <- exp(-lambda * max(0, u[t]-1))
    so tiles that look over-subscribed get suppressed (soft, damped into
    log-field to avoid oscillation). This nudges BP away from many slots
    wanting the same popular tile, without hard-enforcing the permutation.
(b) HARD constraint at decimation: whenever a slot is fixed to (t,r), tile
    t is immediately removed from every other slot's domain and field[t]
    is set to -inf (probability 0) everywhere else. This is exact and is
    what actually guarantees the permutation constraint in the end.

======================================================================
DAMPING / NUMERICS
======================================================================
All messages are kept as normalised probability vectors in LINEAR space
(not log) but every update re-normalises (sum to 1) immediately, which is
suffient to prevent underflow given |P|~83 and realistic factor counts
(no long multiplicative chains before a renormalisation point). Damping:
new_msg = alpha*old + (1-alpha)*computed, alpha=DAMPING (default 0.5),
renormalised after damping. Convergence: stop when max |new-old| over all
directed-edge messages < 1e-4, or after MAX_BP_ITERS.

======================================================================
DECIMATION LOOP
======================================================================
See module docstring further down (decimate()) -- run BP to convergence,
pick lowest-entropy unfixed slot, fix it (if consistent with fixed
neighbors), propagate hard tile removal, repeat; on contradiction (domain
wipeout) backtrack K fixations with taboo + noise; too many contradictions
in a row -> full restart with new RNG seed, keeping the best-ever valid
partial. Deepest valid partial is saved continuously.

======================================================================
CLI
======================================================================
    python bp_solver.py <instance.txt> <seconds> <seed>

Outputs:
    bp_solution.txt      -- written only if a FULL valid 160/160 assignment
                             is found ("slot:tile:rot ...", independently
                             re-verified before writing)
    bp_partial_best.txt  -- deepest-ever valid partial assignment (fixed
                             slots only), overwritten whenever improved
Progress printed to stdout: fixed=k/n contradictions=.. restarts=.. t=..
"""
import sys
import time
import numpy as np

from sat_solver import load_instance

# ----------------------------------------------------------------------
# Tunables
# ----------------------------------------------------------------------
MAX_BP_ITERS = 60
DAMPING = 0.9
CONV_TOL = 1e-4
LAMBDA_FIELD = 0.3          # soft-field uniqueness pressure strength
FIELD_DAMP = 0.5            # damping for the field update itself
BACKTRACK_K = 5             # undo this many fixations on contradiction
MAX_CONSEC_CONTRADICTIONS = 40   # before a full restart
TABOO_SIZE = 400
NOISE_SCALE = 0.05           # multiplicative message noise injected after backtrack


# ======================================================================
# Pattern-id infrastructure
# ======================================================================
def build_pattern_tables(tiles):
    """
    P        : list[str], sorted distinct patterns that occur anywhere in tiles
    pid_of   : dict pattern-string -> id in P
    revid    : np.array[len(P)] int, revid[p] = id of reverse(P[p]) in P,
               or -1 if that reverse string never occurs as a tile edge.
    pat_at   : np.array[n_tiles, 3, 3] int32, pat_at[t, r, j] = id of
               tiles[t][(j + r) % 3]
    """
    pat_set = set()
    for t in tiles:
        for p in t:
            pat_set.add(p)
    P = sorted(pat_set)
    pid_of = {p: i for i, p in enumerate(P)}
    n_p = len(P)

    revid = np.full(n_p, -1, dtype=np.int64)
    for i, p in enumerate(P):
        rp = p[::-1]
        revid[i] = pid_of.get(rp, -1)

    n_tiles = len(tiles)
    pat_at = np.zeros((n_tiles, 3, 3), dtype=np.int64)
    for t in range(n_tiles):
        for r in range(3):
            for j in range(3):
                pat_at[t, r, j] = pid_of[tiles[t][(j + r) % 3]]

    return P, pid_of, revid, pat_at


# ======================================================================
# Board-edge indexing: directed edges s->b for every (slot, local-edge j)
# ======================================================================
def build_edge_index(n, adj):
    """
    Returns:
      slot_edge_to_deid[s][j] = directed-edge id representing the message
                                  FLOWING INTO s ALONG local edge j, i.e. the
                                  message b(the neighbour on edge j) sends to s.
      partner[deid] = (b, k)  the neighbour slot & its local edge index for
                                that directed edge id (so deid identifies the
                                *receiving* (s,j) side).
      There are exactly 3*n directed message slots (n slots * 3 edges each),
      i.e. every undirected board edge contributes exactly 2 directed
      messages (one each way), and slot_edge_to_deid is simply a bijection
      slot*3+j -> deid (we just use deid = s*3+j directly, no separate
      array needed) -- kept as a function for documentation/clarity and to
      centralize the (b,k) lookups.
    """
    deid_of = np.zeros((n, 3), dtype=np.int64)  # deid_of[s,j] = s*3+j
    partner_slot = np.zeros((n, 3), dtype=np.int64)
    partner_edge = np.zeros((n, 3), dtype=np.int64)
    for s in range(n):
        for j in range(3):
            deid_of[s, j] = s * 3 + j
            b, k = adj[s][j]
            partner_slot[s, j] = b
            partner_edge[s, j] = k
    return deid_of, partner_slot, partner_edge


# ======================================================================
# Solver state
# ======================================================================
class BPState:
    """
    Holds all mutable state for one decimation run: domains, messages,
    fixed assignment, soft field, and the message arrays. Reusable across
    decimation steps (in-place updates) for speed.
    """

    def __init__(self, n, adj, tiles, seed_slots, seed_tile, rng):
        self.n = n
        self.adj = adj
        self.tiles = tiles
        self.rng = rng
        self.P, self.pid_of, self.revid, self.pat_at = build_pattern_tables(tiles)
        self.n_p = len(self.P)
        _, self.partner_slot, self.partner_edge = build_edge_index(n, adj)

        # domain[s] = list of (t, r) still allowed in slot s (as an array Kx2)
        # Start with the seed-tile symmetry breaking baked in exactly like
        # sat_solver.py: if len(seed_slots) < n, seed_tile can ONLY go in a
        # seed slot (breaks the huge rotational/tile-relabelling symmetry).
        self.seed_slots = set(seed_slots)
        self.seed_tile = seed_tile
        self.restrict_seed = len(seed_slots) < n

        self.domain = [None] * n            # list of ndarray[K,2] (tile,rot)
        self.dom_pat = [None] * n           # list of ndarray[K,3] pattern-ids per (t,r) per local edge j
        self._init_domains()

        self.fixed = [None] * n             # fixed[s] = (t, r) or None
        self.tile_used = np.zeros(n, dtype=bool)   # tile -> currently consumed by a fixed slot

        # messages[s, j] = length-n_p vector: the message flowing INTO slot s
        # along local edge j (i.e. sent by the neighbour on that edge,
        # describing the distribution over patterns the neighbour claims
        # it WILL show on the facing side, already permuted through revid
        # so it directly compares to what s could show on edge j).
        self.messages = np.full((n, 3, self.n_p), 1.0 / self.n_p, dtype=np.float64)

        # soft field per tile, in prob-multiplier space (>0). 1.0 = neutral.
        self.field = np.ones(n, dtype=np.float64)

    def _init_domains(self):
        n = self.n
        for s in range(n):
            if self.restrict_seed and s not in self.seed_slots:
                # seed tile forbidden here
                pairs = [(t, r) for t in range(n) for r in range(3) if t != self.seed_tile]
            elif self.restrict_seed and s in self.seed_slots:
                pairs = [(t, r) for t in range(n) for r in range(3)]
            else:
                pairs = [(t, r) for t in range(n) for r in range(3)]
            arr = np.array(pairs, dtype=np.int64)
            self.domain[s] = arr
            self._refresh_dom_pat(s)

    def _refresh_dom_pat(self, s):
        arr = self.domain[s]
        if arr.shape[0] == 0:
            self.dom_pat[s] = np.zeros((0, 3), dtype=np.int64)
            return
        t = arr[:, 0]
        r = arr[:, 1]
        self.dom_pat[s] = self.pat_at[t, r, :]   # [K,3]

    # ------------------------------------------------------------------
    def restrict_domain_to_tile_available(self, s):
        """Drop any (t,r) from domain[s] whose tile t is already used by a
        different FIXED slot. Called after any slot gets fixed."""
        if self.fixed[s] is not None:
            return
        arr = self.domain[s]
        if arr.shape[0] == 0:
            return
        keep = ~self.tile_used[arr[:, 0]]
        if not keep.all():
            self.domain[s] = arr[keep]
            self._refresh_dom_pat(s)

    def apply_tile_used_everywhere(self, tile):
        """Hard-remove `tile` from every unfixed slot's domain (uniqueness)."""
        for s in range(self.n):
            if self.fixed[s] is not None:
                continue
            arr = self.domain[s]
            if arr.shape[0] == 0:
                continue
            keep = arr[:, 0] != tile
            if not keep.all():
                self.domain[s] = arr[keep]
                self._refresh_dom_pat(s)

    # ------------------------------------------------------------------
    def local_belief(self, s):
        """
        Unnormalised belief vector over domain[s] rows: b_s(t,r) =
        field[t] * prod_j incoming_msg[s,j, pat_at[t,r,j]].
        Returns (weights ndarray[K], arr domain[s]) -- weights may be all
        zero if the domain is contradictory given current messages/fixed
        neighbours (a HARD zero happens only through domain pruning, not
        through this soft product, but we also apply a HARD compatibility
        check against already-fixed neighbours here so decimation never
        fixes an inconsistent placement).
        """
        arr = self.domain[s]
        K = arr.shape[0]
        if K == 0:
            return np.zeros(0), arr
        dp = self.dom_pat[s]  # [K,3]
        w = np.ones(K, dtype=np.float64)
        for j in range(3):
            b = self.adj[s][j][0]
            fixed_b = self.fixed[b]
            if fixed_b is not None:
                # HARD check: neighbour already fixed -> only patterns that
                # actually match its shown pattern survive.
                bt, br = fixed_b
                bk = self.adj[s][j][1]
                shown = self.pat_at[bt, br, bk]
                need = self.revid[shown]
                if need < 0:
                    return np.zeros(K), arr
                w = w * (dp[:, j] == need)
            else:
                msg = self.messages[s, j]
                w = w * msg[dp[:, j]]
        w = w * self.field[arr[:, 0]]
        return w, arr

    # ------------------------------------------------------------------
    def outgoing_message(self, s, j):
        """
        Compute the (unnormalised) length-n_p vector that slot s sends
        OUT along local edge j to its neighbour, i.e. the marginal
        distribution over "what pattern s will show on edge j", computed
        from the CAVITY belief (product over the OTHER two edges j'!=j
        only, per sum-product) then scattered into pattern-space by
        summing weight over all (t,r) sharing the same pat_at[t,r,j].
        If s is already fixed, this degenerates to a one-hot vector at
        the pattern it actually shows (still correctly consumed by
        revid on the receiving side).
        """
        if self.fixed[s] is not None:
            t, r = self.fixed[s]
            p = self.pat_at[t, r, j]
            out = np.zeros(self.n_p, dtype=np.float64)
            out[p] = 1.0
            return out

        arr = self.domain[s]
        K = arr.shape[0]
        if K == 0:
            return np.ones(self.n_p, dtype=np.float64) / self.n_p  # degenerate; caller handles emptiness elsewhere

        dp = self.dom_pat[s]  # [K,3]
        w = np.ones(K, dtype=np.float64)
        for jp in range(3):
            if jp == j:
                continue
            b = self.adj[s][jp][0]
            fixed_b = self.fixed[b]
            if fixed_b is not None:
                bt, br = fixed_b
                bk = self.adj[s][jp][1]
                shown = self.pat_at[bt, br, bk]
                need = self.revid[shown]
                if need < 0:
                    w = np.zeros(K)
                    break
                w = w * (dp[:, jp] == need)
            else:
                msg = self.messages[s, jp]
                w = w * msg[dp[:, jp]]
        w = w * self.field[arr[:, 0]]

        out = np.zeros(self.n_p, dtype=np.float64)
        # scatter-add: out[pattern] += w for each row's pattern on edge j
        np.add.at(out, dp[:, j], w)
        ssum = out.sum()
        if ssum <= 0 or not np.isfinite(ssum):
            # No consistent local option -- return uniform to keep BP
            # numerically alive; the hard contradiction is caught
            # elsewhere (domain size / local_belief all-zero check).
            return np.ones(self.n_p, dtype=np.float64) / self.n_p
        return out / ssum

    # ------------------------------------------------------------------
    def bp_sweep(self):
        """
        One synchronous BP sweep: compute all new outgoing messages from
        all slots' 3 edges, ROUTE them through revid to become the
        neighbour's incoming message, damp, renormalise. Returns the max
        abs change over all directed messages (for convergence check).
        """
        n = self.n
        new_out = np.empty((n, 3, self.n_p), dtype=np.float64)
        for s in range(n):
            for j in range(3):
                new_out[s, j] = self.outgoing_message(s, j)

        # Route: neighbour b receiving on its local edge k gets a message
        # over ITS OWN pattern space via revid: incoming_b,k(p) = new_out[s,j](revid[p])
        # (p is what b could show; match requires b's pattern's reverse to
        # equal what s shows, i.e. revid[p] == pattern s shows -> so the
        # weight for b showing pattern p is new_out[s,j][revid[p]] when
        # revid[p] != -1, else 0).
        revid = self.revid
        valid = revid >= 0
        gather_idx = np.where(valid, revid, 0)

        new_messages = np.empty_like(self.messages)
        for s in range(n):
            for j in range(3):
                b, k = self.adj[s][j]
                src = new_out[s, j]                # what s shows on edge j
                routed = np.where(valid, src[gather_idx], 0.0)  # over b's pattern space at edge k
                total = routed.sum()
                if total <= 0 or not np.isfinite(total):
                    routed = np.ones(self.n_p, dtype=np.float64) / self.n_p
                else:
                    routed = routed / total
                new_messages[b, k] = routed

        damped = DAMPING * self.messages + (1 - DAMPING) * new_messages
        sums = damped.sum(axis=2, keepdims=True)
        sums[sums <= 0] = 1.0
        damped = damped / sums

        max_change = np.max(np.abs(damped - self.messages)) if n > 0 else 0.0
        self.messages = damped
        return max_change

    # ------------------------------------------------------------------
    def update_field(self):
        """
        Soft uniqueness field: u[t] = sum over unfixed slots s of belief
        that s uses tile t (marginalising rotation). field[t] update in
        LOG space then damped, to gently suppress tiles many slots want
        simultaneously. Already-used tiles get field forced to 0 (handled
        separately/hard in apply_tile_used_everywhere / restrict domains,
        this soft field only concerns UNUSED tiles that are merely
        "oversubscribed" in current beliefs).
        """
        n = self.n
        usage = np.zeros(n, dtype=np.float64)
        for s in range(n):
            if self.fixed[s] is not None:
                continue
            w, arr = self.local_belief(s)
            tot = w.sum()
            if tot <= 0 or not np.isfinite(tot):
                continue
            w = w / tot
            np.add.at(usage, arr[:, 0], w)

        excess = np.maximum(0.0, usage - 1.0)
        new_log_field = -LAMBDA_FIELD * excess
        # combine with current field (already incorporates tile_used hard zeros
        # via domain pruning, not via field) -- damp in log space
        cur_log_field = np.log(np.clip(self.field, 1e-300, None))
        damped_log = FIELD_DAMP * cur_log_field + (1 - FIELD_DAMP) * new_log_field
        damped_log -= damped_log.max()  # keep numerically centered
        self.field = np.exp(damped_log)

    # ------------------------------------------------------------------
    def run_bp(self, max_iters=MAX_BP_ITERS, tol=CONV_TOL, field_every=5):
        for it in range(max_iters):
            max_change = self.bp_sweep()
            if (it + 1) % field_every == 0:
                self.update_field()
            if max_change < tol:
                return it + 1, max_change
        return max_iters, max_change

    # ------------------------------------------------------------------
    def entropy_and_argmax(self, s):
        """Returns (entropy, best_t, best_r, best_weight, total_weight) for
        an UNFIXED slot s. entropy = +inf sentinel if domain is empty
        (contradiction) or the belief sums to 0."""
        w, arr = self.local_belief(s)
        if arr.shape[0] == 0:
            return float("inf"), None, None, 0.0, 0.0
        tot = w.sum()
        if tot <= 0 or not np.isfinite(tot):
            return float("inf"), None, None, 0.0, 0.0
        p = w / tot
        nz = p[p > 1e-300]
        ent = -np.sum(nz * np.log(nz))
        best_i = np.argmax(w)
        best_t, best_r = int(arr[best_i, 0]), int(arr[best_i, 1])
        return ent, best_t, best_r, float(w[best_i]), float(tot)

    # ------------------------------------------------------------------
    def is_domain_empty_somewhere(self):
        for s in range(self.n):
            if self.fixed[s] is None and self.domain[s].shape[0] == 0:
                return True
        return False

    # ------------------------------------------------------------------
    def check_consistent_with_fixed(self, s, t, r):
        """Hard check: does (t,r) at slot s match every already-fixed
        neighbour? (Domains should already enforce this via local_belief's
        hard-mask, but decimation double-checks before committing.)"""
        for j in range(3):
            b, k = self.adj[s][j]
            fb = self.fixed[b]
            if fb is None:
                continue
            bt, br = fb
            shown_here = self.pat_at[t, r, j]
            shown_there = self.pat_at[bt, br, k]
            if self.revid[shown_there] != shown_here:
                return False
        return True

    # ------------------------------------------------------------------
    def fix_slot(self, s, t, r):
        assert self.fixed[s] is None
        self.fixed[s] = (t, r)
        self.tile_used[t] = True
        self.domain[s] = np.array([[t, r]], dtype=np.int64)
        self._refresh_dom_pat(s)
        self.apply_tile_used_everywhere(t)

    # ------------------------------------------------------------------
    def unfix_slot(self, s):
        t, r = self.fixed[s]
        self.fixed[s] = None
        self.tile_used[t] = False
        # domain[s] needs to be rebuilt: all (t',r') not used by OTHER
        # fixed slots and (if seed-restricted) respecting the seed rule.
        n = self.n
        if self.restrict_seed and s not in self.seed_slots:
            pairs = [(tt, rr) for tt in range(n) for rr in range(3)
                     if tt != self.seed_tile and not self.tile_used[tt]]
        else:
            pairs = [(tt, rr) for tt in range(n) for rr in range(3)
                     if not self.tile_used[tt]]
        self.domain[s] = np.array(pairs, dtype=np.int64) if pairs else np.zeros((0, 2), dtype=np.int64)
        self._refresh_dom_pat(s)

    # ------------------------------------------------------------------
    def inject_noise(self, scale=NOISE_SCALE, rng=None):
        rng = rng or self.rng
        noise = 1.0 + scale * (rng.random(self.messages.shape) - 0.5) * 2
        self.messages = self.messages * noise
        sums = self.messages.sum(axis=2, keepdims=True)
        sums[sums <= 0] = 1.0
        self.messages = self.messages / sums


# ======================================================================
# Verification (independent of BP internals -- re-derives everything from
# tiles/adj directly, mirrors verify_solution.py's logic)
# ======================================================================
def verify_full_assignment(n, adj, tiles, assignment):
    """assignment: dict s -> (t, r) covering ALL slots. Returns (ok, reason)."""
    if len(assignment) != n:
        return False, f"only {len(assignment)} of {n} slots assigned"
    used = {}
    for s, (t, r) in assignment.items():
        if t in used:
            return False, f"tile {t} used by both slot {used[t]} and {s}"
        used[t] = s
    checked = set()
    rev = lambda p: p[::-1]
    for s in range(n):
        t, r = assignment[s]
        for j in range(3):
            b, k = adj[s][j]
            key = (min(s, b), max(s, b), min(j, k) if s == b else None)
            key = (s, j) if (s, j) < (b, k) else (b, k)
            if key in checked:
                continue
            checked.add(key)
            tb, rb = assignment[b]
            pat_s = tiles[t][(j + r) % 3]
            pat_b = tiles[tb][(k + rb) % 3]
            if pat_s != rev(pat_b):
                return False, f"edge mismatch slot {s} edge {j} vs slot {b} edge {k}"
    return True, "ok"


def verify_partial_assignment(n, adj, tiles, assignment):
    """assignment: dict s -> (t, r), possibly partial. Checks tile-uniqueness
    among assigned slots and that every board edge where BOTH endpoints are
    assigned actually matches. Returns (ok, reason)."""
    used = {}
    for s, (t, r) in assignment.items():
        if t in used:
            return False, f"tile {t} used by both slot {used[t]} and {s}"
        used[t] = s
    checked = set()
    rev = lambda p: p[::-1]
    for s in assignment:
        t, r = assignment[s]
        for j in range(3):
            b, k = adj[s][j]
            if b not in assignment:
                continue
            key = (s, j) if (s, j) < (b, k) else (b, k)
            if key in checked:
                continue
            checked.add(key)
            tb, rb = assignment[b]
            pat_s = tiles[t][(j + r) % 3]
            pat_b = tiles[tb][(k + rb) % 3]
            if pat_s != rev(pat_b):
                return False, f"edge mismatch slot {s} edge {j} vs slot {b} edge {k}"
    return True, "ok"


# ======================================================================
# Decimation driver
# ======================================================================
def save_partial(path, n, fixed):
    parts = [f"{s}:{fixed[s][0]}:{fixed[s][1]}" for s in range(n) if fixed[s] is not None]
    with open(path, "w") as f:
        f.write(" ".join(parts) + "\n")


def save_full(path, n, fixed):
    parts = [f"{s}:{fixed[s][0]}:{fixed[s][1]}" for s in range(n)]
    with open(path, "w") as f:
        f.write(" ".join(parts) + "\n")


def decimate(n, adj, tiles, seed_slots, seed_tile, seconds, seed):
    """
    Main BP + decimation loop with contradiction backtracking and restarts.
    Returns (best_fixed_dict, best_depth, found_full: bool).
    """
    t_start = time.time()
    rng_np = np.random.default_rng(seed)

    best_depth = -1
    best_assignment = {}

    restarts = 0
    contradictions = 0
    consec_contradictions = 0

    attempt = 0
    while time.time() - t_start < seconds:
        attempt += 1
        state = BPState(n, adj, tiles, seed_slots, seed_tile, rng_np)
        # history of fixation order for backtracking: list of slot ids
        history = []
        taboo = set()  # (slot, tile) pairs forbidden this attempt after a local backtrack

        local_contradictions = 0
        consec_contradictions = 0

        while len(history) < n and time.time() - t_start < seconds:
            n_iters, max_change = state.run_bp()

            if state.is_domain_empty_somewhere():
                contradiction = True
            else:
                # pick lowest-entropy unfixed slot
                best_s = None
                best_ent = None
                best_t = best_r = None
                for s in range(n):
                    if state.fixed[s] is not None:
                        continue
                    ent, t, r, w, tot = state.entropy_and_argmax(s)
                    if ent == float("inf"):
                        best_s, best_ent, best_t, best_r = s, ent, None, None
                        break
                    if best_ent is None or ent < best_ent:
                        best_ent, best_s, best_t, best_r = ent, s, t, r

                if best_ent == float("inf") or best_t is None:
                    contradiction = True
                elif (best_s, best_t) in taboo:
                    # try next-best via a quick re-scan excluding taboo tile
                    arr = state.domain[best_s]
                    w, _ = state.local_belief(best_s)
                    order = np.argsort(-w)
                    picked = None
                    for idx in order:
                        cand_t, cand_r = int(arr[idx, 0]), int(arr[idx, 1])
                        if (best_s, cand_t) not in taboo:
                            picked = (cand_t, cand_r)
                            break
                    if picked is None:
                        contradiction = True
                    else:
                        best_t, best_r = picked
                        contradiction = not state.check_consistent_with_fixed(best_s, best_t, best_r)
                        if not contradiction:
                            state.fix_slot(best_s, best_t, best_r)
                            history.append(best_s)
                else:
                    if not state.check_consistent_with_fixed(best_s, best_t, best_r):
                        contradiction = True
                    else:
                        state.fix_slot(best_s, best_t, best_r)
                        history.append(best_s)
                        contradiction = False

            if not contradiction:
                consec_contradictions = 0
                depth = len(history)
                if depth > best_depth:
                    # verify before trusting (cheap: only checks fixed subset)
                    cur_assignment = {s: state.fixed[s] for s in range(n) if state.fixed[s] is not None}
                    ok, reason = verify_partial_assignment(n, adj, tiles, cur_assignment)
                    if ok:
                        best_depth = depth
                        best_assignment = dict(cur_assignment)
                        save_partial("bp_partial_best.txt", n, state.fixed)
                    else:
                        # Should not happen given hard checks, but guard anyway.
                        print(f"WARNING: depth {depth} failed independent verify: {reason}", flush=True)

                elapsed = time.time() - t_start
                print(f"fixed={depth}/{n} contradictions={contradictions} "
                      f"restarts={restarts} bp_iters={n_iters} t={elapsed:.1f}s "
                      f"best={best_depth}/{n}", flush=True)

                if depth == n:
                    full_assignment = {s: state.fixed[s] for s in range(n)}
                    ok, reason = verify_full_assignment(n, adj, tiles, full_assignment)
                    if ok:
                        return full_assignment, n, True
                    else:
                        print(f"WARNING: full assignment failed verify ({reason}); "
                              f"treating as contradiction and continuing", flush=True)
                        contradiction = True

            if contradiction:
                contradictions += 1
                local_contradictions += 1
                consec_contradictions += 1

                # taboo the offending (slot,tile) if we have one
                if history:
                    s_back = None
                    t_back = None
                    k = min(BACKTRACK_K, len(history))
                    for _ in range(k):
                        s_back = history.pop()
                        t_back, r_back = state.fixed[s_back]
                        state.unfix_slot(s_back)
                    # taboo the specific fixation that led to the wipeout at the
                    # (new) frontier depth to avoid repeating the same mistake
                    if s_back is not None:
                        taboo.add((s_back, t_back))
                        if len(taboo) > TABOO_SIZE:
                            taboo.clear()
                else:
                    # nothing to backtrack (contradiction at depth 0) -> restart
                    consec_contradictions = MAX_CONSEC_CONTRADICTIONS

                state.inject_noise(rng=rng_np)

                if consec_contradictions >= MAX_CONSEC_CONTRADICTIONS:
                    restarts += 1
                    break  # break inner while -> new BPState with new seed draw

        # loop continues to next attempt (new BPState) until time budget ends
        # or a full solution is returned above.

    return best_assignment, best_depth, False


# ======================================================================
# CLI
# ======================================================================
def main():
    if len(sys.argv) < 2:
        print("Usage: python bp_solver.py <instance.txt> <seconds> <seed>", file=sys.stderr)
        sys.exit(1)
    inst_path = sys.argv[1]
    seconds = float(sys.argv[2]) if len(sys.argv) > 2 else 60.0
    seed = int(sys.argv[3]) if len(sys.argv) > 3 else 0

    n, adj, tiles, seed_slots, seed_tile = load_instance(inst_path)
    print(f"Loaded {inst_path}: n={n} slots, seed_slots={len(seed_slots)}, "
          f"seed_tile={seed_tile}", flush=True)

    assignment, depth, found_full = decimate(n, adj, tiles, seed_slots, seed_tile, seconds, seed)

    if found_full:
        ok, reason = verify_full_assignment(n, adj, tiles, assignment)
        print(f"FULL SOLUTION {'PASS' if ok else 'FAIL: ' + reason} "
              f"({depth}/{n} slots)", flush=True)
        if ok:
            save_full("bp_solution.txt", n, {s: assignment[s] for s in range(n)})
            print("Wrote bp_solution.txt", flush=True)
        print("RESULT: SUCCESS - full 160/160 valid matching found" if n == 160 and ok
              else ("RESULT: SUCCESS - full matching found" if ok else "RESULT: FAILURE (verify mismatch)"),
              flush=True)
    else:
        ok, reason = verify_partial_assignment(n, adj, tiles, assignment)
        print(f"BEST PARTIAL: depth={depth}/{n} verify={'PASS' if ok else 'FAIL: ' + reason}", flush=True)
        print(f"RESULT: {'DEEP PARTIAL' if depth >= int(0.875 * n) else 'SHALLOW PARTIAL'} "
              f"({depth}/{n}) -- no full matching found within {seconds}s budget", flush=True)


if __name__ == "__main__":
    main()
