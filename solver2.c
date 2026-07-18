/*
 * solver2.c -- Diamond Dilemma Gold: optimised DFS solver.
 *
 * Compile: zig cc -O3 -o solver2.exe solver2.c
 * (C11, single file, no external dependencies beyond libc)
 *
 * Usage:
 *   solver2.exe <instance_file> <node_limit> <seed>
 *   node_limit = 0 means unlimited
 *   seed = 1..N  permutes candidate order so parallel runs explore different subtrees
 *
 * Key optimisations over solver.c:
 *   1. STATIC FILL ORDER: greedy BFS-style order precomputed at startup,
 *      maximising already-ordered neighbours (2-constrained placements first).
 *      Tie-break by rarest required-pattern potential.
 *   2. PAIR-INDEXED CANDIDATE TABLES: for slots with 2 earlier neighbours,
 *      candidates fetched from pair_list[dA * MAX_DENSE + dB] (zero rejection
 *      except tile_used check). Per slot the pair of constrained edges varies;
 *      precomputed per fill-order position.
 *   3. SUPPLY/DEMAND PRUNE (E2 "colour counting"): supply[p] = edges with pattern
 *      p on unused tiles; demand[p] = unfilled constraint edges requiring p.
 *      After each placement/unplacement we check only touched patterns.
 *
 * CONVENTIONS (same as solver.c, never modified):
 *   Placement: tile t rotation r in slot s maps tile-edge (j+r)%3 -> slot-edge j.
 *   Match: pattern on slot-edge j == rev_pat[pattern on facing neighbour's edge].
 *   Instance format identical to solver.c (parse_instance duplicated here).
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <inttypes.h>
#include <time.h>

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
/* sp_list[d][e] = list of (tile<<2|rot) where tile edge e carries dense pattern d */
/* We build one flat list per (dense_pat, tile_edge) pair, length sp_count[d][e] */
static TRPack   sp_list[MAX_DENSE][MAX_TILE_CANDS];
static int      sp_count[MAX_DENSE];       /* number of (tile,rot) pairs for pattern d */
/* Actually we want sp_list[d] = list of all (t,r) where tile edge (drive+r)%3 has dense d
 * -- but that depends on which slot-edge is driven.  We build it per (dense,slot_edge) below. */

/* Per (dense_pat, slot_edge_index) single-pattern list:
 * spd_list[d][j][i] = TR_PACK(t,r) where tile_dpat[t][(j+r)%3] == d */
static TRPack   spd_list[MAX_DENSE][3][MAX_TILE_CANDS];
static int      spd_count[MAX_DENSE][3];

/* ---- Pair-candidate lists ---- */
/* pair_list[dA * MAX_DENSE + dB] indexed per fill-order slot (see slot2 geometry below) */
/* We store per fill-order index the pair lists; each fill-order slot with 2+ earlier
 * neighbours has TWO constrained slot-edges (jA, jB) with required patterns (dA, dB).
 * pair_list_slot[ord] points to a flat array; pair_entry is indexed [dA*n_dense + dB]. */

/* Maximum pairs: MAX_DENSE * MAX_DENSE entries each up to MAX_PAIR_CANDS */
/* That's 128*128*160*2 bytes = ~5MB: fine. */
#define PAIR_TABLE_DIM  (MAX_DENSE * MAX_DENSE)
typedef struct {
    TRPack *data;   /* pointer into big pool */
    uint8_t count;
} PairEntry;

/* We have at most N_SLOTS fill-order positions, each potentially needing a pair table.
 * Allocate one big pool. */
static TRPack   pair_pool[N_SLOTS * PAIR_TABLE_DIM * MAX_PAIR_CANDS]; /* upper bound; will be much smaller */
static PairEntry pair_table[N_SLOTS][PAIR_TABLE_DIM]; /* pair_table[ord][dA*n_dense+dB] */
static TRPack   *pair_pool_ptr;   /* bump allocator */

/* ---- Seed configuration ---- */
#define MAX_SEED_SLOTS N_SLOTS
static int seed_slots[MAX_SEED_SLOTS];
static int n_seed_slots = 0;
static int seed_tile_id = 23;

/* ============================================================
 * Fill order (precomputed at startup)
 * ============================================================ */
typedef struct {
    uint8_t  slot;           /* which slot */
    uint8_t  n_constrained;  /* how many of its 3 neighbours come EARLIER in fill order */
    /* Per earlier-neighbour info: which slot-edge j of THIS slot is constrained */
    /* and from which neighbour slot and neighbour edge */
    uint8_t  con_j[3];       /* slot-edge index for each earlier constraint (0..2) */
    uint8_t  con_nb[3];      /* earlier neighbour slot */
    uint8_t  con_kb[3];      /* earlier neighbour's edge index */
    /* For 2-constrained: which two slot-edges form the pair for pair_list lookup */
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
 * Parse instance file (identical logic to solver.c)
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
 * spd_list[d][j] = list of TRPack(t,r) such that tile_dpat[t][(j+r)%3] == d
 * i.e. placing tile t with rot r puts pattern d on slot-edge j.
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
 *
 * Start with the seed slot (slots[0] = seed_slots[0]).
 * Then greedily pick the unordered slot with the most already-ordered
 * neighbours (= most constraints available), tie-break by minimum
 * sum of spd_count for the required patterns on its constrained edges.
 * ============================================================ */
static void build_fill_order(void) {
    uint8_t ordered[N_SLOTS];  /* 1 if already in fill_order */
    memset(ordered, 0, sizeof(ordered));
    memset(fill_pos, -1, sizeof(fill_pos));

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
        int best_rarity = INT32_MAX;

        for (int s = 0; s < N_SLOTS; s++) {
            if (ordered[s]) continue;

            /* Count how many of s's neighbours are already ordered */
            int con = 0;
            for (int j = 0; j < 3; j++) {
                int nb = g_adj[s][j].slot;
                if (ordered[nb]) con++;
            }
            if (con == 0) continue;  /* not reachable yet; skip unless it's the only option */

            /* Rarity score: sum of spd_count for required patterns on constrained edges */
            int rarity = 0;
            for (int j = 0; j < 3; j++) {
                int nb = g_adj[s][j].slot;
                if (!ordered[nb]) continue;
                /* if nb were placed, it would put rev_pat on s's edge j.
                 * We don't know which tile/rot yet, but we can sum over
                 * pattern frequencies as a proxy. Use overall spd_count[d][j]
                 * averaged over d -- but since we don't know d yet, use
                 * the min spd_count[d][j] over all d as a tiebreaker sentinel. */
                /* Simpler: use the number of (tile,rot) pairs for slot-edge j
                 * as a measure of how constrained it is = sum spd_count[d][j] = N_SLOTS*3
                 * always the same. Just use con count and break ties randomly. */
                rarity += 1;  /* placeholder: con determines primary order */
            }
            (void)rarity; /* suppress warning; primary tiebreak below uses pattern stats */

            /* Compute rarity as total spd_count entries reachable for constrained edges */
            int rar2 = 0;
            for (int j = 0; j < 3; j++) {
                int nb = g_adj[s][j].slot;
                if (!ordered[nb]) continue;
                /* Any pattern could appear; use average list length = N_SLOTS*3/n_dense */
                /* Better: sum min spd_count over all d for edge j */
                int min_cnt = MAX_TILE_CANDS + 1;
                for (int d = 0; d < n_dense; d++) {
                    if (spd_count[d][j] < min_cnt) min_cnt = spd_count[d][j];
                }
                rar2 += min_cnt;
            }

            if (con > best_constrained ||
                (con == best_constrained && rar2 < best_rarity)) {
                best_s = s;
                best_constrained = con;
                best_rarity = rar2;
            }
        }

        if (best_s < 0) {
            /* No slot has an ordered neighbour yet -- pick any unordered */
            for (int s = 0; s < N_SLOTS; s++) {
                if (!ordered[s]) { best_s = s; break; }
            }
        }

        /* Fill in FillPos for best_s */
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

        /* Set pair_jA, pair_jB for 2-constrained case */
        if (fp->n_constrained >= 2) {
            fp->pair_jA = fp->con_j[0];
            fp->pair_jB = fp->con_j[1];
        }

        ordered[best_s] = 1;
        fill_pos[best_s] = ord;
        n_ordered++;
    }
}

/* ============================================================
 * Build pair candidate tables for 2-constrained fill positions.
 *
 * For fill-order position ord with pair_jA=jA, pair_jB=jB:
 *   pair_table[ord][dA*n_dense + dB] = list of TRPack(t,r) such that
 *     tile_dpat[t][(jA+r)%3] == dA  AND  tile_dpat[t][(jB+r)%3] == dB
 *
 * We build this by iterating over (t,r) and bucketing.
 * ============================================================ */
static void build_pair_tables(void) {
    pair_pool_ptr = pair_pool;

    /* Temporary counting arrays */
    static uint8_t tmp_count[PAIR_TABLE_DIM];
    /* We need a temp buffer per (ord, dA, dB). Build in two passes. */

    for (int ord = 0; ord < N_SLOTS; ord++) {
        FillPos *fp = &fill_order[ord];
        if (fp->n_constrained < 2) {
            /* No pair table needed */
            for (int k = 0; k < PAIR_TABLE_DIM; k++) {
                pair_table[ord][k].data  = NULL;
                pair_table[ord][k].count = 0;
            }
            continue;
        }

        int jA = fp->pair_jA;
        int jB = fp->pair_jB;

        /* Count pass */
        memset(tmp_count, 0, (size_t)n_dense * n_dense);

        for (int t = 0; t < N_SLOTS; t++) {
            for (int r = 0; r < 3; r++) {
                int dA = tile_dpat[t][(jA + r) % 3];
                int dB = tile_dpat[t][(jB + r) % 3];
                int idx = dA * n_dense + dB;
                if (tmp_count[idx] < 255) tmp_count[idx]++;
            }
        }

        /* Assign pool pointers */
        for (int k = 0; k < n_dense * n_dense; k++) {
            pair_table[ord][k].data  = pair_pool_ptr;
            pair_table[ord][k].count = 0;
            pair_pool_ptr += tmp_count[k];
        }

        /* Fill pass */
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

/* Shuffle all candidate tables so different seeds explore different orderings */
static void shuffle_all_tables(uint32_t seed) {
    if (seed == 0) return;  /* seed 0 = no shuffle */
    rng_state = seed;

    /* Shuffle spd_list */
    for (int d = 0; d < n_dense; d++)
        for (int j = 0; j < 3; j++)
            shuffle_tr(spd_list[d][j], spd_count[d][j]);

    /* Shuffle pair tables */
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
 * Supply / demand helpers
 * ============================================================ */

/* Called when tile t is placed: remove its 3 edges from supply */
static inline void supply_remove(int t) {
    for (int e = 0; e < 3; e++) {
        int d = tile_dpat[t][e];
        supply[d]--;
        if (!touched_flag[d]) { touched_flag[d] = 1; touched[n_touched++] = (uint8_t)d; }
    }
}

/* Called when tile t is unplaced: restore its 3 edges to supply */
static inline void supply_restore(int t) {
    for (int e = 0; e < 3; e++) {
        int d = tile_dpat[t][e];
        supply[d]++;
        /* No need to add to touched list on unplace -- we clear after check */
    }
}

/*
 * Called when slot s is placed (tile t, rot r).
 * For each of s's neighbours nb that is NOT yet placed: the edge s presents
 * towards nb now demands rev of what s put there, i.e. the pattern on nb's
 * edge facing s.  We ADD that demand.
 * Also: the demand that nb had for the pattern s consumed (if nb was placed)
 * was already "consumed" by the placement check; but here we track demands
 * from PLACED->UNFILLED direction only, so we remove the demand that s itself
 * satisfied from already-placed neighbours.
 *
 * Convention: demand[d] = number of (placed_slot -> empty_slot) frontier edges
 * where the empty slot must present pattern d on the relevant slot-edge.
 *
 * When we place slot s:
 *   - s moves from "empty" to "placed".
 *   - For each neighbour nb of s:
 *     If nb is empty: s now "faces" nb -- we ADD a demand for the pattern nb
 *       must present on its kb edge. That pattern = rev_dense[dpat s put on j].
 *       Pattern s put on slot-edge j = tile_dpat[t][(j+r)%3].
 *       Demand pattern for nb = rev_dense[tile_dpat[t][(j+r)%3]].
 *     If nb is placed: the demand that nb imposed on s (which s just satisfied)
 *       was already in demand[] -- we REMOVE it.
 */
static inline void demand_update_place(int s, int t, int r) {
    for (int j = 0; j < 3; j++) {
        int nb = g_adj[s][j].slot;
        int kb = g_adj[s][j].edge;
        int dpat_j = tile_dpat[t][(j + r) % 3];  /* dense pattern s puts on edge j */
        if (slot_tile[nb] < 0) {
            /* nb is empty: s now demands rev_dense[dpat_j] from nb on edge kb */
            /* The demand is for what nb must put on its edge kb */
            /* But our demand table tracks "what dense pattern must appear on
             * the EMPTY slot's edge to satisfy the placed neighbour".
             * That pattern = rev_dense[dpat_j] (what nb must present facing s). */
            int d_needed = rev_dense[dpat_j];
            demand[d_needed]++;
            if (!touched_flag[d_needed]) {
                touched_flag[d_needed] = 1;
                touched[n_touched++] = (uint8_t)d_needed;
            }
        } else {
            /* nb is placed: it had a demand for dpat_j from s -- remove it */
            /* The demand nb imposed was for rev of what nb put on edge kb,
             * i.e. rev_dense[tile_dpat[nb_tile][(kb + nb_rot)%3]]
             * = dpat_j (that's the match condition).
             * So demand[dpat_j] was incremented by nb. Now we remove it. */
            demand[dpat_j]--;
            if (!touched_flag[dpat_j]) {
                touched_flag[dpat_j] = 1;
                touched[n_touched++] = (uint8_t)dpat_j;
            }
            (void)kb; /* kb used only conceptually here */
        }
    }
}

/* Reverse of demand_update_place for unplace */
static inline void demand_update_unplace(int s, int t, int r) {
    for (int j = 0; j < 3; j++) {
        int nb = g_adj[s][j].slot;
        int kb = g_adj[s][j].edge;
        int dpat_j = tile_dpat[t][(j + r) % 3];
        if (slot_tile[nb] < 0) {
            /* nb is still empty: remove the demand s imposed */
            int d_needed = rev_dense[dpat_j];
            demand[d_needed]--;
        } else {
            /* nb is placed: restore the demand nb had for s */
            demand[dpat_j]++;
        }
        (void)kb;
    }
}

/* Check supply >= demand for all touched patterns. Returns 1 if feasible, 0 to prune. */
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
    /* Write fill_order slots up to depth */
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
    fprintf(stderr,
        "nodes=%" PRIu64 " depth=%d max_depth=%d sol=%" PRIu64 " nps=%.0f best=%d"
        " pfx=%s\n",
        stat_nodes, depth, stat_max_depth, stat_solutions, nps, stat_best_partial,
        pfx_str());
    fflush(stderr);
    t_last_stats = now;
}

/* ============================================================
 * Core DFS over the static fill order.
 *
 * depth = index into fill_order[]; we are about to fill fill_order[depth].
 * All slots fill_order[0..depth-1] are placed.
 * ============================================================ */
static void dfs(int depth, FILE *sol_file) {
    if (limit_hit) return;

    stat_nodes++;
    if ((stat_nodes & ((1u << 26) - 1)) == 0) print_stats(depth);
    {
        time_t now = time(NULL);
        if (difftime(now, t_last_stats) >= 10.0) print_stats(depth);
    }
    if (node_limit > 0 && stat_nodes >= node_limit) { limit_hit = 1; return; }

    if (depth > stat_max_depth) stat_max_depth = depth;
    if (depth > stat_best_partial) {
        stat_best_partial = depth;
        write_partial("best2_partial.txt", depth);
    }

    if (depth == N_SLOTS) {
        stat_solutions++;
        write_solution(sol_file);
        return;
    }

    FillPos *fp = &fill_order[depth];
    int s = fp->slot;
    int nc = fp->n_constrained;

    /* Determine required dense patterns for each constrained edge */
    uint8_t req_d[3];  /* req_d[c] = dense pattern required on slot-edge fp->con_j[c] */
    for (int c = 0; c < nc; c++) {
        int nb   = fp->con_nb[c];
        int kb   = fp->con_kb[c];
        int t_nb = (int)(uint8_t)slot_tile[nb];
        int r_nb = (int)(uint8_t)slot_rot[nb];
        int dpat = tile_dpat[t_nb][(kb + r_nb) % 3];  /* pattern nb puts on its edge kb */
        req_d[c] = rev_dense[dpat];                    /* what s must put on con_j[c] */
    }

    if (nc == 0) {
        /* Seed slot: iterate all (tile,rot) -- but we know it's the seed tile */
        /* Actually for the first slot we only try the seed tile per solver.c convention */
        /* But solver2 is called with the seed already placed externally -- see main(). */
        /* Should not reach here except if nc==0 for a non-seed internal slot. */
        /* If it somehow does, iterate all unused (tile,rot). */
        for (int t = 0; t < N_SLOTS; t++) {
            if (tile_used[t]) continue;
            for (int r = 0; r < 3; r++) {
                place(s, t, r);
                n_touched = 0;
                supply_remove(t);
                demand_update_place(s, t, r);
                if (supply_demand_ok()) {
                    clear_touched();
                    if (depth < 48) g_prefix[depth] = t*3+r;
                    dfs(depth + 1, sol_file);
                } else {
                    clear_touched();
                }
                demand_update_unplace(s, t, r);
                supply_restore(t);
                unplace(s);
                if (limit_hit) return;
            }
        }
        return;
    }

    if (nc == 1) {
        /* One constrained edge: use spd_list[req_d[0]][fp->con_j[0]] */
        int d0 = req_d[0];
        int j0 = fp->con_j[0];
        TRPack *lst = spd_list[d0][j0];
        int len = spd_count[d0][j0];

        for (int i = 0; i < len; i++) {
            TRPack tr = lst[i];
            int t = TR_TILE(tr);
            int r = TR_ROT(tr);
            if (tile_used[t]) continue;

            /* Verify the one constraint (should always pass by construction) */
            /* No explicit check needed: spd_list guarantees tile_dpat[t][(j0+r)%3] == d0 */

            place(s, t, r);
            n_touched = 0;
            supply_remove(t);
            demand_update_place(s, t, r);
            if (supply_demand_ok()) {
                clear_touched();
                if (depth < 48) g_prefix[depth] = i;
                dfs(depth + 1, sol_file);
            } else {
                clear_touched();
            }
            demand_update_unplace(s, t, r);
            supply_restore(t);
            unplace(s);
            if (limit_hit) return;
        }
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

            /* If nc == 3, verify the third constraint explicitly */
            if (nc == 3) {
                int j2 = fp->con_j[2];
                int d2 = req_d[2];
                if ((int)tile_dpat[t][(j2 + r) % 3] != d2) continue;
            }

            place(s, t, r);
            n_touched = 0;
            supply_remove(t);
            demand_update_place(s, t, r);
            if (supply_demand_ok()) {
                clear_touched();
                if (depth < 48) g_prefix[depth] = i;
                dfs(depth + 1, sol_file);
            } else {
                clear_touched();
            }
            demand_update_unplace(s, t, r);
            supply_restore(t);
            unplace(s);
            if (limit_hit) return;
        }
        return;
    }
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

    /* Initialise supply: all tiles unused, all their edges in supply */
    for (int t = 0; t < N_SLOTS; t++)
        for (int e = 0; e < 3; e++)
            supply[tile_dpat[t][e]]++;
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

    /* Build reverse table */
    for (int p = 0; p < MAX_PATTERNS; p++) rev_pat[p] = reverse11((uint16_t)p);

    /* Parse instance */
    if (!parse_instance(argv[1])) return 1;

    fprintf(stderr, "Diamond Dilemma Solver 2\n");
    fprintf(stderr, "  instance: %s\n", argv[1]);
    fprintf(stderr, "  seed tile: %d, seed slots: %d\n", seed_tile_id, n_seed_slots);
    fprintf(stderr, "  node_limit: %" PRIu64 ", rng_seed: %u\n", cli_node_limit, cli_seed);

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
    FILE *sol = fopen("solutions2.txt", "a");
    if (!sol) { fprintf(stderr, "Cannot open solutions2.txt\n"); return 1; }

    t_start = t_last_stats = time(NULL);
    stat_best_partial = 0;
    stat_max_depth    = 0;
    stat_nodes        = 0;
    stat_solutions    = 0;

    /* Outer loop: seed slot x rotation (symmetry breaking as in solver.c) */
    for (int si = 0; si < n_seed_slots && !limit_hit; si++) {
        int ss = seed_slots[si];

        /* Verify fill_order[0] is this seed slot */
        /* We built fill_order[0] = seed_slots[0]. If si > 0 we'd need to rebuild.
         * For simplicity and correctness, only loop si=0 (seed_slots[0]) per fill order.
         * Multiple seed slots are handled by re-running with a different fill order,
         * but the spec says seed tile 23 and 16 seed slots. The outer loop over
         * seed slots provides symmetry-breaking as in solver.c. We allow it by
         * rebuilding fill_order for each seed slot. */
        if (fill_order[0].slot != (uint8_t)ss) {
            /* Rebuild fill order with ss as starting slot */
            /* Save n_seed_slots and set seed_slots[0] = ss temporarily */
            int orig_ss0 = seed_slots[0];
            seed_slots[0] = ss;
            build_fill_order();
            build_pair_tables();
            if (cli_seed > 0) shuffle_all_tables(cli_seed);
            seed_slots[0] = orig_ss0;
        }

        for (int r = 0; r < 3 && !limit_hit; r++) {
            reset_board();

            /* Place seed tile at fill_order[0] = ss */
            int t_seed = seed_tile_id;
            place(ss, t_seed, r);

            /* Update supply/demand for seed placement */
            n_touched = 0;
            supply_remove(t_seed);
            demand_update_place(ss, t_seed, r);
            clear_touched();

            fprintf(stderr, "seed slot=%d tile=%d rot=%d\n", ss, seed_tile_id, r);

            /* DFS from depth=1 (depth 0 = ss is placed) */
            dfs(1, sol);

            /* Unplace seed */
            demand_update_unplace(ss, t_seed, r);
            supply_restore(t_seed);
            unplace(ss);
        }
    }

    print_stats(0);
    fprintf(stderr, "DONE. nodes=%" PRIu64 " solutions=%" PRIu64 "\n",
        stat_nodes, stat_solutions);
    fclose(sol);
    return 0;
}
