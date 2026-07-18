/*
 * solver.c -- Diamond Dilemma Gold: exhaustive DFS tile-placement solver.
 *
 * Compile: zig cc -O3 -o solver.exe solver.c
 * (C11, single file, no external dependencies beyond libc)
 *
 * Usage:
 *   solver.exe <instance_file>
 *   solver.exe <instance_file> resume
 *   solver.exe <instance_file> resume <node_limit>
 *   solver.exe <instance_file> "" <node_limit>
 *
 * ============================================================
 * INSTANCE FILE FORMAT (produced by gen_instance.py):
 *
 *   Line 1:    "160 240"           (n_slots n_edges)
 *   Lines 2..161:  for slot s (0..159):
 *                  "n0 k0 n1 k1 n2 k2"
 *                  n_j = neighbor slot for slot s's edge j
 *                  k_j = that neighbor's edge index
 *   Lines 162..321: for tile t (0..159):
 *                  "p0 p1 p2"  (three 11-char '0'/'1' strings)
 *   Line 322:   S  (number of seed slots)
 *   Line 323:   S slot indices (space-separated)
 *   Line 324:   seed tile id (0-indexed)
 * ============================================================
 *
 * CONVENTIONS:
 *   Placement: tile t with rotation r in slot s maps
 *              tile-edge (j + r) % 3  ->  slot-edge j,  for j = 0,1,2.
 *   Pattern encoding: 11-bit integer; bit i = character i of the string ('0'->0,'1'->1).
 *   Match condition: pattern on slot-edge j equals REVERSE (bit-flip) of pattern
 *                   on the facing neighbor's edge.
 *
 * SEARCH:
 *   Top level: for each seed slot (ascending), place seed tile in rotations 0..2.
 *   Recursion: MRV -- pick the frontier slot (empty, >=1 placed neighbor) with
 *              the fewest valid candidates; try each in ascending (tile,rot) order.
 *   Frontier is maintained incrementally via placed_neighbor_count[].
 *
 * CHECKPOINTING (every ~60 sec): write checkpoint.txt as
 *   <slot> <tile> <rot> <cand_ordinal>   (one line per decision)
 * Resume: replay decisions, skipping at the last level.
 *
 * OUTPUT:
 *   solutions_gold.txt  -- one line per solution: "s:t:r ..." (appended)
 *   best_partial.txt    -- best partial assignment (overwritten on improvement)
 *   checkpoint.txt      -- current stack (overwritten periodically)
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
#define MAX_TILE_CANDS 160    /* max entries per pattern in pat_list */
#define MAX_CANDS      512    /* scratch candidate array size */

/* ============================================================
 * Global board data (read-only after init)
 * ============================================================ */

/* Adjacency: g_adj[s][j] = (neighbor_slot, neighbor_edge) */
typedef struct { uint8_t slot; uint8_t edge; } Neighbor;
static Neighbor g_adj[N_SLOTS][3];

/* Tile patterns: tile_pat[t][e] = 11-bit integer */
static uint16_t tile_pat[N_SLOTS][3];

/* Reverse-pattern table: rev_pat[p] = bit-reverse of p over 11 bits */
static uint16_t rev_pat[MAX_PATTERNS];

/* Pattern index: pat_list[p] = list of (tile, edge) pairs having that pattern */
typedef struct { uint8_t tile; uint8_t edge; } PatEntry;
static PatEntry pat_list[MAX_PATTERNS][MAX_TILE_CANDS];
static int      pat_count[MAX_PATTERNS];

/* Seed configuration */
#define MAX_SEED_SLOTS N_SLOTS
static int seed_slots[MAX_SEED_SLOTS];
static int n_seed_slots = 0;
static int seed_tile_id = 23;

/* ============================================================
 * Search state (mutable during DFS)
 * ============================================================ */
static int8_t  slot_tile[N_SLOTS];            /* -1 = empty */
static int8_t  slot_rot[N_SLOTS];             /* -1 = empty */
static uint8_t tile_used[N_SLOTS];
static uint8_t placed_nbr_cnt[N_SLOTS];       /* # placed neighbors of slot s */
static uint8_t in_frontier[N_SLOTS];          /* 1 iff slot is empty & has placed neighbor */

/* Candidate scratch buffer (reused) */
typedef struct { uint8_t tile; uint8_t rot; } Cand;
static Cand cands[MAX_CANDS];

/* Decision stack (for checkpointing) */
typedef struct {
    uint8_t  slot;
    uint8_t  tile;
    uint8_t  rot;
    uint16_t ordinal;  /* 0-based index in sorted candidate list */
} Decision;
static Decision dstack[N_SLOTS];
static int      dstack_top = 0;

/* ============================================================
 * Statistics
 * ============================================================ */
static uint64_t stat_nodes     = 0;
static uint64_t stat_solutions = 0;
static int      stat_max_depth = 0;
static int      stat_best_partial = 0;
static time_t   t_start, t_last_stats, t_last_ckpt;
static uint64_t node_limit = 0;   /* 0 = unlimited */
static int      limit_hit  = 0;

/* ============================================================
 * Helpers
 * ============================================================ */

/* Reverse 11-bit pattern */
static uint16_t reverse11(uint16_t p) {
    uint16_t r = 0;
    for (int i = 0; i < PAT_LEN; i++)
        if (p & (1u << i)) r |= (1u << (PAT_LEN - 1 - i));
    return r;
}

/* Parse 11-char '0'/'1' string -> uint16_t (bit i = char i) */
static uint16_t parse_pat(const char *s) {
    uint16_t v = 0;
    for (int i = 0; i < PAT_LEN; i++)
        if (s[i] == '1') v |= (1u << i);
    return v;
}

/* ============================================================
 * Compute candidates for slot s.
 * Fills cands[0..n-1], returns n.
 * Candidates are (tile, rot) pairs consistent with all placed neighbors.
 * Result is unsorted; caller sorts if needed.
 * ============================================================ */
static int get_candidates(int s) {
    /* Gather required patterns from placed neighbors */
    uint16_t req[3];
    int      has[3] = {0, 0, 0};
    for (int j = 0; j < 3; j++) {
        int nb = g_adj[s][j].slot;
        int kb = g_adj[s][j].edge;
        if (slot_tile[nb] >= 0) {
            /* neighbor placed: it puts tile_pat[t_nb][(kb+r_nb)%3] on its edge kb */
            int t_nb = slot_tile[nb], r_nb = slot_rot[nb];
            uint16_t nb_pat = tile_pat[t_nb][(kb + r_nb) % 3];
            req[j] = rev_pat[nb_pat];  /* what slot s must put on edge j */
            has[j] = 1;
        }
    }

    /* Find a constrained edge to drive enumeration */
    int drive = -1;
    for (int j = 0; j < 3; j++) { if (has[j]) { drive = j; break; } }

    if (drive < 0) {
        /* No constraints (shouldn't happen in normal search after first placement) */
        int n = 0;
        for (int t = 0; t < N_SLOTS; t++) {
            if (tile_used[t]) continue;
            for (int r = 0; r < 3; r++) {
                cands[n].tile = (uint8_t)t;
                cands[n].rot  = (uint8_t)r;
                if (++n == MAX_CANDS) return n;
            }
        }
        return n;
    }

    /*
     * Drive enumeration via pat_list[req[drive]]:
     *   tile_pat[t][e] == req[drive]
     *   e maps to slot-edge drive via rotation r: slot-edge j = (tile-edge - r + 3*100) % 3
     *     tile-edge (j+r)%3 -> slot-edge j, so slot-edge drive <- tile-edge (drive+r)%3 = e
     *     => r = (e - drive + 3) % 3  ... wait:
     *     Placement: tile edge (j+r)%3 onto slot edge j.
     *     So slot edge j carries tile edge (j+r)%3.
     *     We need slot edge drive to carry the tile edge with pattern req[drive].
     *     That tile edge index is e = (drive + r) % 3.
     *     Given e, r = (e - drive + 3) % 3.
     */
    int p_idx = req[drive];
    int ne = pat_count[p_idx];
    int n = 0;
    for (int i = 0; i < ne; i++) {
        int t = pat_list[p_idx][i].tile;
        int e = pat_list[p_idx][i].edge;
        if (tile_used[t]) continue;
        int r = (e - drive + 3) % 3;
        /* Verify: slot edge drive <- tile edge e = (drive+r)%3 */
        /* And verify other constrained edges */
        int ok = 1;
        for (int j = 0; j < 3; j++) {
            if (!has[j]) continue;
            uint16_t got = tile_pat[t][(j + r) % 3];
            if (got != req[j]) { ok = 0; break; }
        }
        if (!ok) continue;
        cands[n].tile = (uint8_t)t;
        cands[n].rot  = (uint8_t)r;
        if (++n == MAX_CANDS) return n;
    }
    return n;
}

/* Sort cands[0..n-1] by (tile, rot) ascending (insertion sort; n is tiny) */
static void sort_cands(int n) {
    for (int i = 1; i < n; i++) {
        Cand key = cands[i];
        int kv = key.tile * 3 + key.rot;
        int j = i - 1;
        while (j >= 0 && cands[j].tile * 3 + cands[j].rot > kv) {
            cands[j+1] = cands[j]; j--;
        }
        cands[j+1] = key;
    }
}

/* ============================================================
 * Place / unplace tile (incremental frontier update)
 * ============================================================ */
static void place(int s, int t, int r) {
    slot_tile[s] = (int8_t)t;
    slot_rot[s]  = (int8_t)r;
    tile_used[t] = 1;
    in_frontier[s] = 0;
    for (int j = 0; j < 3; j++) {
        int nb = g_adj[s][j].slot;
        if (slot_tile[nb] < 0) {
            if (++placed_nbr_cnt[nb] == 1)
                in_frontier[nb] = 1;
        }
    }
}

static void unplace(int s) {
    int t = (int)(uint8_t)slot_tile[s];
    slot_tile[s] = -1;
    slot_rot[s]  = -1;
    tile_used[t] = 0;
    /* Recompute placed_nbr_cnt[s] */
    int cnt_s = 0;
    for (int j = 0; j < 3; j++)
        if (slot_tile[g_adj[s][j].slot] >= 0) cnt_s++;
    placed_nbr_cnt[s] = (uint8_t)cnt_s;
    in_frontier[s] = (cnt_s > 0) ? 1 : 0;
    /* Decrement placed_nbr_cnt for s's empty neighbors */
    for (int j = 0; j < 3; j++) {
        int nb = g_adj[s][j].slot;
        if (slot_tile[nb] < 0) {
            if (--placed_nbr_cnt[nb] == 0)
                in_frontier[nb] = 0;
        }
    }
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

static void write_partial(const char *fname) {
    FILE *f = fopen(fname, "w");
    if (!f) return;
    int first = 1;
    for (int s = 0; s < N_SLOTS; s++) {
        if (slot_tile[s] < 0) continue;
        if (!first) fputc(' ', f);
        fprintf(f, "%d:%d:%d", s, (int)(uint8_t)slot_tile[s], (int)(uint8_t)slot_rot[s]);
        first = 0;
    }
    fputc('\n', f);
    fclose(f);
}

static void write_checkpoint(void) {
    FILE *f = fopen("checkpoint.txt", "w");
    if (!f) return;
    for (int i = 0; i < dstack_top; i++)
        fprintf(f, "%d %d %d %d\n",
            dstack[i].slot, dstack[i].tile, dstack[i].rot, dstack[i].ordinal);
    fclose(f);
}

static void print_stats(int depth) {
    time_t now = time(NULL);
    double elapsed = difftime(now, t_start);
    double nps = (elapsed > 0) ? (double)stat_nodes / elapsed : 0.0;
    fprintf(stderr,
        "nodes=%" PRIu64 " depth=%d max_depth=%d sol=%" PRIu64 " nps=%.0f best=%d\n",
        stat_nodes, depth, stat_max_depth, stat_solutions, nps, stat_best_partial);
    fflush(stderr);
    t_last_stats = now;
}

/* ============================================================
 * MRV: find frontier slot with fewest candidates.
 * Returns slot index, or -1 if no frontier.
 * Sets *min_cnt to candidate count (0 = dead end).
 * When returning, cands[] holds the candidates for the chosen slot (sorted).
 * ============================================================ */
static int mrv_pick(int *min_cnt_out) {
    int best_s   = -1;
    int best_cnt = MAX_CANDS + 1;

    /* Scratch buffer for the winner's candidates */
    static Cand winner[MAX_CANDS];
    int winner_n = 0;

    for (int s = 0; s < N_SLOTS; s++) {
        if (!in_frontier[s]) continue;
        int n = get_candidates(s);
        if (n < best_cnt) {
            best_cnt = n;
            best_s   = s;
            winner_n = n;
            memcpy(winner, cands, n * sizeof(Cand));
        }
        if (best_cnt == 0) break;  /* dead end -- no need to look further */
    }

    if (best_s >= 0) {
        memcpy(cands, winner, winner_n * sizeof(Cand));
        sort_cands(winner_n);
    }
    *min_cnt_out = best_cnt;
    return best_s;
}

/* ============================================================
 * Core DFS (no resume logic -- called after resume phase ends)
 * depth = number of tiles already placed on entry
 * ============================================================ */
static void dfs(int depth, FILE *sol_file) {
    if (limit_hit) return;

    stat_nodes++;
    if ((stat_nodes & ((1u << 24) - 1)) == 0) print_stats(depth);
    {
        time_t now = time(NULL);
        if (difftime(now, t_last_stats) >= 10.0) print_stats(depth);
        if (difftime(now, t_last_ckpt)  >= 60.0) { write_checkpoint(); t_last_ckpt = now; }
    }
    if (node_limit > 0 && stat_nodes >= node_limit) { limit_hit = 1; return; }

    if (depth > stat_max_depth) stat_max_depth = depth;
    if (depth > stat_best_partial) {
        stat_best_partial = depth;
        write_partial("best_partial.txt");
    }

    if (depth == N_SLOTS) {
        stat_solutions++;
        write_solution(sol_file);
        return;
    }

    int n_cands;
    int s = mrv_pick(&n_cands);
    if (s < 0 || n_cands == 0) return;

    /* cands[0..n_cands-1] are sorted by (tile,rot) */
    for (int ci = 0; ci < n_cands; ci++) {
        int t = cands[ci].tile;
        int r = cands[ci].rot;

        dstack[dstack_top].slot    = (uint8_t)s;
        dstack[dstack_top].tile    = (uint8_t)t;
        dstack[dstack_top].rot     = (uint8_t)r;
        dstack[dstack_top].ordinal = (uint16_t)ci;
        dstack_top++;

        place(s, t, r);
        dfs(depth + 1, sol_file);
        unplace(s);

        dstack_top--;
        if (limit_hit) return;

        /* Re-derive candidates for slot s (it's empty again, frontier restored) */
        /* But mrv_pick chose a NEW slot next call -- we just need to continue iterating */
        /* However, the cands[] array was overwritten by recursive calls.
         * We need to re-derive for the current slot s at this level. */
        /* Re-derive only if we need to continue (ci+1 < n_cands) */
        if (ci + 1 < n_cands) {
            /* Re-derive candidates for slot s to get the same sorted list */
            int nn = get_candidates(s);
            sort_cands(nn);
            /* nn should equal n_cands (same constraints, same tile availability
             * restored by unplace). If not, something is wrong -- but let's be safe. */
            n_cands = nn;
        }
    }
}

/* ============================================================
 * Resume-aware DFS.
 *
 * resume_stack[0..resume_len-1]: decisions to replay.
 * resume_len: total length of the checkpoint stack.
 * resume_pos: how far we've consumed so far in this call chain.
 *
 * Strategy:
 *   - For levels 0 .. resume_len-2: force the exact slot/tile/rot from checkpoint,
 *     recurse, then after returning from that subtree, continue with the
 *     remaining candidates for that slot (those beyond the checkpoint ordinal).
 *   - For level resume_len-1: skip candidates 0..ordinal-1, then try ordinal..end
 *     using normal dfs() for the subtree.
 *
 * We implement this iteratively using the call stack by passing resume_pos.
 * ============================================================ */
typedef struct { int slot; int tile; int rot; int ordinal; } REntry;
static REntry   rstack[N_SLOTS];
static int      rstack_len = 0;

/* dfs_resume is called with the current resume position.
 * depth = tiles placed so far. */
static void dfs_resume(int depth, int rpos, FILE *sol_file) {
    if (limit_hit) return;
    stat_nodes++;
    if ((stat_nodes & ((1u << 24) - 1)) == 0) print_stats(depth);
    {
        time_t now = time(NULL);
        if (difftime(now, t_last_stats) >= 10.0) print_stats(depth);
        if (difftime(now, t_last_ckpt)  >= 60.0) { write_checkpoint(); t_last_ckpt = now; }
    }
    if (node_limit > 0 && stat_nodes >= node_limit) { limit_hit = 1; return; }
    if (depth > stat_max_depth) stat_max_depth = depth;
    if (depth > stat_best_partial) {
        stat_best_partial = depth;
        write_partial("best_partial.txt");
    }
    if (depth == N_SLOTS) {
        stat_solutions++;
        write_solution(sol_file);
        return;
    }

    if (rpos < rstack_len) {
        /* Still replaying checkpoint */
        int forced_s  = rstack[rpos].slot;
        int forced_t  = rstack[rpos].tile;
        int forced_r  = rstack[rpos].rot;
        int forced_co = rstack[rpos].ordinal;

        /* Derive sorted candidate list for forced_s */
        int nc = get_candidates(forced_s);
        sort_cands(nc);

        if (rpos == rstack_len - 1) {
            /* Last checkpoint level: skip 0..forced_co-1, try forced_co..nc-1 */
            for (int ci = forced_co; ci < nc; ci++) {
                int t = cands[ci].tile;
                int r = cands[ci].rot;

                dstack[dstack_top].slot    = (uint8_t)forced_s;
                dstack[dstack_top].tile    = (uint8_t)t;
                dstack[dstack_top].rot     = (uint8_t)r;
                dstack[dstack_top].ordinal = (uint16_t)ci;
                dstack_top++;

                place(forced_s, t, r);
                /* Resume phase ends: use normal dfs */
                dfs(depth + 1, sol_file);
                unplace(forced_s);

                dstack_top--;
                if (limit_hit) return;

                /* Re-derive for next iteration */
                if (ci + 1 < nc) {
                    nc = get_candidates(forced_s);
                    sort_cands(nc);
                }
            }
        } else {
            /* Not last level: find the forced (tile,rot) in the candidate list */
            int target_ci = -1;
            for (int ci = 0; ci < nc; ci++) {
                if (cands[ci].tile == (uint8_t)forced_t &&
                    cands[ci].rot  == (uint8_t)forced_r) {
                    target_ci = ci; break;
                }
            }
            if (target_ci < 0) {
                fprintf(stderr,
                    "Resume error at depth %d rpos %d: tile %d rot %d not a candidate for slot %d\n",
                    depth, rpos, forced_t, forced_r, forced_s);
                fprintf(stderr, "Falling back to normal search from here.\n");
                /* Fall back: use normal dfs from this point */
                /* But first we need to pick with MRV */
                int n_c2;
                int s2 = mrv_pick(&n_c2);
                if (s2 < 0 || n_c2 == 0) return;
                for (int ci = 0; ci < n_c2; ci++) {
                    int t2 = cands[ci].tile, r2 = cands[ci].rot;
                    dstack[dstack_top].slot    = (uint8_t)s2;
                    dstack[dstack_top].tile    = (uint8_t)t2;
                    dstack[dstack_top].rot     = (uint8_t)r2;
                    dstack[dstack_top].ordinal = (uint16_t)ci;
                    dstack_top++;
                    place(s2, t2, r2);
                    dfs(depth + 1, sol_file);
                    unplace(s2);
                    dstack_top--;
                    if (limit_hit) return;
                    if (ci + 1 < n_c2) { n_c2 = get_candidates(s2); sort_cands(n_c2); }
                }
                return;
            }

            /* Enter the forced branch */
            dstack[dstack_top].slot    = (uint8_t)forced_s;
            dstack[dstack_top].tile    = (uint8_t)forced_t;
            dstack[dstack_top].rot     = (uint8_t)forced_r;
            dstack[dstack_top].ordinal = (uint16_t)target_ci;
            dstack_top++;

            place(forced_s, forced_t, forced_r);
            dfs_resume(depth + 1, rpos + 1, sol_file);
            unplace(forced_s);

            dstack_top--;
            if (limit_hit) return;

            /* After the forced subtree, try candidates AFTER target_ci (unexplored) */
            nc = get_candidates(forced_s);
            sort_cands(nc);
            for (int ci = target_ci + 1; ci < nc; ci++) {
                int t = cands[ci].tile, r = cands[ci].rot;
                dstack[dstack_top].slot    = (uint8_t)forced_s;
                dstack[dstack_top].tile    = (uint8_t)t;
                dstack[dstack_top].rot     = (uint8_t)r;
                dstack[dstack_top].ordinal = (uint16_t)ci;
                dstack_top++;
                place(forced_s, t, r);
                dfs(depth + 1, sol_file);
                unplace(forced_s);
                dstack_top--;
                if (limit_hit) return;
                if (ci + 1 < nc) { nc = get_candidates(forced_s); sort_cands(nc); }
            }
        }
    } else {
        /* Past end of checkpoint: normal MRV search */
        int n_c;
        int s = mrv_pick(&n_c);
        if (s < 0 || n_c == 0) return;
        for (int ci = 0; ci < n_c; ci++) {
            int t = cands[ci].tile, r = cands[ci].rot;
            dstack[dstack_top].slot    = (uint8_t)s;
            dstack[dstack_top].tile    = (uint8_t)t;
            dstack[dstack_top].rot     = (uint8_t)r;
            dstack[dstack_top].ordinal = (uint16_t)ci;
            dstack_top++;
            place(s, t, r);
            dfs_resume(depth + 1, rpos, sol_file);
            unplace(s);
            dstack_top--;
            if (limit_hit) return;
            if (ci + 1 < n_c) { n_c = get_candidates(s); sort_cands(n_c); }
        }
    }
}

/* ============================================================
 * Parse instance file
 * ============================================================ */
static int parse_instance(const char *fname) {
    FILE *f = fopen(fname, "r");
    if (!f) { fprintf(stderr, "Cannot open '%s'\n", fname); return 0; }

    int ns, ne;
    if (fscanf(f, "%d %d", &ns, &ne) != 2 || ns != N_SLOTS || ne != N_EDGES) {
        fprintf(stderr, "Bad header (expected %d %d)\n", N_SLOTS, N_EDGES);
        fclose(f); return 0;
    }

    /* Adjacency */
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

    /* Tiles */
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

    /* Seed slots */
    if (fscanf(f, "%d", &n_seed_slots) != 1) {
        fprintf(stderr, "Bad seed slot count\n"); fclose(f); return 0;
    }
    for (int i = 0; i < n_seed_slots; i++) {
        if (fscanf(f, "%d", &seed_slots[i]) != 1) {
            fprintf(stderr, "Bad seed slot[%d]\n", i); fclose(f); return 0;
        }
    }

    /* Seed tile */
    if (fscanf(f, "%d", &seed_tile_id) != 1) {
        fprintf(stderr, "Bad seed tile\n"); fclose(f); return 0;
    }

    fclose(f);
    return 1;
}

/* ============================================================
 * Load checkpoint into rstack[]
 * ============================================================ */
static int load_checkpoint(void) {
    FILE *f = fopen("checkpoint.txt", "r");
    if (!f) { fprintf(stderr, "No checkpoint.txt found.\n"); return 0; }
    rstack_len = 0;
    while (rstack_len < N_SLOTS) {
        int s, t, r, co;
        if (fscanf(f, "%d %d %d %d", &s, &t, &r, &co) != 4) break;
        rstack[rstack_len].slot    = s;
        rstack[rstack_len].tile    = t;
        rstack[rstack_len].rot     = r;
        rstack[rstack_len].ordinal = co;
        rstack_len++;
    }
    fclose(f);
    if (rstack_len == 0) { fprintf(stderr, "Empty checkpoint.\n"); return 0; }
    fprintf(stderr, "Loaded checkpoint: %d entries.\n", rstack_len);
    return 1;
}

/* ============================================================
 * Reset board state
 * ============================================================ */
static void reset_board(void) {
    memset(slot_tile,     -1, sizeof(slot_tile));
    memset(slot_rot,      -1, sizeof(slot_rot));
    memset(tile_used,      0, sizeof(tile_used));
    memset(placed_nbr_cnt, 0, sizeof(placed_nbr_cnt));
    memset(in_frontier,    0, sizeof(in_frontier));
    dstack_top = 0;
}

/* ============================================================
 * Main
 * ============================================================ */
int main(int argc, char *argv[]) {
    if (argc < 2) {
        fprintf(stderr, "Usage: %s <instance> [resume] [node_limit]\n", argv[0]);
        return 1;
    }

    int do_resume = 0;
    if (argc >= 3 && strcmp(argv[2], "resume") == 0) do_resume = 1;
    if (argc >= 4 && argv[3][0] != '\0') node_limit = (uint64_t)strtoull(argv[3], NULL, 10);

    /* Parse instance */
    if (!parse_instance(argv[1])) return 1;

    /* Build reverse table */
    for (int p = 0; p < MAX_PATTERNS; p++) rev_pat[p] = reverse11((uint16_t)p);

    /* Build pattern index */
    memset(pat_count, 0, sizeof(pat_count));
    for (int t = 0; t < N_SLOTS; t++) {
        for (int e = 0; e < 3; e++) {
            int p = tile_pat[t][e];
            if (pat_count[p] < MAX_TILE_CANDS) {
                pat_list[p][pat_count[p]].tile = (uint8_t)t;
                pat_list[p][pat_count[p]].edge = (uint8_t)e;
                pat_count[p]++;
            }
        }
    }

    /* Open solution file (append) */
    FILE *sol = fopen("solutions_gold.txt", "a");
    if (!sol) { fprintf(stderr, "Cannot open solutions_gold.txt\n"); return 1; }

    t_start = t_last_stats = t_last_ckpt = time(NULL);

    fprintf(stderr, "Diamond Dilemma Solver\n");
    fprintf(stderr, "  instance: %s\n", argv[1]);
    fprintf(stderr, "  seed tile: %d, seed slots: %d\n", seed_tile_id, n_seed_slots);
    fprintf(stderr, "  resume: %s, node_limit: %" PRIu64 "\n",
        do_resume ? "yes" : "no", node_limit);

    /* Sort seed slots ascending (for determinism) */
    for (int i = 0; i < n_seed_slots - 1; i++)
        for (int j = i+1; j < n_seed_slots; j++)
            if (seed_slots[j] < seed_slots[i]) {
                int tmp = seed_slots[i]; seed_slots[i] = seed_slots[j]; seed_slots[j] = tmp;
            }

    if (do_resume && load_checkpoint()) {
        /* Resume: the checkpoint's first entry is the top-level seed placement.
         * We replay the full checkpoint via dfs_resume starting from an empty board. */
        reset_board();
        dfs_resume(0, 0, sol);
    } else {
        /* Fresh search: iterate seed slots x rotations (breaks order-10 symmetry) */
        for (int si = 0; si < n_seed_slots && !limit_hit; si++) {
            int ss = seed_slots[si];
            for (int r = 0; r < 3 && !limit_hit; r++) {
                reset_board();

                /* Record top-level decision */
                dstack[0].slot    = (uint8_t)ss;
                dstack[0].tile    = (uint8_t)seed_tile_id;
                dstack[0].rot     = (uint8_t)r;
                dstack[0].ordinal = (uint16_t)r;  /* ordinal = rotation index at top level */
                dstack_top = 1;

                place(ss, seed_tile_id, r);
                fprintf(stderr, "seed slot=%d tile=%d rot=%d\n", ss, seed_tile_id, r);
                dfs(1, sol);
                unplace(ss);
                dstack_top = 0;
            }
        }
    }

    print_stats(0);

    /* Write final status to checkpoint */
    {
        FILE *f = fopen("checkpoint.txt", "w");
        if (f) {
            fprintf(f, "DONE nodes=%" PRIu64 " solutions=%" PRIu64 "\n",
                stat_nodes, stat_solutions);
            fclose(f);
        }
    }

    fprintf(stderr, "DONE. nodes=%" PRIu64 " solutions=%" PRIu64 "\n",
        stat_nodes, stat_solutions);
    fclose(sol);
    return 0;
}
