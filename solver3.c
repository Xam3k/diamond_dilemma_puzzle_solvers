/*
 * solver3.c -- Diamond Dilemma Gold: exhaustive DFS solver + SINGLE-LOOP PRUNING.
 *
 * Compile: zig cc -O3 -o solver3.exe solver3.c
 * (C11, single file, no external dependencies beyond libc)
 *
 * Usage:
 *   solver3.exe <instance_file> <node_limit> <seed>
 *   node_limit = 0 means unlimited
 *   seed = 1..N  permutes candidate order so parallel runs explore different subtrees
 *
 * This file is solver2.c (static fill order, pair-indexed candidate tables,
 * supply/demand prune) PLUS single-loop pruning on top. All of solver2's
 * existing logic is unchanged; the additions are:
 *
 *   1. GOLD ARC DATA: 365 human-verified within-tile "gold connections" are
 *      loaded from arcs_flat.txt (preferred, simple line format) or arcs.json
 *      (bespoke hand-rolled parser, no library) if the flat file is absent.
 *
 *   2. ENDPOINT NODE SCHEME: every (board edge, position 0..10) pair is a node.
 *      For board edge E joining (slotA,edgeA)-(slotB,edgeB), the side with the
 *      SMALLER slot index is canonical "side A"; a node is addressed in side-A
 *      coordinates: q=p on side A, q=10-p on side B. Because both slots that
 *      share a board edge map to the SAME node id at a shared position, the
 *      "across-edge fusion" of two neighbouring tiles' endpoints is automatic
 *      -- no union is needed for it. The only unions performed are the
 *      within-tile gold arcs of the tile being placed.
 *
 *   3. UNION-FIND WITH UNDO TRAIL: union by rank, no path compression, every
 *      parent/rank write recorded on a trail so a placement's unions can be
 *      rolled back exactly on backtrack (mirrors the DFS's own backtracking).
 *
 *   4. LOOP-CLOSURE RULE: a union whose two endpoints already share a root
 *      would close a cycle. Before the final (160th) placement this is
 *      forbidden -- the candidate is rejected and any partial unions already
 *      applied for that tile are rolled back. At the final placement,
 *      closures are allowed (and expected); the board is only accepted as a
 *      solution if the total count of such closures across the whole
 *      placement is exactly 1 -- i.e. the gold arcs form ONE single cycle.
 *
 * CONVENTIONS carried over unmodified from solver2.c / solver.c:
 *   Placement: tile t rotation r in slot s maps tile-edge (j+r)%3 -> slot-edge j.
 *   Match: pattern on slot-edge j == rev_pat[pattern on facing neighbour's edge].
 *   Instance format identical to solver.c (parse_instance duplicated here).
 *
 * Gold-arc rotation convention (per arcs.json / arcs_flat.txt spec):
 *   A verified arc on tile t connects tile-edge e1 position p1 to tile-edge
 *   e2 position p2 (both measured along the tile's own clockwise traversal,
 *   which coincides with the slot edge's clockwise traversal, so positions
 *   are NOT altered by rotation -- only the slot-edge index is). When tile t
 *   is placed with rotation r, tile-edge e lands on slot-edge j=(e-r+3)%3.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <inttypes.h>
#include <time.h>
#include <math.h>
#include <stddef.h>

/* ============================================================
 * Constants
 * ============================================================ */
#define N_SLOTS        160
#define N_EDGES        240
#define PAT_LEN        11
#define MAX_PATTERNS   2048   /* 2^11 */
#define MAX_DENSE      128    /* static assert below guarantees actual <= 128 */
#define MAX_TILE_CANDS 160    /* max (tile,rot) per single-pattern list */
#define MAX_PAIR_CANDS 160    /* max (tile,rot) per pair list entry */
#define MAX_CANDS      512    /* scratch candidate array */

/* Packed candidate: tile in bits [7:2], rot in bits [1:0] */
typedef uint8_t TRPacked;  /* tile<<2|rot; tile<=159 fits in 8 bits as tile<<2|rot <= 159*4+2 = 638 > 255 */
/* Actually tile can be 0..159, rot 0..2; tile<<2|rot max = 159*4+2 = 638 which doesn't fit uint8_t.
 * Use uint16_t instead. */
typedef uint16_t TRPack;
#define TR_PACK(t,r)   ((TRPack)(((uint16_t)(t) << 2) | (uint8_t)(r)))
#define TR_TILE(p)     ((int)((p) >> 2))
#define TR_ROT(p)      ((int)((p) & 3))

/* ---- Loop-pruning constants ---- */
#define MAX_ARCS_PER_TILE 8    /* actual observed max is 3; generous headroom */
#define UF_N (N_EDGES * PAT_LEN)   /* 240*11 = 2640 endpoint nodes */

/* ============================================================
 * Board data (read-only after init)
 * ============================================================ */

typedef struct { uint8_t slot; uint8_t edge; } Neighbor;
static Neighbor g_adj[N_SLOTS][3];
static uint16_t tile_pat[N_SLOTS][3];   /* raw 11-bit patterns */
static uint16_t rev_pat[MAX_PATTERNS];

/* ---- Pattern compression ---- */
static int      n_dense = 0;              /* number of distinct patterns found */
static uint16_t dense_to_raw[MAX_DENSE]; /* dense_id -> raw pattern */
static int      raw_to_dense[MAX_PATTERNS]; /* raw -> dense id (-1 if absent) */
/* dense reverse: rev_dense[d] = dense id of rev_pat[dense_to_raw[d]] */
static uint8_t  rev_dense[MAX_DENSE];

/* Tile patterns in dense IDs */
static uint8_t  tile_dpat[N_SLOTS][3];   /* dense pattern per tile edge */

/* ---- Single-pattern candidate lists (dense-indexed) ---- */
static TRPack   sp_list[MAX_DENSE][MAX_TILE_CANDS];
static int      sp_count[MAX_DENSE];       /* number of (tile,rot) pairs for pattern d */

/* Per (dense_pat, slot_edge_index) single-pattern list:
 * spd_list[d][j][i] = TR_PACK(t,r) where tile_dpat[t][(j+r)%3] == d */
static TRPack   spd_list[MAX_DENSE][3][MAX_TILE_CANDS];
static int      spd_count[MAX_DENSE][3];

/* ---- Pair-candidate lists ---- */
#define PAIR_TABLE_DIM  (MAX_DENSE * MAX_DENSE)
typedef struct {
    TRPack *data;   /* pointer into big pool */
    uint8_t count;
} PairEntry;

static TRPack   pair_pool[N_SLOTS * PAIR_TABLE_DIM * MAX_PAIR_CANDS]; /* upper bound; will be much smaller */
static PairEntry pair_table[N_SLOTS][PAIR_TABLE_DIM]; /* pair_table[ord][dA*n_dense+dB] */
static TRPack   *pair_pool_ptr;   /* bump allocator */

/* ---- Seed configuration ---- */
#define MAX_SEED_SLOTS N_SLOTS
static int seed_slots[MAX_SEED_SLOTS];
static int n_seed_slots = 0;
static int seed_tile_id = 23;

/* ============================================================
 * Loop-pruning data (NEW in solver3)
 * ============================================================ */

/* Verified gold arcs per tile, in TILE edge coordinates (not yet rotated). */
static uint8_t tile_arc_count[N_SLOTS];
static uint8_t tile_arc_e1[N_SLOTS][MAX_ARCS_PER_TILE];
static uint8_t tile_arc_p1[N_SLOTS][MAX_ARCS_PER_TILE];
static uint8_t tile_arc_e2[N_SLOTS][MAX_ARCS_PER_TILE];
static uint8_t tile_arc_p2[N_SLOTS][MAX_ARCS_PER_TILE];

/* Board-edge canonicalisation: edge_id[s][j] = unique id 0..N_EDGES-1 for the
 * physical board edge touched by (slot s, slot-edge j). is_sideA[s][j] = 1 if
 * (s,j) is the canonical "side A" of that edge (the side with smaller slot
 * index), else 0. */
static int     edge_id[N_SLOTS][3];
static uint8_t is_sideA[N_SLOTS][3];

/* Union-find over UF_N = 2640 endpoint nodes. Union by rank, NO path
 * compression (required so undo is a simple trail replay). */
static int uf_parent[UF_N];
static int uf_rank[UF_N];

typedef struct { int idx; int old_val; uint8_t is_rank; } UFUndo;
#define UF_TRAIL_CAP 8192
static UFUndo uf_trail[UF_TRAIL_CAP];
static int    uf_trail_top = 0;

/* closed_cycles = cumulative count of unions performed so far (in the current
 * seed/rotation attempt) whose two endpoints already shared a root. Forbidden
 * to be nonzero before the final placement; must equal exactly 1 once all
 * 160 slots are filled for the board to be accepted as a single gold loop. */
static int closed_cycles = 0;

/* Per fill-order-depth bookkeeping so a placement's unions/cycle-count can be
 * undone precisely when that slot is unplaced (DFS backtracks one depth at a
 * time, single active path, so indexing by depth is safe). */
static int uf_mark_stack[N_SLOTS];
static int uf_cyc_stack[N_SLOTS];

static uint64_t stat_cycles_pruned = 0;

/* ============================================================
 * Fill order (precomputed at startup)
 * ============================================================ */
typedef struct {
    uint8_t  slot;           /* which slot */
    uint8_t  n_constrained;  /* how many of its 3 neighbours come EARLIER in fill order */
    uint8_t  con_j[3];       /* slot-edge index for each earlier constraint (0..2) */
    uint8_t  con_nb[3];      /* earlier neighbour slot */
    uint8_t  con_kb[3];      /* earlier neighbour's edge index */
    uint8_t  pair_jA;        /* slot-edge index A (used when n_constrained >= 2) */
    uint8_t  pair_jB;        /* slot-edge index B */
} FillPos;

static FillPos fill_order[N_SLOTS];
static int     fill_pos[N_SLOTS];  /* fill_pos[slot] = position in fill_order (-1 if not yet assigned) */

/* ============================================================
 * Search state (mutable during DFS)
 * ============================================================ */
static int8_t  slot_tile[N_SLOTS];      /* -1 = empty */
static int8_t  slot_rot[N_SLOTS];       /* -1 = empty */
static uint8_t tile_used[N_SLOTS];

/* Supply/demand */
static int16_t supply[MAX_DENSE];  /* supply[d] = #edges with dense pattern d on unused tiles */
static int16_t demand[MAX_DENSE];  /* demand[d] = #frontier constraint edges requiring dense pattern d */

/* Touched pattern list for incremental supply/demand check */
static uint8_t touched[MAX_DENSE];
static uint8_t touched_flag[MAX_DENSE]; /* to avoid duplicates */
static int     n_touched;

/* ============================================================
 * Statistics
 * ============================================================ */
static uint64_t stat_nodes     = 0;
static uint64_t stat_solutions = 0;
static int      stat_max_depth = 0;
static int      stat_best_partial = 0;
static time_t   t_start, t_last_stats;
static uint64_t node_limit = 0;
static int      limit_hit  = 0;

/* ============================================================
 * Stuck-subtree dump instrumentation (NEW in solver3)
 *
 * Purpose: identify DFS frames whose subtree is unusually expensive
 * (candidate for offloading to a CP-SAT "is this residual board still
 * completable?" oracle). Entirely env-gated: OFF unless STUCK_DUMP names
 * an output file, in which case it costs one extra static-array write per
 * dfs() entry/return at depths 40..120 and a rate-limited file write. When
 * OFF (the default), every guard collapses to a single `if (g_stuck_dump_on)`
 * check that is false, i.e. one cheap comparison, no array writes, no I/O.
 *
 * dfs(depth) is entered with the board holding placements for
 * fill_order[0..depth-1] (ancestors); a call to dfs(depth) only ever
 * places/unplaces fill_order[depth] itself (and recurses for deeper
 * slots, which are always unplaced again before dfs(depth) returns). So
 * at the point dfs(depth) is about to return, slot_tile/slot_rot still
 * hold exactly the ancestor placements 0..depth-1 -- precisely the board
 * "as it was" when this frame started -- even though depth's own slot has
 * already been placed-then-unplaced by this frame's own candidate loop.
 * That is what dump_stuck_subtree() below reconstructs and writes.
 * ============================================================ */
static int      g_stuck_dump_on   = 0;
static FILE    *g_stuck_dump_f    = NULL;
static uint64_t g_stuck_min       = 30000000ULL;   /* STUCK_MIN env, default */
static uint64_t entry_nodes[N_SLOTS + 1];          /* stat_nodes snapshot on entry, by depth */
static uint64_t stat_dumps        = 0;
static time_t   g_last_dump_time  = 0;
#define STUCK_DUMP_MAX            200
#define STUCK_DUMP_RATE_SECONDS   5.0
#define STUCK_DEPTH_LO            40
#define STUCK_DEPTH_HI            120

static void dump_stuck_subtree(int depth, uint64_t subtree_nodes) {
    fprintf(g_stuck_dump_f, "d %d n %" PRIu64 " B", depth, subtree_nodes);
    for (int i = 0; i < depth; i++) {
        int s = fill_order[i].slot;
        fprintf(g_stuck_dump_f, " %d:%d:%d", s, (int)(uint8_t)slot_tile[s], (int)(uint8_t)slot_rot[s]);
    }
    fputc('\n', g_stuck_dump_f);
    fflush(g_stuck_dump_f);
}

/* Called just before dfs(depth) returns (after its candidate loop has
 * finished, all of ITS OWN candidates placed and unplaced again). Checks
 * the node-count delta against STUCK_MIN and the two rate limits, and
 * writes one dump line if all pass. */
static inline void maybe_dump_stuck(int depth) {
    if (!g_stuck_dump_on) return;                              /* the one cheap comparison when OFF */
    if (depth < STUCK_DEPTH_LO || depth > STUCK_DEPTH_HI) return;
    if (stat_dumps >= STUCK_DUMP_MAX) return;

    uint64_t subtree = stat_nodes - entry_nodes[depth];
    if (subtree <= g_stuck_min) return;

    time_t now = time(NULL);
    if (difftime(now, g_last_dump_time) < STUCK_DUMP_RATE_SECONDS) return;

    dump_stuck_subtree(depth, subtree);
    g_last_dump_time = now;
    stat_dumps++;
}

/* ============================================================
 * TIME_LIMIT instrumentation (NEW in solver3)
 *
 * Optional wall-clock budget, checked only from the already-existing
 * periodic stats path (print_stats(), called from dfs() every 2^26 nodes
 * or every 10s of wall time -- see below). When TIME_LIMIT is unset,
 * g_time_limit stays 0.0 and the single `> 0.0` comparison is the only
 * added cost. On expiry this sets limit_hit exactly like node_limit does,
 * so the DFS unwinds through its normal `if (limit_hit) return;` guards.
 * ============================================================ */
static double g_time_limit = 0.0;   /* seconds; 0 = unlimited (TIME_LIMIT env) */
/* Per-prefix node cap (PREFIX_NODE_CAP): in PREFIX_FILE mode, a single prefix
 * whose subtree exceeds this many nodes is ABANDONED (deferred to DEFER_FILE
 * for later deeper decomposition) instead of stalling the whole batch. */
static uint64_t g_prefix_node_cap = 0;
static uint64_t g_prefix_pstart = 0;
static int      g_prefix_capped = 0;
static FILE    *g_defer_f = NULL;
static long     g_defer_count = 0;

/* ============================================================
 * ROOT_UNIT partitioning (NEW in solver3)
 *
 * Purpose: let an external driver (ledger_run.py) split the exhaustive
 * search into independent top-level "units" -- one unit == one (seed slot,
 * rotation) pair, i.e. exactly one iteration of the existing seed x
 * rotation outer loop in main(). Units are numbered
 * u = seed_index*3 + rotation, seed_index into the (sorted) seed_slots[]
 * array as actually iterated by the outer loop, for
 * u in [0, n_seed_slots*3). When ROOT_UNIT is unset this is entirely
 * inert: g_root_unit stays -1 and the `si != unit_si` / `r != unit_r`
 * guards added to the outer loop are two extra integer comparisons per
 * iteration of a loop that already only runs n_seed_slots*3 times total,
 * i.e. immeasurable overhead.
 * ============================================================ */
static int g_root_unit = -1;   /* -1 = disabled (ROOT_UNIT env unset) */
static int g_depth_cap = 0;    /* DEPTH_CAP=C truncates the tree below depth C
                                * (validation aid for the ESTIMATE mode). */
static FILE *g_frontier_f = NULL;      /* FRONTIER_FILE: dump every node AT
                                        * depth DEPTH_CAP (req line format)
                                        * instead of descending further. */
static uint64_t g_frontier_count = 0;
/* PREFIX_FILE batch slicing: process only prefixes [start, start+count). */
static long g_prefix_start = 0;
static long g_prefix_count = -1;   /* -1 = to end of file */

/* ============================================================
 * EQUIV_STATS: equivalence-signature revisit measurement (NEW in solver3)
 *
 * Purpose: measurement only, no pruning. Estimates how often the DFS
 * re-encounters EQUIVALENT residual subproblems at depths [60,110], to
 * decide whether a transposition/memo table would pay for its complexity.
 *
 * Two 64-bit FNV-1a signatures are computed at a sampled subset of dfs()
 * entries in the depth window:
 *
 *   match_sig: hashes (a) the full tile_used[] bitmap (which physical
 *     tiles are already committed -- since the fill order is STATIC, the
 *     placed SLOT SET at a given depth is always identical, so it need
 *     not be hashed, only which tiles occupy it), plus (b) for every
 *     future fill-order position in [depth, depth+40], the dense boundary
 *     pattern required of it by each of ITS constraining neighbours that
 *     is already placed at the current depth (a neighbour can be earlier
 *     in the *static* fill order than that future position while still
 *     being unplaced *right now*, so this is filtered by fill_pos[nb] <
 *     depth, not just "earlier in fill_order"). Two DFS states with equal
 *     match_sig look identical from the point of view of "which
 *     (tile-availability, near-frontier boundary requirement) subproblem
 *     remains", modulo hash collisions.
 *
 *   loop_sig: match_sig, further hashed with the union-find ROOT of every
 *     boundary endpoint node (a node on any board edge between an already-
 *     placed slot and a not-yet-placed neighbour, at all PAT_LEN positions
 *     of that edge -- the endpoint-node scheme already treats each
 *     (edge,position) as a node, see the file header). Roots are
 *     canonicalised by first-occurrence renumbering (0,1,2,...) in
 *     iteration order before hashing, so two physically-identical
 *     pairings-of-open-strands hash equal even if their raw uf_parent
 *     values differ.
 *
 * Both signatures are looked up/inserted into a 2^22-entry open-addressing
 * table of raw 8-byte hashes (linear probe, max 8 steps then counted as
 * "full" and skipped -- no eviction, no resizing). probes/hits/inserts/
 * full are tallied per table and reported at exit.
 *
 * Cost control: gated OFF unless EQUIV_STATS=1 (one cheap comparison when
 * off, same as STUCK_DUMP/ROOT_UNIT above); when on, further limited to
 * depths [40,129] AND to every EQUIV_SAMPLE_STRIDE'th dfs() entry in that
 * window (a free-running counter, not per-depth, so the sampling rate is
 * uniform across the window) to bound the O(depth-window x boundary-size)
 * work to a small fraction of total nodes.
 *
 * PER-BUCKET REPORTING: in addition to the aggregate probes/hits, both
 * signatures' probe outcomes are also tallied into 9 depth buckets of
 * width 10 (40-49, 50-59, ..., 120-129) so revisit rate can be read as a
 * function of depth (a memo table is only worth it in the depth range
 * where the hit rate is actually high). The lookup tables themselves stay
 * shared/global across the whole window -- only the counters are bucketed
 * by the depth at the time of the probe.
 * ============================================================ */
#define EQUIV_DEPTH_LO       40
#define EQUIV_DEPTH_HI       129
#define EQUIV_BUCKET_WIDTH   10
#define EQUIV_N_BUCKETS      9      /* (EQUIV_DEPTH_HI + 1 - EQUIV_DEPTH_LO) / EQUIV_BUCKET_WIDTH */
#define EQUIV_SAMPLE_STRIDE  1      /* measure 1 in this many dfs() entries in the window */
#define EQUIV_LOOKAHEAD      40      /* future fill-order positions scanned for match_sig */
#define EQUIV_TABLE_BITS     22
#define EQUIV_TABLE_SIZE     (1u << EQUIV_TABLE_BITS)
#define EQUIV_TABLE_MASK     (EQUIV_TABLE_SIZE - 1)
#define EQUIV_PROBE_MAX      8
#define FNV_OFFSET_BASIS     0xcbf29ce484222325ULL
#define FNV_PRIME            0x100000001b3ULL

static int      g_equiv_stats_on = 0;
static uint64_t g_equiv_calls    = 0;   /* free-running counter, window entries only */

static uint64_t match_table[EQUIV_TABLE_SIZE];
static uint64_t loop_table[EQUIV_TABLE_SIZE];

static uint64_t stat_equiv_match_probes  = 0, stat_equiv_match_hits    = 0;
static uint64_t stat_equiv_match_inserts = 0, stat_equiv_match_full   = 0;
static uint64_t stat_equiv_loop_probes   = 0, stat_equiv_loop_hits    = 0;
static uint64_t stat_equiv_loop_inserts  = 0, stat_equiv_loop_full    = 0;

/* Per-depth-bucket probes/hits, indexed by (depth - EQUIV_DEPTH_LO) / EQUIV_BUCKET_WIDTH. */
static uint64_t stat_equiv_match_bucket_probes[EQUIV_N_BUCKETS];
static uint64_t stat_equiv_match_bucket_hits[EQUIV_N_BUCKETS];
static uint64_t stat_equiv_loop_bucket_probes[EQUIV_N_BUCKETS];
static uint64_t stat_equiv_loop_bucket_hits[EQUIV_N_BUCKETS];

/* Scratch for canonicalising union-find roots into first-occurrence ids,
 * without paying a memset(UF_N) on every sampled call: each root's slot is
 * only considered valid for the current call if its stamp matches the
 * current epoch (bumped once per call). */
static int32_t canon_stamp[UF_N];
static int32_t canon_id[UF_N];
static int32_t canon_epoch = 0;

static inline uint64_t fnv1a_bytes(uint64_t h, const void *data, size_t len) {
    const uint8_t *p = (const uint8_t *)data;
    for (size_t i = 0; i < len; i++) {
        h ^= p[i];
        h *= FNV_PRIME;
    }
    return h;
}

/* Result of an open-addressing probe: which bucket to credit the outcome
 * to (INSERT is tallied like a "miss" for rate purposes -- only HIT means
 * "this exact signature was already in the table"). */
typedef enum { EQUIV_PROBE_INSERT = 0, EQUIV_PROBE_HIT = 1, EQUIV_PROBE_FULL = 2 } EquivProbeOutcome;

/* Open-addressing probe/insert with linear probing, capped at
 * EQUIV_PROBE_MAX steps. sig==0 is reserved as the "empty slot" sentinel
 * (an FNV-1a hash landing on exactly 0 is astronomically unlikely; if it
 * ever happens we just remap it to 1, a negligible approximation).
 * *out_steps receives how many probe slots were examined (>=1), so the
 * caller can tally aggregate AND per-bucket probe counts from one call. */
static inline EquivProbeOutcome equiv_probe(uint64_t *table, uint64_t sig, int *out_steps) {
    if (sig == 0) sig = 1;
    uint32_t idx = (uint32_t)(sig & EQUIV_TABLE_MASK);
    for (int step = 0; step < EQUIV_PROBE_MAX; step++) {
        uint32_t slot = (idx + (uint32_t)step) & EQUIV_TABLE_MASK;
        if (table[slot] == 0) { table[slot] = sig; *out_steps = step + 1; return EQUIV_PROBE_INSERT; }
        if (table[slot] == sig)                   { *out_steps = step + 1; return EQUIV_PROBE_HIT; }
    }
    *out_steps = EQUIV_PROBE_MAX;
    return EQUIV_PROBE_FULL;
}

/* ============================================================
 * ORACLE_DIR: persistent CP-SAT "stuck-subtree oracle" sidecar (NEW)
 *
 * Purpose: solver3.c occasionally gets stuck in an enormous subtree at some
 * mid-search depth (see STUCK_DUMP above). oracle_probe.py measured that
 * asking a CP-SAT solver "is this residual board (ancestors 0..depth-1 as
 * currently placed, ignoring the single-loop constraint) still completable
 * as a plain edge matching at all?" is INFEASIBLE 100% of the time for
 * subtrees >=30M nodes, in a median 0.088s -- a 60:1 node-equivalent
 * payoff (still 4:1 even at 2M-node triggers). This wires that up as a
 * live sidecar: a persistent oracle_sidecar.py process watches a directory
 * for request files this solver drops, and writes back a one-word verdict.
 *
 * Protocol (one sidecar serving exactly one solver process):
 *   ORACLE_DIR=<dir> enables the feature. This solver best-effort mkdir's
 *   the dir too, so a bare standalone run doesn't strictly need the
 *   orchestrator to have created it first.
 *   req_<seq>.txt written by the solver: same line format as STUCK_DUMP's
 *   dump line ("d <depth> n <nodes_so_far> B <slot:tile:rot> ..."), written
 *   atomically (req_<seq>.txt.tmp then rename()'d).
 *   ans_<seq>.txt written by the sidecar: one word INFEASIBLE/FEASIBLE/
 *   UNKNOWN. seq is a strictly increasing integer, one file pair per call.
 *
 * When/how a call is made: checked once per candidate tried, in each of the
 * three dfs() candidate loops (nc==0/1/>=2), right after that candidate's
 * unplace() -- i.e. with fill_order[depth]'s own slot EMPTY again, so the
 * ancestor board dumped is exactly depths [0,depth), identical convention
 * to dump_stuck_subtree(). A call fires only if ALL of: ORACLE_DIR is set;
 * depth is in [ORACLE_DEPTH_LO,ORACLE_DEPTH_HI]; this exact dfs(depth)
 * invocation ("frame") hasn't already asked (oracle_asked[depth], reset to
 * 0 on every dfs(depth) entry -- "at most 1 call per frame"); nodes
 * consumed since this frame's entry (entry_nodes[depth], the same
 * bookkeeping STUCK_DUMP already maintains) exceed ORACLE_MIN; the global
 * cooldown since the last call anywhere in the run is >= ORACLE_COOLDOWN_MS;
 * and the lifetime call budget ORACLE_MAX hasn't been exhausted.
 *
 * The call is SYNCHRONOUS: write the request, then spin-poll for the
 * answer file every 5ms (portable Sleep()/usleep(), see sleep_ms() below)
 * for up to ORACLE_WAIT ms. Since this is a single-threaded blocking wait,
 * "in flight" and "at most 1 per frame" are equivalent here -- no two
 * calls are ever concurrent -- but the per-frame flag and the global
 * g_prune_below mechanism below are written to be correct even if that
 * assumption is ever relaxed later (e.g. an async variant).
 *
 * Verdict handling:
 *   INFEASIBLE -> the residual board (ancestors 0..depth-1 EXACTLY as
 *     placed right now) has no completion at all, for ANY candidate at
 *     depth or deeper -- i.e. the ENTIRE dfs(depth) frame (not just the
 *     candidates already tried) is refuted. Set g_prune_below = depth; the
 *     candidate loop this was called from checks the flag immediately
 *     afterward and, since depth >= g_prune_below there, stops iterating
 *     further candidates and returns from THIS dfs(depth) call, clearing
 *     the flag first (this call site IS the frame it names). dfs() also
 *     checks the flag at its very entry (`depth > g_prune_below` => return
 *     immediately) so the unwind is correct even if this mechanism is ever
 *     triggered while descendants are notionally still "in flight".
 *   FEASIBLE / UNKNOWN / timeout (no answer file within ORACLE_WAIT ms) ->
 *     recorded in oracle_asked[depth] (no re-ask for this frame instance)
 *     and the search simply continues normally -- these are NOT proof of
 *     anything, just "don't know" (a FEASIBLE residual might still fail
 *     the single-loop constraint solver3.c itself must still verify).
 *
 * Cost when OFF (ORACLE_DIR unset): one cheap `if (!g_oracle_on) return;`
 * comparison per would-be call site, no array writes, no I/O -- same
 * pattern as STUCK_DUMP/ROOT_UNIT/EQUIV_STATS above.
 * ============================================================ */
#ifdef _WIN32
#include <windows.h>
#include <direct.h>
static void sleep_ms(unsigned ms) { Sleep(ms); }
static uint64_t monotonic_ms(void) { return (uint64_t)GetTickCount64(); }
static void oracle_mkdir(const char *path) { _mkdir(path); /* ignore EEXIST etc */ }
#else
#include <unistd.h>
#include <sys/time.h>
#include <sys/stat.h>
#include <sys/types.h>
static void sleep_ms(unsigned ms) { usleep((useconds_t)ms * 1000); }
static uint64_t monotonic_ms(void) {
    struct timeval tv; gettimeofday(&tv, NULL);
    return (uint64_t)tv.tv_sec * 1000ULL + (uint64_t)tv.tv_usec / 1000ULL;
}
static void oracle_mkdir(const char *path) { mkdir(path, 0755); /* ignore EEXIST etc */ }
#endif

#define ORACLE_DEPTH_LO 40
#define ORACLE_DEPTH_HI 120

static int      g_oracle_on           = 0;
static char     g_oracle_dir[480]     = {0};
static uint64_t g_oracle_min          = 4000000ULL;  /* ORACLE_MIN env */
static uint64_t g_oracle_wait_ms      = 12000ULL;    /* ORACLE_WAIT env (ms) */
static uint64_t g_oracle_cooldown_ms  = 1000ULL;     /* ORACLE_COOLDOWN_MS env */
static uint64_t g_oracle_max          = 100000ULL;   /* ORACLE_MAX env */
static uint64_t g_oracle_seq          = 0;
static uint64_t g_last_oracle_call_ms = 0;
static int      g_prune_below         = -1;          /* -1 = inactive */
static uint8_t  oracle_asked[N_SLOTS + 1];           /* per-depth, reset on dfs() entry */

static uint64_t stat_oracle_calls         = 0;
static uint64_t stat_oracle_infeasible    = 0;
static uint64_t stat_oracle_feasible      = 0;
static uint64_t stat_oracle_unknown       = 0;
static uint64_t stat_oracle_wait_ms_total = 0;

/* Write req_<seq>.txt (atomically via a .tmp + rename) using exactly the
 * STUCK_DUMP line convention, then spin-poll for ans_<seq>.txt. Returns a
 * pointer to a static verdict buffer: "INFEASIBLE"/"FEASIBLE"/some other
 * sidecar-written token, or "" on I/O failure / timeout with no answer. */
static const char *oracle_roundtrip(int depth, uint64_t subtree_nodes) {
    static char verdict[64];
    verdict[0] = '\0';

    char req_tmp[560], req_path[560], ans_path[560];
    uint64_t seq = g_oracle_seq++;
    snprintf(req_tmp,  sizeof req_tmp,  "%s/req_%" PRIu64 ".txt.tmp", g_oracle_dir, seq);
    snprintf(req_path, sizeof req_path, "%s/req_%" PRIu64 ".txt",     g_oracle_dir, seq);
    snprintf(ans_path, sizeof ans_path, "%s/ans_%" PRIu64 ".txt",     g_oracle_dir, seq);

    FILE *rf = fopen(req_tmp, "w");
    if (!rf) {
        fprintf(stderr, "WARNING: oracle: cannot write '%s'\n", req_tmp);
        return verdict;
    }
    fprintf(rf, "d %d n %" PRIu64 " B", depth, subtree_nodes);
    for (int i = 0; i < depth; i++) {
        int ss = fill_order[i].slot;
        fprintf(rf, " %d:%d:%d", ss, (int)(uint8_t)slot_tile[ss], (int)(uint8_t)slot_rot[ss]);
    }
    fputc('\n', rf);
    fclose(rf);
    if (rename(req_tmp, req_path) != 0) {
        fprintf(stderr, "WARNING: oracle: rename '%s' -> '%s' failed\n", req_tmp, req_path);
        remove(req_tmp);
        return verdict;
    }

    g_last_oracle_call_ms = monotonic_ms();
    stat_oracle_calls++;

    uint64_t waited_ms = 0;
    int got = 0;
    while (waited_ms < g_oracle_wait_ms) {
        FILE *af = fopen(ans_path, "r");
        if (af) {
            got = (fgets(verdict, sizeof verdict, af) != NULL);
            fclose(af);
            if (got) break;
        }
        sleep_ms(5);
        waited_ms += 5;
    }
    stat_oracle_wait_ms_total += waited_ms;

    if (!got) { verdict[0] = '\0'; return verdict; }
    size_t vlen = strlen(verdict);
    while (vlen > 0 && (verdict[vlen - 1] == '\n' || verdict[vlen - 1] == '\r')) verdict[--vlen] = '\0';
    return verdict;
}

/* Called right after a candidate at `depth` has been unplaced (so
 * fill_order[depth]'s own slot is empty again -- ancestors 0..depth-1 are
 * the whole placed board). See the big comment block above for the full
 * trigger/verdict logic. */
static inline void maybe_ask_oracle(int depth) {
    if (!g_oracle_on) return;                                          /* the one cheap comparison when OFF */
    if (depth < ORACLE_DEPTH_LO || depth > ORACLE_DEPTH_HI) return;
    if (oracle_asked[depth]) return;                                   /* at most 1 call per frame */
    if (stat_oracle_calls >= g_oracle_max) return;

    uint64_t subtree = stat_nodes - entry_nodes[depth];
    if (subtree <= g_oracle_min) return;

    uint64_t now_ms = monotonic_ms();
    if (g_last_oracle_call_ms != 0 && (now_ms - g_last_oracle_call_ms) < g_oracle_cooldown_ms) return;

    oracle_asked[depth] = 1;   /* mark now: even a timeout must not re-ask this frame */

    const char *verdict = oracle_roundtrip(depth, subtree);
    if (verdict[0] == '\0') {
        stat_oracle_unknown++;                 /* I/O failure or no answer within ORACLE_WAIT */
    } else if (strcmp(verdict, "INFEASIBLE") == 0) {
        stat_oracle_infeasible++;
        g_prune_below = depth;
    } else if (strcmp(verdict, "FEASIBLE") == 0) {
        stat_oracle_feasible++;
    } else {
        stat_oracle_unknown++;
    }
}

/* ============================================================
 * FORCED_PAIRS: forced-adjacency implication (NEW)
 *
 * Certain raw 11-bit edge patterns occur exactly once among all N_SLOTS*3
 * tile edges, with their reverse pattern ALSO occurring exactly once
 * elsewhere (or, if the pattern is its own reverse, occurring exactly
 * TWICE total). In either case the two carrying tile-edges are FORCED to
 * be adjacent in any valid tiling: no other tile-edge in the whole 480-
 * edge set can ever present the required reverse pattern, so whichever
 * board edge one of the two carriers ends up on, the tile-edge on the
 * other side of that board edge must be the carrier's unique partner --
 * no other tile could ever legally sit there.
 *
 * forced_partner[t][e] packs the partner as (tileB<<2 | edgeB), or
 * FP_NONE if tile-edge (t,e) has no forced partner. Computed once at
 * startup from tile_pat[]/rev_pat[] in build_forced_pairs() -- the pairs
 * are never hardcoded, they fall out of the pattern-frequency count.
 *
 * fp_check(s,t,r) is called from all three dfs() candidate loops exactly
 * like dry_check_would_close() -- BEFORE place(), so a rejection costs
 * nothing beyond the check itself. For every edge e of the tile about to
 * be placed that has a forced partner (tB,eB), it finds the neighbouring
 * slot nb across that edge:
 *   - if nb already holds a tile, it must be exactly tB oriented so its
 *     edge eB faces us -- otherwise tB's unique partner-carrying edge can
 *     never be matched anywhere on the board and the WHOLE tiling is dead
 *     (pattern matching alone would only notice this later, once tB is
 *     placed elsewhere and supply/demand finally goes negative; this
 *     catches it immediately).
 *   - if nb is empty, tB must still be unused (else, again, its edge can
 *     never be matched anywhere); additionally, the implied placement of
 *     tB at nb with the forced rotation is checked for pattern-
 *     consistency against nb's OTHER already-placed neighbours, catching
 *     some infeasibilities a level earlier still.
 *
 * OFF by default (FORCED_PAIRS env unset): build_forced_pairs() is never
 * called (forced_partner[][] stays all-FP_NONE, harmless even if read),
 * and every dfs() call site guards fp_check() behind `g_forced_pairs_on`
 * -- one cheap comparison when off, matching STUCK_DUMP/ORACLE_DIR/etc.
 * ============================================================ */
#define FP_NONE 0xFFFFu

static int      g_forced_pairs_on  = 0;
static int      g_rigidity_on       = 0;   /* RIGIDITY=1: value-order candidates by tile rigidity */
static int      g_neighbor_fc       = 0;   /* NEIGHBOR_FC=1|2: forward-check empty neighbours */
static int      g_rarity2_on        = 0;   /* RARITY2=1: frequency-weighted fill-order tiebreak */
static int      g_fill_tie_steps    = 0;   /* diagnostic: #fill steps with a con-tie */
static uint16_t forced_partner[N_SLOTS][3];   /* (tileB<<2|edgeB), or FP_NONE */
static uint64_t stat_fp_rejections = 0;
static uint64_t stat_fc_pruned = 0;

/* Scans tile_pat[]/rev_pat[] (both must already be loaded) to find every
 * raw pattern with global count==1 whose reverse also has global count==1
 * (P != rev(P)), plus every palindromic pattern (P == rev(P)) with global
 * count==2, and records each such pair's two carriers as forced partners
 * of each other. */
static void build_forced_pairs(void) {
    static int16_t raw_count[MAX_PATTERNS];
    static int16_t carrier_t[MAX_PATTERNS];
    static int8_t  carrier_e[MAX_PATTERNS];

    memset(raw_count, 0, sizeof raw_count);
    for (int p = 0; p < MAX_PATTERNS; p++) carrier_t[p] = -1;

    for (int t = 0; t < N_SLOTS; t++) {
        for (int e = 0; e < 3; e++) {
            int raw = tile_pat[t][e];
            if (raw_count[raw] == 0) { carrier_t[raw] = (int16_t)t; carrier_e[raw] = (int8_t)e; }
            raw_count[raw]++;
        }
    }

    for (int t = 0; t < N_SLOTS; t++)
        for (int e = 0; e < 3; e++)
            forced_partner[t][e] = (uint16_t)FP_NONE;

    int n_pairs = 0;
    for (int p = 0; p < MAX_PATTERNS; p++) {
        int rp = rev_pat[p];

        if (p < rp) {
            if (raw_count[p] == 1 && raw_count[rp] == 1) {
                int tA = carrier_t[p],  eA = carrier_e[p];
                int tB = carrier_t[rp], eB = carrier_e[rp];
                forced_partner[tA][eA] = (uint16_t)((tB << 2) | eB);
                forced_partner[tB][eB] = (uint16_t)((tA << 2) | eA);
                n_pairs++;
            }
        } else if (p == rp) {
            if (raw_count[p] == 2) {
                int t1 = -1, e1 = -1, t2 = -1, e2 = -1;
                for (int t = 0; t < N_SLOTS && t2 < 0; t++) {
                    for (int e = 0; e < 3; e++) {
                        if (tile_pat[t][e] != p) continue;
                        if (t1 < 0) { t1 = t; e1 = e; }
                        else        { t2 = t; e2 = e; break; }
                    }
                }
                if (t1 >= 0 && t2 >= 0) {
                    forced_partner[t1][e1] = (uint16_t)((t2 << 2) | e2);
                    forced_partner[t2][e2] = (uint16_t)((t1 << 2) | e1);
                    n_pairs++;
                }
            }
        }
    }

    fprintf(stderr, "  FORCED_PAIRS ON: %d forced pattern pair(s) found\n", n_pairs);
}

/* Pre-placement check: is placing tile t rotation r at slot s consistent
 * with every forced-partner implication triggered by t's own edges? See
 * the big comment block above for the full (a)/(b) reasoning. Called
 * BEFORE place(), exactly like dry_check_would_close(). */
static inline int fp_check(int s, int t, int r) {
    for (int e = 0; e < 3; e++) {
        uint16_t fp = forced_partner[t][e];
        if (fp == (uint16_t)FP_NONE) continue;

        int tB = fp >> 2;
        int eB = fp & 3;
        int j  = (e - r + 3) % 3;         /* slot-edge carrying tile-edge e */
        int nb = g_adj[s][j].slot;
        int kb = g_adj[s][j].edge;

        if (slot_tile[nb] >= 0) {
            int t_nb = (int)(uint8_t)slot_tile[nb];
            int r_nb = (int)(uint8_t)slot_rot[nb];
            if (t_nb != tB || (kb + r_nb) % 3 != eB) return 0;
        } else {
            if (tile_used[tB]) return 0;

            /* Optional stronger check: the implied placement of tB at nb
             * must itself be pattern-consistent with nb's OTHER already-
             * placed neighbours. */
            int r_imp = (eB - kb + 3) % 3;
            for (int jn = 0; jn < 3; jn++) {
                if (jn == kb) continue;
                int nb2 = g_adj[nb][jn].slot;
                if (slot_tile[nb2] < 0) continue;
                int t_nb2 = (int)(uint8_t)slot_tile[nb2];
                int r_nb2 = (int)(uint8_t)slot_rot[nb2];
                int e_nb2 = g_adj[nb][jn].edge;
                uint16_t nb2_pat = tile_pat[t_nb2][(e_nb2 + r_nb2) % 3];
                uint16_t tb_pat  = tile_pat[tB][(jn + r_imp) % 3];
                if (tb_pat != rev_pat[nb2_pat]) return 0;
            }
        }
    }
    return 1;
}

/* ============================================================
 * Helpers
 * ============================================================ */
static uint16_t reverse11(uint16_t p) {
    uint16_t r = 0;
    for (int i = 0; i < PAT_LEN; i++)
        if (p & (1u << i)) r |= (1u << (PAT_LEN - 1 - i));
    return r;
}

static uint16_t parse_pat(const char *s) {
    uint16_t v = 0;
    for (int i = 0; i < PAT_LEN; i++)
        if (s[i] == '1') v |= (1u << i);
    return v;
}

/* ============================================================
 * Parse instance file (identical logic to solver.c / solver2.c)
 * ============================================================ */
static int parse_instance(const char *fname) {
    FILE *f = fopen(fname, "r");
    if (!f) { fprintf(stderr, "Cannot open '%s'\n", fname); return 0; }

    int ns, ne;
    if (fscanf(f, "%d %d", &ns, &ne) != 2 || ns != N_SLOTS || ne != N_EDGES) {
        fprintf(stderr, "Bad header (expected %d %d)\n", N_SLOTS, N_EDGES);
        fclose(f); return 0;
    }

    for (int s = 0; s < N_SLOTS; s++) {
        for (int j = 0; j < 3; j++) {
            int nb, kb;
            if (fscanf(f, "%d %d", &nb, &kb) != 2) {
                fprintf(stderr, "Bad adjacency at s=%d j=%d\n", s, j);
                fclose(f); return 0;
            }
            g_adj[s][j].slot = (uint8_t)nb;
            g_adj[s][j].edge = (uint8_t)kb;
        }
    }

    char p0[16], p1[16], p2[16];
    for (int t = 0; t < N_SLOTS; t++) {
        if (fscanf(f, "%15s %15s %15s", p0, p1, p2) != 3) {
            fprintf(stderr, "Bad tile at t=%d\n", t);
            fclose(f); return 0;
        }
        tile_pat[t][0] = parse_pat(p0);
        tile_pat[t][1] = parse_pat(p1);
        tile_pat[t][2] = parse_pat(p2);
    }

    if (fscanf(f, "%d", &n_seed_slots) != 1) {
        fprintf(stderr, "Bad seed slot count\n"); fclose(f); return 0;
    }
    for (int i = 0; i < n_seed_slots; i++) {
        if (fscanf(f, "%d", &seed_slots[i]) != 1) {
            fprintf(stderr, "Bad seed slot[%d]\n", i); fclose(f); return 0;
        }
    }
    if (fscanf(f, "%d", &seed_tile_id) != 1) {
        fprintf(stderr, "Bad seed tile\n"); fclose(f); return 0;
    }

    fclose(f);
    return 1;
}

/* ============================================================
 * Board-edge canonicalisation (NEW in solver3)
 *
 * Every board edge is shared by exactly two (slot, slot-edge) references
 * (g_adj is symmetric: g_adj[s][j] = (nb,kb) implies g_adj[nb][kb] = (s,j)).
 * Since no slot is adjacent to itself, "the pair with smaller (slot,edge)"
 * reduces to "the side with the smaller slot index" -- side A.
 * ============================================================ */
static void build_edge_ids(void) {
    for (int s = 0; s < N_SLOTS; s++)
        for (int j = 0; j < 3; j++)
            edge_id[s][j] = -1;

    int next_edge = 0;
    for (int s = 0; s < N_SLOTS; s++) {
        for (int j = 0; j < 3; j++) {
            if (edge_id[s][j] != -1) continue;  /* already assigned via neighbour */

            int nb = g_adj[s][j].slot;
            int kb = g_adj[s][j].edge;
            if (nb == s) {
                fprintf(stderr, "FATAL: slot %d edge %d is adjacent to itself (unsupported)\n", s, j);
                exit(1);
            }

            int eid = next_edge++;
            edge_id[s][j]   = eid;
            edge_id[nb][kb] = eid;
            is_sideA[s][j]   = (s  < nb) ? 1 : 0;
            is_sideA[nb][kb] = (nb < s)  ? 1 : 0;
        }
    }

    if (next_edge != N_EDGES) {
        fprintf(stderr, "FATAL: computed %d unique board edges, expected %d\n", next_edge, N_EDGES);
        exit(1);
    }
    fprintf(stderr, "  board edges assigned: %d (UF nodes = %d)\n", next_edge, UF_N);
}

/* node_of(s,j,p) = the endpoint-node id for slot s, slot-edge j, position p
 * (0..10), expressed in side-A coordinates. Two slots that share a board
 * edge map their touching endpoints to the SAME node id -- that is the
 * "automatic fusion" that needs no explicit union. */
static inline int node_of(int s, int j, int p) {
    int eid = edge_id[s][j];
    int q = is_sideA[s][j] ? p : (PAT_LEN - 1 - p);
    return eid * PAT_LEN + q;
}

/* ============================================================
 * Gold arc loading (NEW in solver3)
 *
 * Prefers arcs_flat.txt (one line per tile: "e1 p1 e2 p2  e1 p1 e2 p2 ...",
 * N_SLOTS lines, no external tokens needed beyond strtol). Falls back to a
 * bespoke hand-rolled parser for arcs.json, a JSON array of N_SLOTS tile
 * entries; entry = list of arcs; arc = [[e1,p1],[e2,p2]].
 *
 * The JSON parser relies on the file's rigid, fully regular nesting depth
 * (no library, no general JSON semantics needed):
 *   depth 1: the outer array of tiles
 *   depth 2: a tile's array of arcs      -> depth 1->2 transition = new tile
 *   depth 3: an arc's array of endpoints -> depth 2->3 transition = new arc
 *   depth 4: an endpoint's [e,p] pair    -> integers only ever appear here
 * ============================================================ */
static void load_arcs_flat(FILE *f) {
    char line[4096];
    for (int t = 0; t < N_SLOTS; t++) {
        if (!fgets(line, sizeof line, f)) {
            fprintf(stderr, "FATAL: arcs_flat.txt ended early at tile %d (expected %d lines)\n", t, N_SLOTS);
            exit(1);
        }
        int na = 0;
        char *p = line;
        for (;;) {
            char *end;
            long e1 = strtol(p, &end, 10);
            if (end == p) break;  /* no more numbers on this line */
            p = end;
            long pp1 = strtol(p, &end, 10); p = end;
            long e2  = strtol(p, &end, 10); p = end;
            long pp2 = strtol(p, &end, 10); p = end;

            if (na >= MAX_ARCS_PER_TILE) {
                fprintf(stderr, "FATAL: tile %d has more than %d arcs in arcs_flat.txt\n", t, MAX_ARCS_PER_TILE);
                exit(1);
            }
            tile_arc_e1[t][na] = (uint8_t)e1;
            tile_arc_p1[t][na] = (uint8_t)pp1;
            tile_arc_e2[t][na] = (uint8_t)e2;
            tile_arc_p2[t][na] = (uint8_t)pp2;
            na++;
        }
        tile_arc_count[t] = (uint8_t)na;
    }
}

static void parse_arcs_json(const char *fname) {
    FILE *f = fopen(fname, "rb");
    if (!f) { fprintf(stderr, "FATAL: cannot open '%s'\n", fname); exit(1); }
    fseek(f, 0, SEEK_END);
    long len = ftell(f);
    fseek(f, 0, SEEK_SET);
    char *buf = (char *)malloc((size_t)len + 1);
    if (!buf) { fprintf(stderr, "FATAL: out of memory reading %s (%ld bytes)\n", fname, len); exit(1); }
    size_t rd = fread(buf, 1, (size_t)len, f);
    buf[rd] = '\0';
    fclose(f);

    long i = 0;
    int  depth = 0;
    int  tile_idx = -1;
    int  arc_idx  = -1;
    int  num_pos  = 0;
    long nums[4];

    while (i < (long)rd) {
        char c = buf[i];

        if (c == ' ' || c == '\t' || c == '\n' || c == '\r' || c == ',') { i++; continue; }

        if (c == '[') {
            depth++;
            if (depth == 2) {
                tile_idx++;
                if (tile_idx >= N_SLOTS) {
                    fprintf(stderr, "FATAL: arcs.json has more than %d tile entries\n", N_SLOTS);
                    exit(1);
                }
                arc_idx = -1;
                tile_arc_count[tile_idx] = 0;
            } else if (depth == 3) {
                arc_idx++;
                if (arc_idx >= MAX_ARCS_PER_TILE) {
                    fprintf(stderr, "FATAL: tile %d has more than %d arcs in arcs.json\n", tile_idx, MAX_ARCS_PER_TILE);
                    exit(1);
                }
                num_pos = 0;
            }
            i++;
            continue;
        }

        if (c == ']') {
            if (depth == 3) {
                if (num_pos != 4) {
                    fprintf(stderr, "FATAL: malformed arc at tile %d arc %d (got %d numbers, expected 4)\n",
                            tile_idx, arc_idx, num_pos);
                    exit(1);
                }
                tile_arc_e1[tile_idx][arc_idx] = (uint8_t)nums[0];
                tile_arc_p1[tile_idx][arc_idx] = (uint8_t)nums[1];
                tile_arc_e2[tile_idx][arc_idx] = (uint8_t)nums[2];
                tile_arc_p2[tile_idx][arc_idx] = (uint8_t)nums[3];
                tile_arc_count[tile_idx] = (uint8_t)(arc_idx + 1);
            }
            depth--;
            i++;
            continue;
        }

        if ((c >= '0' && c <= '9') || c == '-') {
            char *end;
            long v = strtol(buf + i, &end, 10);
            if (end == buf + i) {
                fprintf(stderr, "FATAL: bad number in arcs.json near byte %ld\n", i);
                exit(1);
            }
            if (depth == 4) {
                if (num_pos >= 4) {
                    fprintf(stderr, "FATAL: too many numbers in one arc at tile %d arc %d\n", tile_idx, arc_idx);
                    exit(1);
                }
                nums[num_pos++] = v;
            }
            i = (long)(end - buf);
            continue;
        }

        fprintf(stderr, "FATAL: unexpected character '%c' (0x%02x) at byte %ld in arcs.json\n", c, (unsigned char)c, i);
        exit(1);
    }

    if (tile_idx + 1 != N_SLOTS) {
        fprintf(stderr, "FATAL: arcs.json had %d tile entries, expected %d\n", tile_idx + 1, N_SLOTS);
        exit(1);
    }

    free(buf);
}

static void load_arcs(void) {
    FILE *f = fopen("arcs_flat.txt", "r");
    if (f) {
        fprintf(stderr, "  loading gold arcs from arcs_flat.txt\n");
        load_arcs_flat(f);
        fclose(f);
    } else {
        fprintf(stderr, "  arcs_flat.txt not found; parsing arcs.json\n");
        parse_arcs_json("arcs.json");
    }

    int total = 0;
    for (int t = 0; t < N_SLOTS; t++) total += tile_arc_count[t];
    fprintf(stderr, "  loaded %d verified gold arcs across %d tiles (expected 365)\n", total, N_SLOTS);
    if (total != 365) {
        fprintf(stderr, "  WARNING: arc total is %d, not the expected 365 -- continuing anyway\n", total);
    }
}

/* ============================================================
 * Build dense pattern IDs
 * ============================================================ */
static void build_dense_ids(void) {
    memset(raw_to_dense, -1, sizeof(raw_to_dense));
    n_dense = 0;

    for (int t = 0; t < N_SLOTS; t++) {
        for (int e = 0; e < 3; e++) {
            int raw = tile_pat[t][e];
            if (raw_to_dense[raw] < 0) {
                if (n_dense >= MAX_DENSE) {
                    fprintf(stderr, "FATAL: more than %d distinct patterns!\n", MAX_DENSE);
                    exit(1);
                }
                raw_to_dense[raw] = n_dense;
                dense_to_raw[n_dense] = (uint16_t)raw;
                n_dense++;
            }
        }
    }

    /* Also need dense IDs for rev_pat of all patterns (they appear as required patterns) */
    for (int d = 0; d < n_dense; d++) {
        uint16_t raw = dense_to_raw[d];
        uint16_t rraw = rev_pat[raw];
        if (raw_to_dense[rraw] < 0) {
            if (n_dense >= MAX_DENSE) {
                fprintf(stderr, "FATAL: more than %d distinct patterns (including reverses)!\n", MAX_DENSE);
                exit(1);
            }
            raw_to_dense[rraw] = n_dense;
            dense_to_raw[n_dense] = rraw;
            n_dense++;
        }
    }

    /* Fill tile_dpat */
    for (int t = 0; t < N_SLOTS; t++)
        for (int e = 0; e < 3; e++)
            tile_dpat[t][e] = (uint8_t)raw_to_dense[tile_pat[t][e]];

    /* Fill rev_dense */
    for (int d = 0; d < n_dense; d++) {
        uint16_t rraw = rev_pat[dense_to_raw[d]];
        rev_dense[d] = (uint8_t)raw_to_dense[rraw];
    }

    fprintf(stderr, "  distinct patterns (inc. reverses): %d\n", n_dense);
    if (n_dense > MAX_DENSE) { fprintf(stderr, "FATAL: n_dense > MAX_DENSE\n"); exit(1); }
}

/* Static assert: evaluated at runtime via check in main */
static void check_dense_limit(void) {
    if (n_dense > MAX_DENSE) {
        fprintf(stderr, "Static assert violation: n_dense=%d > MAX_DENSE=%d\n", n_dense, MAX_DENSE);
        exit(1);
    }
}

/* ============================================================
 * Build single-pattern lists spd_list[d][j][...]
 * ============================================================ */
static void build_spd_lists(void) {
    memset(spd_count, 0, sizeof(spd_count));
    for (int t = 0; t < N_SLOTS; t++) {
        for (int r = 0; r < 3; r++) {
            for (int j = 0; j < 3; j++) {
                int d = tile_dpat[t][(j + r) % 3];
                int cnt = spd_count[d][j];
                if (cnt < MAX_TILE_CANDS) {
                    spd_list[d][j][cnt] = TR_PACK(t, r);
                    spd_count[d][j]++;
                }
            }
        }
    }
}

/* ============================================================
 * Compute greedy fill order.
 * ============================================================ */
static void build_fill_order(void) {
    uint8_t ordered[N_SLOTS];  /* 1 if already in fill_order */
    memset(ordered, 0, sizeof(ordered));
    memset(fill_pos, -1, sizeof(fill_pos));

    /* Per-dense-pattern tile-edge frequency (for the RARITY2 tiebreak):
     * how the 480 tile-edges distribute across patterns -- i.e. the
     * edge-index imbalance. */
    int patfreq[MAX_DENSE];
    memset(patfreq, 0, sizeof(patfreq));
    for (int t = 0; t < N_SLOTS; t++)
        for (int e = 0; e < 3; e++)
            patfreq[tile_dpat[t][e]]++;

    g_fill_tie_steps = 0;
    int n_ordered = 0;

    /* Always start with seed slot */
    int seed_slot = seed_slots[0];
    fill_order[0].slot = (uint8_t)seed_slot;
    fill_order[0].n_constrained = 0;
    ordered[seed_slot] = 1;
    fill_pos[seed_slot] = 0;
    n_ordered = 1;

    while (n_ordered < N_SLOTS) {
        int best_s = -1;
        int best_constrained = -1;
        double best_rarity = 1e300;

        for (int s = 0; s < N_SLOTS; s++) {
            if (ordered[s]) continue;

            int con = 0;
            for (int j = 0; j < 3; j++) {
                int nb = g_adj[s][j].slot;
                if (ordered[nb]) con++;
            }
            if (con == 0) continue;  /* not reachable yet; skip unless it's the only option */

            /* Tiebreak among equally-constrained slots: lower rarity score =
             * fewer tiles expected to fit -> fill earlier (fail-first).
             * RARITY2 uses a frequency-weighted EXPECTED candidate count per
             * placed-neighbour edge -- for each edge j it averages, over the
             * pattern the neighbour might present (weighted by that pattern's
             * tile-edge frequency = the imbalance), how many tiles could then
             * mate. Default keeps the original crude min-count. */
            double rar_score = (g_rarity2_on == 2) ? 1.0 : 0.0;
            for (int j = 0; j < 3; j++) {
                int nb = g_adj[s][j].slot;
                if (!ordered[nb]) continue;
                if (g_rarity2_on) {
                    double ec = 0.0;
                    for (int p = 0; p < n_dense; p++)
                        ec += (double)patfreq[p] * (double)spd_count[rev_dense[p]][j];
                    ec /= (double)(N_SLOTS * 3);
                    if (g_rarity2_on == 2) rar_score *= (ec + 1e-9);  /* joint estimate */
                    else                   rar_score += ec;
                } else {
                    int min_cnt = MAX_TILE_CANDS + 1;
                    for (int d = 0; d < n_dense; d++)
                        if (spd_count[d][j] < min_cnt) min_cnt = spd_count[d][j];
                    rar_score += (double)min_cnt;
                }
            }

            if (con > best_constrained ||
                (con == best_constrained && rar_score < best_rarity)) {
                best_s = s;
                best_constrained = con;
                best_rarity = rar_score;
            }
        }

        /* Diagnostic: does a con-tie exist at this step (so the rarity
         * tiebreak actually decides anything)? */
        {
            int at_best = 0;
            for (int s = 0; s < N_SLOTS; s++) {
                if (ordered[s]) continue;
                int con = 0;
                for (int j = 0; j < 3; j++)
                    if (ordered[g_adj[s][j].slot]) con++;
                if (con == best_constrained) at_best++;
            }
            if (at_best > 1) g_fill_tie_steps++;
        }

        if (best_s < 0) {
            for (int s = 0; s < N_SLOTS; s++) {
                if (!ordered[s]) { best_s = s; break; }
            }
        }

        int ord = n_ordered;
        FillPos *fp = &fill_order[ord];
        fp->slot = (uint8_t)best_s;
        fp->n_constrained = 0;

        for (int j = 0; j < 3; j++) {
            int nb = g_adj[best_s][j].slot;
            if (ordered[nb]) {
                int c = fp->n_constrained;
                fp->con_j[c]  = (uint8_t)j;
                fp->con_nb[c] = (uint8_t)nb;
                fp->con_kb[c] = g_adj[best_s][j].edge;
                fp->n_constrained++;
            }
        }

        if (fp->n_constrained >= 2) {
            fp->pair_jA = fp->con_j[0];
            fp->pair_jB = fp->con_j[1];
        }

        ordered[best_s] = 1;
        fill_pos[best_s] = ord;
        n_ordered++;
    }
    if (g_rarity2_on)
        fprintf(stderr, "  fill-order tie steps=%d/%d rarity2=%d\n",
                g_fill_tie_steps, N_SLOTS, g_rarity2_on);
}

/* ============================================================
 * Build pair candidate tables for 2-constrained fill positions.
 * ============================================================ */
static void build_pair_tables(void) {
    pair_pool_ptr = pair_pool;

    static uint8_t tmp_count[PAIR_TABLE_DIM];

    for (int ord = 0; ord < N_SLOTS; ord++) {
        FillPos *fp = &fill_order[ord];
        if (fp->n_constrained < 2) {
            for (int k = 0; k < PAIR_TABLE_DIM; k++) {
                pair_table[ord][k].data  = NULL;
                pair_table[ord][k].count = 0;
            }
            continue;
        }

        int jA = fp->pair_jA;
        int jB = fp->pair_jB;

        memset(tmp_count, 0, (size_t)n_dense * n_dense);

        for (int t = 0; t < N_SLOTS; t++) {
            for (int r = 0; r < 3; r++) {
                int dA = tile_dpat[t][(jA + r) % 3];
                int dB = tile_dpat[t][(jB + r) % 3];
                int idx = dA * n_dense + dB;
                if (tmp_count[idx] < 255) tmp_count[idx]++;
            }
        }

        for (int k = 0; k < n_dense * n_dense; k++) {
            pair_table[ord][k].data  = pair_pool_ptr;
            pair_table[ord][k].count = 0;
            pair_pool_ptr += tmp_count[k];
        }

        for (int t = 0; t < N_SLOTS; t++) {
            for (int r = 0; r < 3; r++) {
                int dA = tile_dpat[t][(jA + r) % 3];
                int dB = tile_dpat[t][(jB + r) % 3];
                int idx = dA * n_dense + dB;
                PairEntry *pe = &pair_table[ord][idx];
                pe->data[pe->count++] = TR_PACK(t, r);
            }
        }
    }

    ptrdiff_t pool_used = pair_pool_ptr - pair_pool;
    fprintf(stderr, "  pair pool used: %td entries\n", pool_used);
    if (pool_used > (ptrdiff_t)(sizeof(pair_pool) / sizeof(pair_pool[0]))) {
        fprintf(stderr, "FATAL: pair pool overflow\n");
        exit(1);
    }
}

/* ============================================================
 * Seed random shuffle helper (Fisher-Yates)
 * ============================================================ */
static uint32_t rng_state = 1;
static uint32_t rng_next(void) {
    rng_state ^= rng_state << 13;
    rng_state ^= rng_state >> 17;
    rng_state ^= rng_state << 5;
    return rng_state;
}

static void shuffle_tr(TRPack *arr, int n) {
    for (int i = n - 1; i > 0; i--) {
        int j = (int)(rng_next() % (uint32_t)(i + 1));
        TRPack tmp = arr[i]; arr[i] = arr[j]; arr[j] = tmp;
    }
}

static void shuffle_all_tables(uint32_t seed) {
    if (seed == 0) return;  /* seed 0 = no shuffle */
    rng_state = seed;

    for (int d = 0; d < n_dense; d++)
        for (int j = 0; j < 3; j++)
            shuffle_tr(spd_list[d][j], spd_count[d][j]);

    for (int ord = 0; ord < N_SLOTS; ord++) {
        FillPos *fp = &fill_order[ord];
        if (fp->n_constrained < 2) continue;
        int sz = n_dense * n_dense;
        for (int k = 0; k < sz; k++) {
            PairEntry *pe = &pair_table[ord][k];
            if (pe->count > 1) shuffle_tr(pe->data, pe->count);
        }
    }
}

/* ============================================================
 * Rigidity value-ordering (RIGIDITY=1)
 *
 * Static per-tile "rigidity": a tile is rigid when its edges mate with
 * rare patterns (few other tile-edges can face them). Sorting each
 * candidate list so the most rigid tiles are tried FIRST is a fail-first
 * VALUE heuristic aimed at reaching a full assignment sooner -- it does
 * not change the total exhaustion node count, only the order subtrees are
 * visited, so it is benchmarked on nodes-to-first-solution / best-depth
 * reached, not on coverage.
 * ============================================================ */
static double g_rigidity[N_SLOTS];

static void compute_rigidity(void) {
    int pat_freq[MAX_DENSE];
    memset(pat_freq, 0, sizeof(pat_freq));
    for (int t = 0; t < N_SLOTS; t++)
        for (int e = 0; e < 3; e++)
            pat_freq[tile_dpat[t][e]]++;
    for (int t = 0; t < N_SLOTS; t++) {
        double r = 0.0;
        for (int e = 0; e < 3; e++) {
            int mate = pat_freq[rev_dense[tile_dpat[t][e]]];
            r += 1.0 / (double)(mate > 0 ? mate : 1);
        }
        g_rigidity[t] = r;
    }
}

/* insertion sort a TRPack list by descending tile rigidity (stable enough;
 * lists are short) */
static void sort_tr_by_rigidity(TRPack *arr, int n) {
    for (int i = 1; i < n; i++) {
        TRPack key = arr[i];
        double kr = g_rigidity[TR_TILE(key)];
        int j = i - 1;
        while (j >= 0 && g_rigidity[TR_TILE(arr[j])] < kr) {
            arr[j + 1] = arr[j];
            j--;
        }
        arr[j + 1] = key;
    }
}

static void order_all_tables_by_rigidity(void) {
    compute_rigidity();
    for (int d = 0; d < n_dense; d++)
        for (int j = 0; j < 3; j++)
            sort_tr_by_rigidity(spd_list[d][j], spd_count[d][j]);
    for (int ord = 0; ord < N_SLOTS; ord++) {
        FillPos *fp = &fill_order[ord];
        if (fp->n_constrained < 2) continue;
        int sz = n_dense * n_dense;
        for (int k = 0; k < sz; k++) {
            PairEntry *pe = &pair_table[ord][k];
            if (pe->count > 1) sort_tr_by_rigidity(pe->data, pe->count);
        }
    }
}

/* ============================================================
 * Supply / demand helpers
 * ============================================================ */
static inline void supply_remove(int t) {
    for (int e = 0; e < 3; e++) {
        int d = tile_dpat[t][e];
        supply[d]--;
        if (!touched_flag[d]) { touched_flag[d] = 1; touched[n_touched++] = (uint8_t)d; }
    }
}

static inline void supply_restore(int t) {
    for (int e = 0; e < 3; e++) {
        int d = tile_dpat[t][e];
        supply[d]++;
    }
}

static inline void demand_update_place(int s, int t, int r) {
    for (int j = 0; j < 3; j++) {
        int nb = g_adj[s][j].slot;
        int kb = g_adj[s][j].edge;
        int dpat_j = tile_dpat[t][(j + r) % 3];
        if (slot_tile[nb] < 0) {
            int d_needed = rev_dense[dpat_j];
            demand[d_needed]++;
            if (!touched_flag[d_needed]) {
                touched_flag[d_needed] = 1;
                touched[n_touched++] = (uint8_t)d_needed;
            }
        } else {
            demand[dpat_j]--;
            if (!touched_flag[dpat_j]) {
                touched_flag[dpat_j] = 1;
                touched[n_touched++] = (uint8_t)dpat_j;
            }
            (void)kb;
        }
    }
}

static inline void demand_update_unplace(int s, int t, int r) {
    for (int j = 0; j < 3; j++) {
        int nb = g_adj[s][j].slot;
        int kb = g_adj[s][j].edge;
        int dpat_j = tile_dpat[t][(j + r) % 3];
        if (slot_tile[nb] < 0) {
            int d_needed = rev_dense[dpat_j];
            demand[d_needed]--;
        } else {
            demand[dpat_j]++;
        }
        (void)kb;
    }
}

static inline int supply_demand_ok(void) {
    for (int i = 0; i < n_touched; i++) {
        int d = touched[i];
        if (demand[d] > supply[d]) return 0;
    }
    return 1;
}

static inline void clear_touched(void) {
    for (int i = 0; i < n_touched; i++) touched_flag[touched[i]] = 0;
    n_touched = 0;
}

/* ============================================================
 * Union-find with undo trail (NEW in solver3)
 * ============================================================ */
static void uf_reset(void) {
    for (int i = 0; i < UF_N; i++) { uf_parent[i] = i; uf_rank[i] = 0; }
    uf_trail_top = 0;
    closed_cycles = 0;
}

static int uf_find(int x) {
    while (uf_parent[x] != x) x = uf_parent[x];
    return x;
}

static inline void uf_push(int idx, int old_val, int is_rank) {
    if (uf_trail_top >= UF_TRAIL_CAP) {
        fprintf(stderr, "FATAL: union-find undo trail overflow (cap=%d)\n", UF_TRAIL_CAP);
        exit(1);
    }
    uf_trail[uf_trail_top].idx     = idx;
    uf_trail[uf_trail_top].old_val = old_val;
    uf_trail[uf_trail_top].is_rank = (uint8_t)is_rank;
    uf_trail_top++;
}

/* Link two DIFFERENT roots by rank; records undo entries for both the
 * parent write (always) and the rank write (only on a tie). */
static inline void uf_link(int ra, int rb) {
    if (uf_rank[ra] < uf_rank[rb]) { int t = ra; ra = rb; rb = t; }
    uf_push(rb, uf_parent[rb], 0);
    uf_parent[rb] = ra;
    if (uf_rank[ra] == uf_rank[rb]) {
        uf_push(ra, uf_rank[ra], 1);
        uf_rank[ra]++;
    }
}

static inline void uf_undo_to(int mark) {
    while (uf_trail_top > mark) {
        uf_trail_top--;
        UFUndo *e = &uf_trail[uf_trail_top];
        if (e->is_rank) uf_rank[e->idx]   = e->old_val;
        else            uf_parent[e->idx] = e->old_val;
    }
}

/* Cheap pre-filter (find() only, no writes): reject early if placing tile t
 * with rotation r at slot s would, on its own (against the CURRENT union-find
 * state), close a cycle before the final placement. This is a heuristic --
 * it does not chase chaining between two arcs of the SAME tile (an earlier
 * arc's union could make a later arc's endpoints collide) -- but that is
 * fine: apply_loop_unions() below is the authoritative, exhaustive check. */
static inline int dry_check_would_close(int s, int t, int r, int depth) {
    if (depth == N_SLOTS - 1) return 0;  /* final placement: closures allowed */
    int na = tile_arc_count[t];
    for (int k = 0; k < na; k++) {
        int j1 = (tile_arc_e1[t][k] - r + 3) % 3;
        int j2 = (tile_arc_e2[t][k] - r + 3) % 3;
        int n1 = node_of(s, j1, tile_arc_p1[t][k]);
        int n2 = node_of(s, j2, tile_arc_p2[t][k]);
        if (uf_find(n1) == uf_find(n2)) return 1;
    }
    return 0;
}

/* Authoritative loop-union step for placing tile t/rot r at slot s at fill-
 * order depth. Processes the tile's verified arcs IN ORDER with REAL unions,
 * so a cycle closure created by chaining two of the tile's own arcs together
 * is caught correctly (unlike the dry pre-filter). Returns 1 on success
 * (unions committed; mark/cycle-count recorded in uf_mark_stack/uf_cyc_stack
 * so undo_loop_unions(depth) can reverse exactly this). Returns 0 on
 * rejection (a cycle would close at depth < N_SLOTS-1); any partial unions
 * already applied for THIS tile are rolled back before returning, so the
 * caller need not (and must not) call undo_loop_unions in that case. */
static int apply_loop_unions(int s, int t, int r, int depth) {
    int mark = uf_trail_top;
    int local_cycles = 0;
    int is_last = (depth == N_SLOTS - 1);
    int na = tile_arc_count[t];

    for (int k = 0; k < na; k++) {
        int j1 = (tile_arc_e1[t][k] - r + 3) % 3;
        int j2 = (tile_arc_e2[t][k] - r + 3) % 3;
        int n1 = node_of(s, j1, tile_arc_p1[t][k]);
        int n2 = node_of(s, j2, tile_arc_p2[t][k]);
        int ra = uf_find(n1), rb = uf_find(n2);

        if (ra == rb) {
            local_cycles++;
            if (!is_last) {
                uf_undo_to(mark);
                return 0;
            }
            /* last placement: closure allowed; roots already equal, nothing to union */
        } else {
            uf_link(ra, rb);
        }
    }

    uf_mark_stack[depth] = mark;
    uf_cyc_stack[depth]  = local_cycles;
    closed_cycles += local_cycles;
    return 1;
}

static inline void undo_loop_unions(int depth) {
    closed_cycles -= uf_cyc_stack[depth];
    uf_undo_to(uf_mark_stack[depth]);
}

/* ============================================================
 * Place / unplace (incremental)
 * ============================================================ */
static inline void place(int s, int t, int r) {
    slot_tile[s] = (int8_t)t;
    slot_rot[s]  = (int8_t)r;
    tile_used[t] = 1;
}

static inline void unplace(int s) {
    int t = (int)(uint8_t)slot_tile[s];
    tile_used[t] = 0;
    slot_tile[s] = -1;
    slot_rot[s]  = -1;
}

/* ============================================================
 * Output helpers
 * ============================================================ */
static void write_solution(FILE *sol) {
    for (int s = 0; s < N_SLOTS; s++) {
        if (s) fputc(' ', sol);
        fprintf(sol, "%d:%d:%d", s, (int)(uint8_t)slot_tile[s], (int)(uint8_t)slot_rot[s]);
    }
    fputc('\n', sol);
    fflush(sol);
}

static void write_partial(const char *fname, int depth) {
    FILE *f = fopen(fname, "w");
    if (!f) return;
    int first = 1;
    for (int i = 0; i < depth; i++) {
        int s = fill_order[i].slot;
        if (slot_tile[s] < 0) continue;
        if (!first) fputc(' ', f);
        fprintf(f, "%d:%d:%d", s, (int)(uint8_t)slot_tile[s], (int)(uint8_t)slot_rot[s]);
        first = 0;
    }
    fputc('\n', f);
    fclose(f);
}

static int g_prefix[48];
static char pfx_buf[400];
static const char *pfx_str(void) {
    int off = 0;
    for (int i = 0; i < 40; i++)
        off += snprintf(pfx_buf + off, sizeof(pfx_buf) - off, "%d%s", g_prefix[i], i < 39 ? "." : "");
    return pfx_buf;
}
static void print_stats(int depth) {
    time_t now = time(NULL);
    double elapsed = difftime(now, t_start);
    double nps = (elapsed > 0) ? (double)stat_nodes / elapsed : 0.0;
    /* TIME_LIMIT expiry check lives here: this is the one place the DFS
     * already periodically calls back into, so no extra timing calls are
     * added anywhere on the hot path. */
    if (g_time_limit > 0.0 && elapsed >= g_time_limit) limit_hit = 1;

    char oracle_suffix[192];
    oracle_suffix[0] = '\0';
    if (g_oracle_on) {
        snprintf(oracle_suffix, sizeof oracle_suffix,
            " oracle_calls=%" PRIu64 " oracle_infeas=%" PRIu64 " oracle_feas=%" PRIu64
            " oracle_unk=%" PRIu64 " oracle_wait_ms=%" PRIu64,
            stat_oracle_calls, stat_oracle_infeasible, stat_oracle_feasible,
            stat_oracle_unknown, stat_oracle_wait_ms_total);
    }

    char fp_suffix[64];
    fp_suffix[0] = '\0';
    if (g_forced_pairs_on) {
        snprintf(fp_suffix, sizeof fp_suffix, " fp_rejections=%" PRIu64, stat_fp_rejections);
    }
    static char fc_suffix[48];
    fc_suffix[0] = '\0';
    if (g_neighbor_fc)
        snprintf(fc_suffix, sizeof fc_suffix, " fc_pruned=%" PRIu64, stat_fc_pruned);

    if (g_stuck_dump_on) {
        fprintf(stderr,
            "nodes=%" PRIu64 " depth=%d max_depth=%d sol=%" PRIu64 " nps=%.0f best=%d cycles_pruned=%" PRIu64
            " dumps=%" PRIu64 " pfx=%s%s%s\n",
            stat_nodes, depth, stat_max_depth, stat_solutions, nps, stat_best_partial, stat_cycles_pruned,
            stat_dumps, pfx_str(), oracle_suffix, fp_suffix);
    } else {
        fprintf(stderr,
            "nodes=%" PRIu64 " depth=%d max_depth=%d sol=%" PRIu64 " nps=%.0f best=%d cycles_pruned=%" PRIu64
            " pfx=%s%s%s%s\n",
            stat_nodes, depth, stat_max_depth, stat_solutions, nps, stat_best_partial, stat_cycles_pruned,
            pfx_str(), oracle_suffix, fp_suffix, fc_suffix);
    }
    fflush(stderr);
    t_last_stats = now;
}

/* ============================================================
 * EQUIV_STATS measurement (NEW in solver3) -- implementation.
 * (Declarations/constants/equiv_probe() are up near the STUCK_DUMP block;
 * this needs node_of() and uf_find(), which are defined later than that
 * block, so the function body lives here, right before dfs() calls it.)
 * ============================================================ */
static inline void maybe_equiv_stats(int depth) {
    if (!g_equiv_stats_on) return;                                   /* the one cheap comparison when OFF */
    if (depth < EQUIV_DEPTH_LO || depth > EQUIV_DEPTH_HI) return;
    if ((g_equiv_calls++ % EQUIV_SAMPLE_STRIDE) != 0) return;         /* sample 1/EQUIV_SAMPLE_STRIDE entries */

    /* ---- match_sig: tile_used[] bitmap + near-frontier boundary reqs ---- */
    uint64_t h = FNV_OFFSET_BASIS;
    h = fnv1a_bytes(h, tile_used, sizeof(tile_used));
    h = fnv1a_bytes(h, &depth, sizeof(depth));

    int hi = depth + EQUIV_LOOKAHEAD;
    if (hi > N_SLOTS - 1) hi = N_SLOTS - 1;
    for (int i = depth; i <= hi; i++) {
        FillPos *fpi = &fill_order[i];
        for (int c = 0; c < fpi->n_constrained; c++) {
            int nb = fpi->con_nb[c];
            if (fill_pos[nb] >= depth) continue;   /* earlier in static order than i, but not placed YET */
            int kb   = fpi->con_kb[c];
            int t_nb = (int)(uint8_t)slot_tile[nb];
            int r_nb = (int)(uint8_t)slot_rot[nb];
            uint8_t  dpat  = tile_dpat[t_nb][(kb + r_nb) % 3];
            uint16_t pos16 = (uint16_t)i;
            h = fnv1a_bytes(h, &pos16, sizeof(pos16));
            h = fnv1a_bytes(h, &dpat,  sizeof(dpat));
        }
    }
    uint64_t match_sig = h;
    int bucket = (depth - EQUIV_DEPTH_LO) / EQUIV_BUCKET_WIDTH;   /* depth in [LO,HI] => bucket in [0,N_BUCKETS) */

    {
        int steps;
        EquivProbeOutcome oc = equiv_probe(match_table, match_sig, &steps);
        stat_equiv_match_probes            += (uint64_t)steps;
        stat_equiv_match_bucket_probes[bucket] += (uint64_t)steps;
        if (oc == EQUIV_PROBE_HIT)    { stat_equiv_match_hits++;    stat_equiv_match_bucket_hits[bucket]++; }
        else if (oc == EQUIV_PROBE_INSERT) stat_equiv_match_inserts++;
        else                                stat_equiv_match_full++;
    }

    /* ---- loop_sig: match_sig + canonicalised UF roots of boundary nodes ---- */
    uint64_t h2 = match_sig;
    canon_epoch++;
    int32_t next_id = 0;
    for (int idx = 0; idx < depth; idx++) {
        int p = fill_order[idx].slot;
        for (int j = 0; j < 3; j++) {
            int nb = g_adj[p][j].slot;
            if (fill_pos[nb] < depth) continue;   /* neighbour already placed -> not a boundary edge */
            for (int pos = 0; pos < PAT_LEN; pos++) {
                int node = node_of(p, j, pos);
                int root = uf_find(node);
                int32_t cid;
                if (canon_stamp[root] == canon_epoch) {
                    cid = canon_id[root];
                } else {
                    cid = next_id++;
                    canon_stamp[root] = canon_epoch;
                    canon_id[root]    = cid;
                }
                h2 = fnv1a_bytes(h2, &cid, sizeof(cid));
            }
        }
    }
    uint64_t loop_sig = h2;
    {
        int steps;
        EquivProbeOutcome oc = equiv_probe(loop_table, loop_sig, &steps);
        stat_equiv_loop_probes             += (uint64_t)steps;
        stat_equiv_loop_bucket_probes[bucket] += (uint64_t)steps;
        if (oc == EQUIV_PROBE_HIT)    { stat_equiv_loop_hits++;    stat_equiv_loop_bucket_hits[bucket]++; }
        else if (oc == EQUIV_PROBE_INSERT) stat_equiv_loop_inserts++;
        else                                stat_equiv_loop_full++;
    }
}

static inline double equiv_rate(uint64_t hits, uint64_t probes) {
    return probes ? (100.0 * (double)hits / (double)probes) : 0.0;
}

static void print_equiv_stats(void) {
    if (!g_equiv_stats_on) return;

    fprintf(stderr,
        "EQUIV match: probes=%" PRIu64 " hits=%" PRIu64 " rate=%.2f%% | "
        "loop: probes=%" PRIu64 " hits=%" PRIu64 " rate=%.2f%%\n",
        stat_equiv_match_probes, stat_equiv_match_hits,
        equiv_rate(stat_equiv_match_hits, stat_equiv_match_probes),
        stat_equiv_loop_probes, stat_equiv_loop_hits,
        equiv_rate(stat_equiv_loop_hits, stat_equiv_loop_probes));
    fprintf(stderr,
        "EQUIV detail: match inserts=%" PRIu64 " full=%" PRIu64
        " | loop inserts=%" PRIu64 " full=%" PRIu64 " (sampled 1/%d, depth=[%d,%d])\n",
        stat_equiv_match_inserts, stat_equiv_match_full,
        stat_equiv_loop_inserts, stat_equiv_loop_full,
        EQUIV_SAMPLE_STRIDE, EQUIV_DEPTH_LO, EQUIV_DEPTH_HI);

    for (int b = 0; b < EQUIV_N_BUCKETS; b++) {
        int d_lo = EQUIV_DEPTH_LO + b * EQUIV_BUCKET_WIDTH;
        int d_hi = d_lo + EQUIV_BUCKET_WIDTH - 1;
        fprintf(stderr,
            "EQUIV d%d-%d match: P=%" PRIu64 " H=%" PRIu64 " rate=%.2f%% | "
            "loop: P=%" PRIu64 " H=%" PRIu64 " rate=%.2f%%\n",
            d_lo, d_hi,
            stat_equiv_match_bucket_probes[b], stat_equiv_match_bucket_hits[b],
            equiv_rate(stat_equiv_match_bucket_hits[b], stat_equiv_match_bucket_probes[b]),
            stat_equiv_loop_bucket_probes[b], stat_equiv_loop_bucket_hits[b],
            equiv_rate(stat_equiv_loop_bucket_hits[b], stat_equiv_loop_bucket_probes[b]));
    }
    fflush(stderr);
}

/* ============================================================
 * Neighbour forward-check (NEIGHBOR_FC=1).
 *
 * After placing at slot s, for each still-empty neighbour nb: gather nb's
 * currently-placed-neighbour edge constraints and verify at least one
 * unused (tile,rotation) satisfies them all. If any empty neighbour has
 * zero viable candidates, the just-made placement is dead -> prune. This
 * is a joint forward-check (all active constraints on nb, not just the
 * newly-added one) and reduces total nodes; benchmarked on coverage.
 * Returns 1 if DEAD (should prune), 0 otherwise.
 * ============================================================ */
static int neighbor_fc_dead(int s) {
    for (int jn = 0; jn < 3; jn++) {
        int nb = g_adj[s][jn].slot;
        if (slot_tile[nb] >= 0) continue;   /* already placed */

        /* Collect nb's active edge constraints from its placed neighbours. */
        int cj[3], creq[3], nc = 0;
        for (int j2 = 0; j2 < 3; j2++) {
            int ps = g_adj[nb][j2].slot;
            int t_ps = slot_tile[ps];
            if (t_ps < 0) continue;         /* that neighbour empty -> no constraint yet */
            int e_ps = g_adj[nb][j2].edge;
            int r_ps = slot_rot[ps];
            int dp = tile_dpat[t_ps][(e_ps + r_ps) % 3];
            cj[nc]  = j2;
            creq[nc] = rev_dense[dp];
            nc++;
        }
        if (nc == 0) continue;              /* nb unconstrained -> trivially alive */

        int alive = 0;
        for (int t = 0; t < N_SLOTS && !alive; t++) {
            if (tile_used[t]) continue;
            for (int r = 0; r < 3; r++) {
                int ok = 1;
                for (int c = 0; c < nc; c++) {
                    if ((int)tile_dpat[t][(cj[c] + r) % 3] != creq[c]) { ok = 0; break; }
                }
                if (ok) { alive = 1; break; }
            }
        }
        if (!alive) return 1;               /* nb has no viable candidate -> dead */
    }
    return 0;
}

/* ============================================================
 * Core DFS over the static fill order.
 *
 * depth = index into fill_order[]; we are about to fill fill_order[depth].
 * All slots fill_order[0..depth-1] are placed.
 * ============================================================ */
static void dfs(int depth, FILE *sol_file) {
    if (limit_hit) return;
    if (g_frontier_f && g_depth_cap > 0 && depth == g_depth_cap) {
        fprintf(g_frontier_f, "d %d n 0 B", depth);
        for (int i = 0; i < depth; i++) {
            int ss = fill_order[i].slot;
            fprintf(g_frontier_f, " %d:%d:%d", ss,
                    (int)(uint8_t)slot_tile[ss], (int)(uint8_t)slot_rot[ss]);
        }
        fputc('\n', g_frontier_f);
        g_frontier_count++;
        return;
    }
    if (g_depth_cap > 0 && depth > g_depth_cap) return;
    if (g_prune_below >= 0 && depth > g_prune_below) return;

    if ((g_stuck_dump_on || g_oracle_on) && depth >= STUCK_DEPTH_LO && depth <= STUCK_DEPTH_HI)
        entry_nodes[depth] = stat_nodes;
    if (g_oracle_on && depth >= ORACLE_DEPTH_LO && depth <= ORACLE_DEPTH_HI)
        oracle_asked[depth] = 0;

    stat_nodes++;
    maybe_equiv_stats(depth);
    if ((stat_nodes & ((1u << 26) - 1)) == 0) print_stats(depth);
    {
        time_t now = time(NULL);
        if (difftime(now, t_last_stats) >= 10.0) print_stats(depth);
    }
    if (node_limit > 0 && stat_nodes >= node_limit) { limit_hit = 1; return; }
    if (g_prefix_node_cap && (stat_nodes - g_prefix_pstart) > g_prefix_node_cap) {
        limit_hit = 1; g_prefix_capped = 1; return;
    }

    if (depth > stat_max_depth) stat_max_depth = depth;
    if (depth > stat_best_partial) {
        stat_best_partial = depth;
        write_partial("best3_partial.txt", depth);
    }

    if (depth == N_SLOTS) {
        /* Full tiling found (matches + supply/demand already satisfied).
         * Accept as a GOLD SOLUTION only if the gold arcs collapsed into
         * exactly ONE single cycle across the whole board. */
        if (closed_cycles == 1) {
            stat_solutions++;
            write_solution(sol_file);
        } else {
            stat_cycles_pruned++;
        }
        return;
    }

    FillPos *fp = &fill_order[depth];
    int s = fp->slot;
    int nc = fp->n_constrained;

    uint8_t req_d[3];
    for (int c = 0; c < nc; c++) {
        int nb   = fp->con_nb[c];
        int kb   = fp->con_kb[c];
        int t_nb = (int)(uint8_t)slot_tile[nb];
        int r_nb = (int)(uint8_t)slot_rot[nb];
        int dpat = tile_dpat[t_nb][(kb + r_nb) % 3];
        req_d[c] = rev_dense[dpat];
    }

    if (nc == 0) {
        for (int t = 0; t < N_SLOTS; t++) {
            if (tile_used[t]) continue;
            for (int r = 0; r < 3; r++) {
                if (dry_check_would_close(s, t, r, depth)) { stat_cycles_pruned++; continue; }
                if (g_forced_pairs_on && !fp_check(s, t, r)) { stat_fp_rejections++; continue; }

                place(s, t, r);
                n_touched = 0;
                supply_remove(t);
                demand_update_place(s, t, r);
                if (supply_demand_ok()) {
                    clear_touched();
                    if (apply_loop_unions(s, t, r, depth)) {
                        if (g_neighbor_fc && neighbor_fc_dead(s)) {
                            stat_fc_pruned++;
                        } else {
                            if (depth < 48) g_prefix[depth] = t*3+r;
                            dfs(depth + 1, sol_file);
                        }
                        undo_loop_unions(depth);
                    } else {
                        stat_cycles_pruned++;
                    }
                } else {
                    clear_touched();
                }
                demand_update_unplace(s, t, r);
                supply_restore(t);
                unplace(s);
                maybe_ask_oracle(depth);
                if (g_prune_below >= 0 && depth >= g_prune_below) {
                    if (g_prune_below == depth) g_prune_below = -1;
                    return;
                }
                if (limit_hit) return;
            }
        }
        maybe_dump_stuck(depth);
        return;
    }

    if (nc == 1) {
        int d0 = req_d[0];
        int j0 = fp->con_j[0];
        TRPack *lst = spd_list[d0][j0];
        int len = spd_count[d0][j0];

        for (int i = 0; i < len; i++) {
            TRPack tr = lst[i];
            int t = TR_TILE(tr);
            int r = TR_ROT(tr);
            if (tile_used[t]) continue;
            if (dry_check_would_close(s, t, r, depth)) { stat_cycles_pruned++; continue; }
            if (g_forced_pairs_on && !fp_check(s, t, r)) { stat_fp_rejections++; continue; }

            place(s, t, r);
            n_touched = 0;
            supply_remove(t);
            demand_update_place(s, t, r);
            if (supply_demand_ok()) {
                clear_touched();
                if (apply_loop_unions(s, t, r, depth)) {
                    if (g_neighbor_fc && neighbor_fc_dead(s)) {
                        stat_fc_pruned++;
                    } else {
                        if (depth < 48) g_prefix[depth] = i;
                        dfs(depth + 1, sol_file);
                    }
                    undo_loop_unions(depth);
                } else {
                    stat_cycles_pruned++;
                }
            } else {
                clear_touched();
            }
            demand_update_unplace(s, t, r);
            supply_restore(t);
            unplace(s);
            maybe_ask_oracle(depth);
            if (g_prune_below >= 0 && depth >= g_prune_below) {
                if (g_prune_below == depth) g_prune_below = -1;
                return;
            }
            if (limit_hit) return;
        }
        maybe_dump_stuck(depth);
        return;
    }

    /* nc >= 2: use pair table for first two constraints, check third explicitly */
    {
        int dA = req_d[0];
        int dB = req_d[1];
        int jA = fp->pair_jA;
        int jB = fp->pair_jB;
        (void)jA; (void)jB;

        int idx = dA * n_dense + dB;
        PairEntry *pe = &pair_table[depth][idx];
        int len = pe->count;
        TRPack *lst = pe->data;

        for (int i = 0; i < len; i++) {
            TRPack tr = lst[i];
            int t = TR_TILE(tr);
            int r = TR_ROT(tr);
            if (tile_used[t]) continue;

            if (nc == 3) {
                int j2 = fp->con_j[2];
                int d2 = req_d[2];
                if ((int)tile_dpat[t][(j2 + r) % 3] != d2) continue;
            }

            if (dry_check_would_close(s, t, r, depth)) { stat_cycles_pruned++; continue; }
            if (g_forced_pairs_on && !fp_check(s, t, r)) { stat_fp_rejections++; continue; }

            place(s, t, r);
            n_touched = 0;
            supply_remove(t);
            demand_update_place(s, t, r);
            if (supply_demand_ok()) {
                clear_touched();
                if (apply_loop_unions(s, t, r, depth)) {
                    if (g_neighbor_fc && neighbor_fc_dead(s)) {
                        stat_fc_pruned++;
                    } else {
                        if (depth < 48) g_prefix[depth] = i;
                        dfs(depth + 1, sol_file);
                    }
                    undo_loop_unions(depth);
                } else {
                    stat_cycles_pruned++;
                }
            } else {
                clear_touched();
            }
            demand_update_unplace(s, t, r);
            supply_restore(t);
            unplace(s);
            maybe_ask_oracle(depth);
            if (g_prune_below >= 0 && depth >= g_prune_below) {
                if (g_prune_below == depth) g_prune_below = -1;
                return;
            }
            if (limit_hit) return;
        }
        maybe_dump_stuck(depth);
        return;
    }
}

/* ============================================================
 * Knuth backtrack-tree size estimator (ESTIMATE=N env)
 *
 * For each root unit, runs N independent random root-to-leaf probes of the
 * EXACT tree dfs() would search: at every depth it enumerates the children
 * that pass every real check (candidate tables, third-constraint, loop
 * closure, forced pairs, supply/demand, loop unions), multiplies the
 * running product by that count, adds it to the node estimate, then
 * descends into one uniformly-random viable child. The mean of the probe
 * estimates is an unbiased estimator of the unit's total dfs() node count
 * (Knuth 1975). The oracle is NOT modelled, so relative to the hybrid
 * engine the result is an UPPER bound on nodes actually visited.
 * ============================================================ */
static uint64_t g_est_probes = 0;      /* ESTIMATE=N -> estimator mode */
static double   g_est_grand  = 0.0;    /* sum of unit means */
static uint64_t est_rng_state = 0x9E3779B97F4A7C15ull;

static inline uint64_t est_rand(void) {
    uint64_t x = est_rng_state;
    x ^= x << 13; x ^= x >> 7; x ^= x << 17;
    est_rng_state = x;
    return x;
}

typedef struct { uint8_t t, r; } EstCand;

/* Enumerate children of the current node at `depth` that dfs() would
 * actually recurse into. Mirrors the three nc cases of dfs() exactly. */
static int est_enumerate(int depth, EstCand *out) {
    FillPos *fp = &fill_order[depth];
    int s = fp->slot;
    int nc = fp->n_constrained;

    uint8_t req_d[3];
    for (int c = 0; c < nc; c++) {
        int nb   = fp->con_nb[c];
        int kb   = fp->con_kb[c];
        int t_nb = (int)(uint8_t)slot_tile[nb];
        int r_nb = (int)(uint8_t)slot_rot[nb];
        int dpat = tile_dpat[t_nb][(kb + r_nb) % 3];
        req_d[c] = rev_dense[dpat];
    }

    int n_out = 0;

    /* Deep viability test shared by all three candidate streams. */
    #define EST_TRY(tt, rr)                                                 \
        do {                                                                \
            int t_ = (tt), r_ = (rr);                                       \
            if (!tile_used[t_] &&                                           \
                !dry_check_would_close(s, t_, r_, depth) &&                 \
                (!g_forced_pairs_on || fp_check(s, t_, r_))) {              \
                place(s, t_, r_);                                           \
                n_touched = 0;                                              \
                supply_remove(t_);                                          \
                demand_update_place(s, t_, r_);                             \
                int ok_ = 0;                                                \
                if (supply_demand_ok()) {                                   \
                    clear_touched();                                        \
                    if (apply_loop_unions(s, t_, r_, depth)) {              \
                        ok_ = (!g_neighbor_fc || !neighbor_fc_dead(s));     \
                        undo_loop_unions(depth);                            \
                    }                                                       \
                } else {                                                    \
                    clear_touched();                                        \
                }                                                           \
                demand_update_unplace(s, t_, r_);                           \
                supply_restore(t_);                                         \
                unplace(s);                                                 \
                if (ok_) { out[n_out].t = (uint8_t)t_;                      \
                           out[n_out].r = (uint8_t)r_; n_out++; }           \
            }                                                               \
        } while (0)

    if (nc == 0) {
        for (int t = 0; t < N_SLOTS; t++) {
            if (tile_used[t]) continue;
            for (int r = 0; r < 3; r++) EST_TRY(t, r);
        }
    } else if (nc == 1) {
        TRPack *lst = spd_list[req_d[0]][fp->con_j[0]];
        int len = spd_count[req_d[0]][fp->con_j[0]];
        for (int i = 0; i < len; i++)
            EST_TRY(TR_TILE(lst[i]), TR_ROT(lst[i]));
    } else {
        int idx = req_d[0] * n_dense + req_d[1];
        PairEntry *pe = &pair_table[depth][idx];
        for (int i = 0; i < pe->count; i++) {
            int t = TR_TILE(pe->data[i]);
            int r = TR_ROT(pe->data[i]);
            if (nc == 3 &&
                (int)tile_dpat[t][(fp->con_j[2] + r) % 3] != req_d[2])
                continue;
            EST_TRY(t, r);
        }
    }
    #undef EST_TRY
    return n_out;
}

/* Run g_est_probes probes of the current unit (seed tile already placed by
 * the caller, exactly as for dfs(1)). Prints a per-unit summary and adds
 * the unit's mean estimate to g_est_grand. */
static double g_est_depth_nodes[N_SLOTS + 1];  /* sum over units of E[#nodes at depth k] */

/* EST_DUMP="12,16,20": dump up to 200 surviving prefixes per listed depth
 * to est_prefixes_<k>.txt, in the oracle req_ line format, for offline
 * CP-SAT refutation-time measurement. */
static int g_est_dump_depth[8];
static int g_est_dump_n = 0;
static int g_est_dump_count[8];
#define EST_DUMP_CAP 200

static void est_maybe_dump_prefix(int depth) {
    for (int i = 0; i < g_est_dump_n; i++) {
        if (g_est_dump_depth[i] != depth || g_est_dump_count[i] >= EST_DUMP_CAP)
            continue;
        char path[64];
        snprintf(path, sizeof path, "est_prefixes_%d.txt", depth);
        FILE *f = fopen(path, "a");
        if (!f) return;
        fprintf(f, "d %d n 0 B", depth);
        for (int j = 0; j < depth; j++) {
            int ss = fill_order[j].slot;
            fprintf(f, " %d:%d:%d", ss, (int)(uint8_t)slot_tile[ss], (int)(uint8_t)slot_rot[ss]);
        }
        fputc('\n', f);
        fclose(f);
        g_est_dump_count[i]++;
    }
}

static void estimate_unit(int unit_id) {
    static EstCand cands[N_SLOTS * 3];
    static int applied_depths[N_SLOTS];
    static double depth_P_sum[N_SLOTS + 1];
    memset(depth_P_sum, 0, sizeof(depth_P_sum));

    double sum_est = 0.0, max_est = 0.0;
    uint64_t depth_sum = 0, overflow_probes = 0, full_leaves = 0;
    int deepest = 0;
    /* batch means over 10 batches for a rough spread indication */
    double batch_sum[10] = {0};
    uint64_t per_batch = g_est_probes / 10; if (per_batch == 0) per_batch = 1;

    for (uint64_t p = 0; p < g_est_probes; p++) {
        double P = 1.0, est = 1.0;
        int depth = 1, n_applied = 0;

        for (;;) {
            if (depth == N_SLOTS) { full_leaves++; break; }
            if (g_depth_cap > 0 && depth == g_depth_cap) break;
            int b = est_enumerate(depth, cands);
            if (b == 0) break;
            P *= (double)b;
            est += P;
            if (isinf(est)) { overflow_probes++; break; }
            depth_P_sum[depth + 1] += P;

            EstCand c = cands[est_rand() % (uint64_t)b];
            int s = fill_order[depth].slot;
            place(s, c.t, c.r);
            n_touched = 0;
            supply_remove(c.t);
            demand_update_place(s, c.t, c.r);
            clear_touched();
            apply_loop_unions(s, c.t, c.r, depth);
            applied_depths[n_applied++] = depth;
            depth++;
            if (g_est_dump_n > 0) est_maybe_dump_prefix(depth);
        }

        if (depth > deepest) deepest = depth;
        depth_sum += (uint64_t)depth;

        for (int i = n_applied - 1; i >= 0; i--) {
            int d = applied_depths[i];
            int s = fill_order[d].slot;
            int t = (int)(uint8_t)slot_tile[s];
            int r = (int)(uint8_t)slot_rot[s];
            undo_loop_unions(d);
            demand_update_unplace(s, t, r);
            supply_restore(t);
            unplace(s);
        }

        sum_est += est;
        if (est > max_est) max_est = est;
        batch_sum[(p / per_batch) % 10] += est;

        if (((p + 1) & 0xFFFF) == 0)
            fprintf(stderr, "  [est u%d] probe %" PRIu64 "/%" PRIu64
                    " running_mean=%.3e\n",
                    unit_id, p + 1, g_est_probes, sum_est / (double)(p + 1));
    }

    double mean = sum_est / (double)g_est_probes;
    double bmin = batch_sum[0] / (double)per_batch, bmax = bmin;
    for (int i = 1; i < 10; i++) {
        double bm = batch_sum[i] / (double)per_batch;
        if (bm < bmin) bmin = bm;
        if (bm > bmax) bmax = bm;
    }
    g_est_grand += mean;
    for (int k = 0; k <= N_SLOTS; k++)
        g_est_depth_nodes[k] += depth_P_sum[k] / (double)g_est_probes;
    fprintf(stderr, "EST unit %d mean_nodes=%.4e batch_range=[%.2e,%.2e] "
            "max_probe=%.2e avg_death_depth=%.1f deepest=%d full_leaves=%" PRIu64
            " overflow=%" PRIu64 "\n",
            unit_id, mean, bmin, bmax, max_est,
            (double)depth_sum / (double)g_est_probes, deepest,
            full_leaves, overflow_probes);
}

/* ============================================================
 * Reset board state
 * ============================================================ */
static void reset_board(void) {
    memset(slot_tile, -1, sizeof(slot_tile));
    memset(slot_rot,  -1, sizeof(slot_rot));
    memset(tile_used,  0, sizeof(tile_used));
    memset(supply,     0, sizeof(supply));
    memset(demand,     0, sizeof(demand));
    memset(touched_flag, 0, sizeof(touched_flag));
    n_touched = 0;

    for (int t = 0; t < N_SLOTS; t++)
        for (int e = 0; e < 3; e++)
            supply[tile_dpat[t][e]]++;
}

/* ============================================================
 * PREFIX_FILE mode: re-root the search at each prefix listed in a file
 * (req_ line format, one per line). For every line: rebuild the fill
 * order for the line's seed slot, place the prefix with full
 * bookkeeping, then dfs() from its depth -- honouring DEPTH_CAP and
 * FRONTIER_FILE, which turns this into the "expand these subtrees two
 * more plies and dump their children" primitive of the recursive
 * shallow-refutation strategy.
 * ============================================================ */
static void run_prefix_file(const char *path, FILE *sol) {
    FILE *pf = fopen(path, "r");
    if (!pf) { fprintf(stderr, "FATAL: cannot open PREFIX_FILE '%s'\n", path); exit(1); }
    static char line[16384];
    int idx = 0;
    int orig_ss0 = seed_slots[0];

    long seen = -1;                 /* ordinal among valid "d" prefix lines */
    long processed = 0;
    while (fgets(line, sizeof line, pf)) {
        int k; uint64_t nn;
        if (sscanf(line, "d %d n %" SCNu64 " B", &k, &nn) != 2) continue;
        seen++;
        if (seen < g_prefix_start) continue;
        if (g_prefix_count >= 0 && seen >= g_prefix_start + g_prefix_count) break;
        processed++;
        char *p = strchr(line, 'B') + 1;

        static int slots[N_SLOTS], tiles[N_SLOTS], rots[N_SLOTS];
        int n = 0, s_, t_, r_, consumed;
        while (n < k && sscanf(p, " %d:%d:%d%n", &s_, &t_, &r_, &consumed) == 3) {
            slots[n] = s_; tiles[n] = t_; rots[n] = r_; n++; p += consumed;
        }
        if (n != k) {
            fprintf(stderr, "PREFIX %d PARSE_ERROR (%d/%d triples)\n", idx++, n, k);
            continue;
        }

        if (fill_order[0].slot != (uint8_t)slots[0]) {
            seed_slots[0] = slots[0];
            build_fill_order();
            build_pair_tables();
            seed_slots[0] = orig_ss0;
        }
        reset_board();
        uf_reset();
        g_prune_below = -1;

        uint64_t nodes0 = stat_nodes, sols0 = stat_solutions, fr0 = g_frontier_count;
        int ok = 1;
        for (int i = 0; i < k; i++) {
            if (fill_order[i].slot != (uint8_t)slots[i]) {
                fprintf(stderr, "PREFIX %d SLOT_MISMATCH at %d (fill=%d line=%d)\n",
                        idx, i, (int)fill_order[i].slot, slots[i]);
                ok = 0; break;
            }
            place(slots[i], tiles[i], rots[i]);
            n_touched = 0;
            supply_remove(tiles[i]);
            demand_update_place(slots[i], tiles[i], rots[i]);
            int sd = supply_demand_ok();
            clear_touched();
            if (!sd || !apply_loop_unions(slots[i], tiles[i], rots[i], i)) {
                fprintf(stderr, "PREFIX %d REJECTED at i=%d (sd=%d)\n", idx, i, sd);
                ok = 0; break;
            }
        }
        if (ok) {
            g_prefix_pstart = stat_nodes;
            g_prefix_capped = 0;
            dfs(k, sol);
            if (limit_hit && g_prefix_capped) {
                /* Per-prefix cap tripped (not a global stop): defer this
                 * prefix for deeper decomposition and keep going. */
                limit_hit = 0;
                g_prefix_capped = 0;
                if (g_defer_f) {
                    fprintf(g_defer_f, "d %d n 0 B", k);
                    for (int j = 0; j < k; j++) {
                        int ss = fill_order[j].slot;
                        fprintf(g_defer_f, " %d:%d:%d", ss,
                                (int)(uint8_t)slot_tile[ss], (int)(uint8_t)slot_rot[ss]);
                    }
                    fputc('\n', g_defer_f);
                    fflush(g_defer_f);
                }
                g_defer_count++;
                fprintf(stderr, "PREFIX %d DEFERRED (exceeded node cap)\n", idx);
            }
        }
        if (g_frontier_f) fflush(g_frontier_f);
        fprintf(stderr, "PREFIX %d %s nodes=%" PRIu64 " sols=%" PRIu64
                " frontier_children=%" PRIu64 "\n",
                idx, ok ? "OK" : "SKIP",
                stat_nodes - nodes0, stat_solutions - sols0,
                g_frontier_count - fr0);
        idx++;
        if (limit_hit) { fprintf(stderr, "PREFIX_FILE: limit hit, stopping\n"); break; }
    }
    fclose(pf);
    /* Bankable batch marker: EXHAUSTED only if we finished the whole slice
     * without hitting the node/time limit. */
    if (limit_hit)
        fprintf(stderr, "PREFIX_BATCH INCOMPLETE start=%ld processed=%ld\n",
                g_prefix_start, processed);
    else
        fprintf(stderr, "PREFIX_BATCH EXHAUSTED start=%ld count=%ld sols=%" PRIu64
                " deferred=%ld\n",
                g_prefix_start, processed, stat_solutions, g_defer_count);
}

/* ============================================================
 * Main
 * ============================================================ */
int main(int argc, char *argv[]) {
    if (argc < 2) {
        fprintf(stderr, "Usage: %s <instance> [node_limit] [seed]\n", argv[0]);
        fprintf(stderr, "  node_limit=0 for unlimited\n");
        fprintf(stderr, "  seed=0 for deterministic order, 1..N for shuffled\n");
        return 1;
    }

    uint64_t cli_node_limit = 0;
    uint32_t cli_seed = 0;
    if (argc >= 3) cli_node_limit = (uint64_t)strtoull(argv[2], NULL, 10);
    if (argc >= 4) cli_seed = (uint32_t)strtoul(argv[3], NULL, 10);

    /* Stuck-subtree dump: OFF unless STUCK_DUMP names an output file. */
    {
        const char *dump_path = getenv("STUCK_DUMP");
        if (dump_path && dump_path[0]) {
            g_stuck_dump_f = fopen(dump_path, "a");
            if (!g_stuck_dump_f) {
                fprintf(stderr, "WARNING: cannot open STUCK_DUMP file '%s'; dumps disabled\n", dump_path);
            } else {
                g_stuck_dump_on = 1;
                const char *min_s = getenv("STUCK_MIN");
                if (min_s && min_s[0]) g_stuck_min = strtoull(min_s, NULL, 10);
                fprintf(stderr, "  STUCK_DUMP ON: file='%s' STUCK_MIN=%" PRIu64 " depth=[%d,%d]\n",
                        dump_path, g_stuck_min, STUCK_DEPTH_LO, STUCK_DEPTH_HI);
            }
        }
    }

    /* ROOT_UNIT: parse the raw integer now; it can only be range-checked
     * against n_seed_slots*3 once the instance is parsed (below). */
    {
        const char *ru = getenv("ROOT_UNIT");
        if (ru && ru[0]) g_root_unit = atoi(ru);
    }

    /* ESTIMATE: N Knuth probes per unit instead of searching. */
    {
        const char *es = getenv("ESTIMATE");
        if (es && es[0]) g_est_probes = strtoull(es, NULL, 10);
        if (g_est_probes > 0) {
            const char *esd = getenv("ESTIMATE_SEED");
            if (esd && esd[0]) est_rng_state ^= strtoull(esd, NULL, 10);
            est_rng_state ^= (uint64_t)time(NULL);
            fprintf(stderr, "  ESTIMATE ON: %" PRIu64 " probes/unit\n", g_est_probes);
        }
        const char *ed = getenv("EST_DUMP");
        if (ed && ed[0]) {
            char buf[128];
            strncpy(buf, ed, sizeof buf - 1); buf[sizeof buf - 1] = '\0';
            for (char *tok = strtok(buf, ","); tok && g_est_dump_n < 8; tok = strtok(NULL, ","))
                g_est_dump_depth[g_est_dump_n++] = atoi(tok);
            fprintf(stderr, "  EST_DUMP ON: %d depth(s), cap %d prefixes each\n",
                    g_est_dump_n, EST_DUMP_CAP);
        }
        const char *dc = getenv("DEPTH_CAP");
        if (dc && dc[0]) g_depth_cap = atoi(dc);
        if (g_depth_cap > 0)
            fprintf(stderr, "  DEPTH_CAP ON: tree truncated below depth %d\n", g_depth_cap);
    }

    /* TIME_LIMIT: optional wall-clock budget in seconds, checked from the
     * existing periodic print_stats() path. Unset/<=0 means unlimited. */
    {
        const char *tl = getenv("TIME_LIMIT");
        if (tl && tl[0]) g_time_limit = strtod(tl, NULL);
    }

    /* EQUIV_STATS: measurement-only equivalence-signature revisit stats. */
    {
        const char *es = getenv("EQUIV_STATS");
        if (es && es[0] && atoi(es) != 0) {
            g_equiv_stats_on = 1;
            fprintf(stderr, "  EQUIV_STATS ON: depth=[%d,%d] sample=1/%d lookahead=%d table=2^%d x2\n",
                    EQUIV_DEPTH_LO, EQUIV_DEPTH_HI, EQUIV_SAMPLE_STRIDE, EQUIV_LOOKAHEAD, EQUIV_TABLE_BITS);
        }
    }

    /* ORACLE_DIR: persistent CP-SAT stuck-subtree oracle sidecar. */
    {
        const char *od = getenv("ORACLE_DIR");
        if (od && od[0]) {
            g_oracle_on = 1;
            strncpy(g_oracle_dir, od, sizeof(g_oracle_dir) - 1);
            g_oracle_dir[sizeof(g_oracle_dir) - 1] = '\0';
            oracle_mkdir(g_oracle_dir);   /* best-effort; fine if it already exists */

            const char *om = getenv("ORACLE_MIN");
            if (om && om[0]) g_oracle_min = strtoull(om, NULL, 10);
            const char *ow = getenv("ORACLE_WAIT");
            if (ow && ow[0]) g_oracle_wait_ms = strtoull(ow, NULL, 10);
            const char *ocd = getenv("ORACLE_COOLDOWN_MS");
            if (ocd && ocd[0]) g_oracle_cooldown_ms = strtoull(ocd, NULL, 10);
            const char *omax = getenv("ORACLE_MAX");
            if (omax && omax[0]) g_oracle_max = strtoull(omax, NULL, 10);

            fprintf(stderr,
                "  ORACLE ON: dir='%s' depth=[%d,%d] ORACLE_MIN=%" PRIu64 " ORACLE_WAIT=%" PRIu64
                "ms ORACLE_COOLDOWN_MS=%" PRIu64 " ORACLE_MAX=%" PRIu64 "\n",
                g_oracle_dir, ORACLE_DEPTH_LO, ORACLE_DEPTH_HI, g_oracle_min, g_oracle_wait_ms,
                g_oracle_cooldown_ms, g_oracle_max);
        }
    }

    /* FORCED_PAIRS: forced-adjacency implication from globally-unique
     * pattern pairs. build_forced_pairs() itself is called later, once
     * tile_pat[]/rev_pat[] are both ready (see below). */
    {
        const char *fpv = getenv("FORCED_PAIRS");
        if (fpv && fpv[0] && atoi(fpv) != 0) g_forced_pairs_on = 1;
        const char *rgv = getenv("RIGIDITY");
        if (rgv && rgv[0] && atoi(rgv) != 0) g_rigidity_on = 1;
        const char *fcv = getenv("NEIGHBOR_FC");
        if (fcv && fcv[0]) g_neighbor_fc = atoi(fcv);
        const char *r2v = getenv("RARITY2");
        if (r2v && r2v[0]) g_rarity2_on = atoi(r2v);
    }

    /* Build reverse table */
    for (int p = 0; p < MAX_PATTERNS; p++) rev_pat[p] = reverse11((uint16_t)p);

    /* Parse instance */
    if (!parse_instance(argv[1])) return 1;

    fprintf(stderr, "Diamond Dilemma Solver 3 (single-loop pruning)\n");
    fprintf(stderr, "  instance: %s\n", argv[1]);
    fprintf(stderr, "  seed tile: %d, seed slots: %d\n", seed_tile_id, n_seed_slots);
    fprintf(stderr, "  node_limit: %" PRIu64 ", rng_seed: %u\n", cli_node_limit, cli_seed);

    /* Board-edge canonicalisation + gold arc data (needs g_adj from parse_instance) */
    build_edge_ids();
    load_arcs();

    /* FORCED_PAIRS precompute: needs tile_pat[]+rev_pat[], both ready now.
     * Skipped entirely (zero cost) when FORCED_PAIRS is unset. */
    if (g_forced_pairs_on) build_forced_pairs();

    /* Build dense pattern IDs */
    build_dense_ids();
    check_dense_limit();

    /* Build single-pattern driver lists */
    build_spd_lists();

    /* Sort seed slots ascending */
    for (int i = 0; i < n_seed_slots - 1; i++)
        for (int j = i + 1; j < n_seed_slots; j++)
            if (seed_slots[j] < seed_slots[i]) {
                int tmp = seed_slots[i]; seed_slots[i] = seed_slots[j]; seed_slots[j] = tmp;
            }

    /* ROOT_UNIT range check + decode, now that seed_slots[] is in the final
     * (sorted) order the outer loop below actually iterates in. unit u maps
     * to seed_slots[u/3] rotation u%3, for u in [0, n_seed_slots*3). */
    int unit_si = -1, unit_r = -1;
    if (g_root_unit >= 0) {
        if (g_root_unit >= n_seed_slots * 3) {
            fprintf(stderr, "FATAL: ROOT_UNIT=%d out of range [0,%d)\n", g_root_unit, n_seed_slots * 3);
            return 1;
        }
        unit_si = g_root_unit / 3;
        unit_r  = g_root_unit % 3;
        fprintf(stderr, "  ROOT_UNIT=%d -> seed_slots[%d]=%d rot=%d (only this unit runs)\n",
                g_root_unit, unit_si, seed_slots[unit_si], unit_r);
    }

    /* Compute fill order */
    build_fill_order();

    /* Build pair tables */
    build_pair_tables();

    /* Optionally shuffle candidate lists for this seed */
    if (cli_seed > 0) shuffle_all_tables(cli_seed);

    node_limit = cli_node_limit;

    /* Print fill order summary */
    {
        int c0 = 0, c1 = 0, c2 = 0, c3 = 0;
        for (int i = 0; i < N_SLOTS; i++) {
            switch (fill_order[i].n_constrained) {
                case 0: c0++; break;
                case 1: c1++; break;
                case 2: c2++; break;
                case 3: c3++; break;
            }
        }
        fprintf(stderr, "  fill order: 0-con=%d 1-con=%d 2-con=%d 3-con=%d\n", c0, c1, c2, c3);
    }

    /* Open solution file (append) */
    FILE *sol = fopen("solutions3.txt", "a");
    if (!sol) { fprintf(stderr, "Cannot open solutions3.txt\n"); return 1; }

    t_start = t_last_stats = time(NULL);
    stat_best_partial = 0;
    stat_max_depth    = 0;
    stat_nodes        = 0;
    stat_solutions    = 0;

    /* FRONTIER_FILE / PREFIX_FILE modes */
    {
        const char *ff = getenv("FRONTIER_FILE");
        if (ff && ff[0]) {
            g_frontier_f = fopen(ff, "w");
            if (!g_frontier_f) { fprintf(stderr, "FATAL: cannot open FRONTIER_FILE '%s'\n", ff); return 1; }
            fprintf(stderr, "  FRONTIER_FILE ON: '%s' (dump at depth %d)\n", ff, g_depth_cap);
        }
        const char *pfx = getenv("PREFIX_FILE");
        if (pfx && pfx[0]) {
            const char *ps = getenv("PREFIX_START");
            const char *pc = getenv("PREFIX_COUNT");
            if (ps && ps[0]) g_prefix_start = atol(ps);
            if (pc && pc[0]) g_prefix_count = atol(pc);
            const char *pnc = getenv("PREFIX_NODE_CAP");
            if (pnc && pnc[0]) g_prefix_node_cap = strtoull(pnc, NULL, 10);
            const char *df = getenv("DEFER_FILE");
            if (df && df[0]) {
                g_defer_f = fopen(df, "a");
                if (!g_defer_f) fprintf(stderr, "WARN: cannot open DEFER_FILE '%s'\n", df);
            }
            run_prefix_file(pfx, sol);
            if (g_defer_f) fclose(g_defer_f);
            fprintf(stderr, "PREFIX_FILE DONE total_nodes=%" PRIu64 " total_sols=%" PRIu64
                    " total_frontier=%" PRIu64 "\n",
                    stat_nodes, stat_solutions, g_frontier_count);
            if (g_frontier_f) fclose(g_frontier_f);
            fclose(sol);
            return 0;
        }
    }

    /* Outer loop: seed slot x rotation (symmetry breaking as in solver.c).
     * When ROOT_UNIT is set, every iteration except the single targeted
     * (unit_si, unit_r) is skipped -- cheaply, before the expensive
     * fill_order/pair_table rebuild below, so a ROOT_UNIT run does none of
     * the other units' setup work either. */
    for (int si = 0; si < n_seed_slots && !limit_hit; si++) {
        if (g_root_unit >= 0 && si != unit_si) continue;
        int ss = seed_slots[si];

        if (fill_order[0].slot != (uint8_t)ss) {
            int orig_ss0 = seed_slots[0];
            seed_slots[0] = ss;
            build_fill_order();
            build_pair_tables();
            if (cli_seed > 0) shuffle_all_tables(cli_seed);
            if (g_rigidity_on) order_all_tables_by_rigidity();
            seed_slots[0] = orig_ss0;
        }

        for (int r = 0; r < 3 && !limit_hit; r++) {
            if (g_root_unit >= 0 && r != unit_r) continue;
            reset_board();
            uf_reset();
            g_prune_below = -1;

            /* Place seed tile at fill_order[0] = ss */
            int t_seed = seed_tile_id;
            place(ss, t_seed, r);

            /* Update supply/demand for seed placement */
            n_touched = 0;
            supply_remove(t_seed);
            demand_update_place(ss, t_seed, r);
            clear_touched();

            /* Loop-union bookkeeping for the seed placement (depth 0). The
             * union-find is completely empty at this point, so no cycle can
             * possibly close yet; the check is done anyway for uniformity
             * and defence-in-depth. */
            if (apply_loop_unions(ss, t_seed, r, 0)) {
                fprintf(stderr, "seed slot=%d tile=%d rot=%d\n", ss, seed_tile_id, r);

                if (g_est_probes > 0)
                    estimate_unit(si * 3 + r);
                else
                    /* DFS from depth=1 (depth 0 = ss is placed) */
                    dfs(1, sol);

                undo_loop_unions(0);
            } else {
                fprintf(stderr, "WARNING: seed placement unexpectedly rejected by loop pruning (slot=%d tile=%d rot=%d)\n",
                        ss, seed_tile_id, r);
                stat_cycles_pruned++;
            }

            /* Unplace seed */
            demand_update_unplace(ss, t_seed, r);
            supply_restore(t_seed);
            unplace(ss);
        }
    }

    /* ROOT_UNIT run: report this unit's outcome and exit with a status the
     * ledger driver can branch on (0 = EXHAUSTED -> mark DONE in the
     * ledger; 3 = INCOMPLETE -> release the claim for a future, bigger-
     * budget retry). Natural exhaustion means the single targeted (si,r)
     * combination's dfs() call returned on its own, i.e. limit_hit never
     * got set (neither node_limit nor TIME_LIMIT fired). */
    if (g_frontier_f) {
        fprintf(stderr, "FRONTIER TOTAL count=%" PRIu64 "\n", g_frontier_count);
        fclose(g_frontier_f);
        g_frontier_f = NULL;
    }

    if (g_est_probes > 0) {
        fprintf(stderr, "EST DEPTH PROFILE (expected surviving prefixes at depth k, all units):\n");
        for (int k = 2; k <= N_SLOTS; k += 2) {
            if (g_est_depth_nodes[k] <= 0.0) break;
            fprintf(stderr, "  k=%3d survivors=%.3e\n", k, g_est_depth_nodes[k]);
        }
        fprintf(stderr, "EST GRAND TOTAL (sum of unit means): %.4e nodes\n", g_est_grand);
        fflush(stderr);
        fclose(sol);
        if (g_stuck_dump_f) fclose(g_stuck_dump_f);
        return 0;
    }

    if (g_root_unit >= 0) {
        print_stats(0);
        print_equiv_stats();
        if (limit_hit) {
            fprintf(stderr, "UNIT %d INCOMPLETE nodes=%" PRIu64, g_root_unit, stat_nodes);
            if (g_oracle_on) fprintf(stderr, " oracle_calls=%" PRIu64 " oracle_infeas=%" PRIu64,
                                     stat_oracle_calls, stat_oracle_infeasible);
            fprintf(stderr, "\n");
            fflush(stderr);
            fclose(sol);
            if (g_stuck_dump_f) fclose(g_stuck_dump_f);
            return 3;
        } else {
            fprintf(stderr, "UNIT %d EXHAUSTED nodes=%" PRIu64 " sols=%" PRIu64,
                    g_root_unit, stat_nodes, stat_solutions);
            if (g_oracle_on) fprintf(stderr, " oracle_calls=%" PRIu64 " oracle_infeas=%" PRIu64,
                                     stat_oracle_calls, stat_oracle_infeasible);
            fprintf(stderr, "\n");
            fflush(stderr);
            fclose(sol);
            if (g_stuck_dump_f) fclose(g_stuck_dump_f);
            return 0;
        }
    }

    print_stats(0);
    fprintf(stderr, "DONE. nodes=%" PRIu64 " solutions=%" PRIu64 " cycles_pruned=%" PRIu64,
        stat_nodes, stat_solutions, stat_cycles_pruned);
    if (g_stuck_dump_on) fprintf(stderr, " dumps=%" PRIu64, stat_dumps);
    if (g_oracle_on) {
        fprintf(stderr,
            " oracle_calls=%" PRIu64 " oracle_infeas=%" PRIu64 " oracle_feas=%" PRIu64
            " oracle_unk=%" PRIu64 " oracle_wait_ms=%" PRIu64,
            stat_oracle_calls, stat_oracle_infeasible, stat_oracle_feasible,
            stat_oracle_unknown, stat_oracle_wait_ms_total);
    }
    if (g_forced_pairs_on) fprintf(stderr, " fp_rejections=%" PRIu64, stat_fp_rejections);
    fprintf(stderr, "\n");
    print_equiv_stats();
    fclose(sol);
    if (g_stuck_dump_f) fclose(g_stuck_dump_f);
    return 0;
}
