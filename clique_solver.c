/*
 * clique_solver.c -- Diamond Dilemma: max-clique-style branch-and-bound for
 * the MAXIMUM PARTIAL edge-matching (Eternity-II "max-clique" technique,
 * ported to a direct constraint-graph formulation).
 *
 * FORMULATION (see task spec):
 *   Graph node p = (tile t, slot s, rot r).  Two nodes p1=(t1,s1,r1),
 *   p2=(t2,s2,r2) are COMPATIBLE iff t1!=t2, s1!=s2, and for every board
 *   edge directly joining s1 and s2 the facing patterns match (revid[.]==.).
 *   If s1,s2 are not board-adjacent they are always compatible.
 *   A CLIQUE in this graph = an assignment slot->(tile,rot) over a SUBSET
 *   of slots using distinct tiles such that every adjacent pair of placed
 *   slots matches on their shared edge(s).  This is exactly a valid partial
 *   solution.  We search for the largest such clique (goal: 160 = full
 *   solution) with anytime branch-and-bound, NOT by materializing the graph
 *   (160*160*3 nodes -- too large), but by testing compatibility implicitly
 *   via the O(3) neighbor check against already-placed slots, indexed by a
 *   pattern -> (tile,edge) table for O(candidates) enumeration.
 *
 * Instance format (identical to solver_mc.c, see its header comment):
 *   line1: "N E"
 *   N lines: "n0 k0 n1 k1 n2 k2"  (neighbor slot + neighbor edge per slot edge)
 *   N lines: three 11-bit pattern strings (tile edge patterns)
 *   then seed lines (ignored here)
 *
 * CONVENTIONS (must match solver_mc.c / solver2.c exactly):
 *   Placement: tile t, rotation r, in slot s maps tile-edge (j+r)%3 to
 *   slot-edge j.  Two facing slot-edges match iff revid[patA]==patB.
 *
 * Build:  zig cc -O3 -o clique_solver.exe clique_solver.c
 * Usage:  clique_solver.exe <instance.txt> <seconds> <seed>
 *
 * Env:
 *   CLIQUE_WARM=<file>   partial-solution file ("slot:tile:rot " lines) used
 *                        to (a) seed best_count as a floor for pruning, and
 *                        (b) seed the very first dive (placements are
 *                        replayed in file order; any that no longer fit --
 *                        should not happen for a valid file -- are skipped).
 *
 * Output: clique_best.txt, rewritten ("slot:tile:rot " one line) every time
 *         best_count improves; each write is preceded by an internal
 *         self-check (verify_assignment) that re-derives validity from
 *         scratch, so a written file is guaranteed to be a legal partial
 *         matching (distinct tiles, distinct slots, every adjacent placed
 *         pair matches).
 *
 * Progress: "best=k/160 nodes=... t=..." on stderr whenever best improves,
 *           plus periodic heartbeat lines.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <math.h>

#define MAXN   160
#define MAXE   240
#define MAXPAT 2048

/* ---------------- instance data (read-only after load) ---------------- */
static int N, E;
static int nb_slot[MAXN][3], nb_edge[MAXN][3];
static int tilepat[MAXN][3];        /* pattern id of tile t, edge e (0..2) */
static int revid[MAXPAT];           /* reverse pattern id, or -1 */

/* pattern table (same linear-scan intern approach as solver_mc.c) */
static char pats[MAXPAT][12];
static int npat = 0;
static int pat_id(const char *s) {
    for (int i = 0; i < npat; i++) if (!strncmp(pats[i], s, 11)) return i;
    strncpy(pats[npat], s, 11); pats[npat][11] = 0;
    return npat++;
}
static void rev_str(const char *s, char *o) { for (int i = 0; i < 11; i++) o[i] = s[10 - i]; o[11] = 0; }

/* pattern -> occurrence list of (tile<<2|edge) */
static int *pat_list[MAXPAT];
static int pat_cnt[MAXPAT];

/* RNG: xorshift64, same style as solver_mc.c */
static unsigned long rngs;
static inline unsigned long xr(){ rngs^=rngs<<13; rngs^=rngs>>7; rngs^=rngs<<17; return rngs; }
static inline int ri(int m){ return (int)(xr()%(unsigned)m); }

/* ---------------- search state ---------------- */
/* Current partial assignment. */
static int cur_tile[MAXN];   /* tile placed in slot s, or -1 if empty */
static int cur_rot[MAXN];    /* rotation of tile in slot s (valid iff cur_tile[s]>=0) */
static int tile_used[MAXN];  /* -1 if free, else the slot the tile occupies */
static int cur_count = 0;    /* number of currently placed slots */

/* Best-so-far (anytime). */
static int best_tile[MAXN], best_rot[MAXN];
static int best_count = 0;

/* Slot fill order candidate bookkeeping: for MRV we just rescan empty slots
 * each branch step (N<=160, cheap relative to node cost) rather than
 * maintaining a priority structure. */

static long long nodes = 0;
static time_t t_start;
static double budget_secs;
static volatile int time_up = 0;

static inline double elapsed_secs(void){ return difftime(time(0), t_start); }

/* Check whether tile t at slot s with rotation r is legal against the
 * CURRENTLY PLACED neighbors of s only (tile-used / slot-used checked by
 * caller).  O(3). */
static inline int legal_place(int s, int t, int r) {
    for (int j = 0; j < 3; j++) {
        int b = nb_slot[s][j], k = nb_edge[s][j];
        if (b == s) {
            /* self-adjacent edge (slot borders itself on another of its
             * own edges) -- must be checked against this same tile/rot. */
            int pa = tilepat[t][(j + r) % 3];
            int pb = tilepat[t][(k + r) % 3];
            if (revid[pa] != pb) return 0;
            continue;
        }
        if (cur_tile[b] < 0) continue;           /* neighbor empty: always compatible */
        int pa = tilepat[t][(j + r) % 3];
        int pb = tilepat[cur_tile[b]][(k + cur_rot[b]) % 3];
        if (revid[pa] != pb) return 0;
    }
    return 1;
}

/* Re-verify a full (or partial) proposed assignment completely from
 * scratch: distinct tiles across placed slots, and every board edge whose
 * BOTH endpoints are placed must match.  Returns 1 if OK, 0 if not. Used as
 * an internal self-check before writing best. */
static int verify_assignment(int *tl, int *rt) {
    static int seen[MAXN];
    for (int i = 0; i < N; i++) seen[i] = -1;
    for (int s = 0; s < N; s++) {
        int t = tl[s];
        if (t < 0) continue;
        if (t < 0 || t >= N) return 0;
        if (seen[t] != -1) return 0; /* tile used twice */
        seen[t] = s;
        int r = rt[s];
        if (r < 0 || r > 2) return 0;
    }
    for (int s = 0; s < N; s++) {
        if (tl[s] < 0) continue;
        for (int j = 0; j < 3; j++) {
            int b = nb_slot[s][j], k = nb_edge[s][j];
            if (tl[b] < 0) continue;
            /* avoid double-reporting; matching is symmetric so checking
             * both directions is harmless (just redundant) */
            int pa = tilepat[tl[s]][(j + rt[s]) % 3];
            int pb = tilepat[tl[b]][(k + rt[b]) % 3];
            if (revid[pa] != pb) return 0;
        }
    }
    return 1;
}

static int count_placed(int *tl) {
    int c = 0;
    for (int s = 0; s < N; s++) if (tl[s] >= 0) c++;
    return c;
}

static void write_best(const char *outf) {
    if (!verify_assignment(best_tile, best_rot)) {
        fprintf(stderr, "INTERNAL ERROR: best assignment failed self-check! NOT WRITTEN.\n");
        return;
    }
    FILE *o = fopen(outf, "w");
    if (!o) { fprintf(stderr, "warn: could not open %s for writing\n", outf); return; }
    for (int s = 0; s < N; s++) {
        if (best_tile[s] >= 0) fprintf(o, "%d:%d:%d ", s, best_tile[s], best_rot[s]);
    }
    fprintf(o, "\n");
    fclose(o);
}

/* Save current partial into best if it improves; self-checked. */
static void maybe_improve(const char *outf) {
    if (cur_count > best_count) {
        best_count = cur_count;
        for (int s = 0; s < N; s++) { best_tile[s] = cur_tile[s]; best_rot[s] = cur_rot[s]; }
        write_best(outf);
        fprintf(stderr, "best=%d/%d nodes=%lld t=%.0f\n", best_count, N, nodes, elapsed_secs());
    }
}

/* ---------------- candidate enumeration for one empty slot ----------------
 * Returns number of legal (tile,rot) candidates for slot s given the
 * CURRENT partial assignment, writing up to cap of them into out (each
 * entry packed as tile*3+rot for compactness), stopping early once
 * `stop_after_found` legal ones are found if >0 (used for a cheap
 * "has-at-least-one-candidate" bound test without full enumeration). If
 * `out` is NULL, only counts (up to cap, or all if cap<=0), useful for MRV
 * scoring; pass cap=2 to just distinguish 0/1/many cheaply is NOT used here
 * since we need exact bound too -- caller decides cap. */
static int enum_candidates(int s, int *out, int cap) {
    /* Find a constraining neighbor (already placed) to narrow the search via
     * the pattern index; if none, we must scan all free tiles x 3 rots. */
    int constraining_j = -1, bs = -1, bk = -1;
    for (int j = 0; j < 3; j++) {
        int b = nb_slot[s][j];
        if (b != s && cur_tile[b] >= 0) { constraining_j = j; bs = b; bk = nb_edge[s][j]; break; }
    }
    int n = 0;
    if (constraining_j >= 0) {
        int pb = tilepat[cur_tile[bs]][(bk + cur_rot[bs]) % 3];
        int want = revid[pb];
        if (want >= 0) {
            int cnt = pat_cnt[want];
            int *lst = pat_list[want];
            for (int i = 0; i < cnt; i++) {
                int t = lst[i] >> 2, e = lst[i] & 3;
                if (tile_used[t] >= 0) continue;
                int r = ((e - constraining_j) % 3 + 3) % 3;
                if (!legal_place(s, t, r)) continue; /* checks remaining neighbors + self-loop edges */
                if (out) { if (cap > 0 && n >= cap) break; out[n] = t * 3 + r; }
                n++;
                if (cap > 0 && !out && n >= cap) break; /* count-only early stop */
            }
        }
        return n;
    }
    /* No placed neighbor constrains s (all neighbors empty, or self-only):
     * scan every unused tile x 3 rotations directly (cap this to avoid
     * O(160*3) blowing up too often -- only happens for isolated / early
     * placements, still fine at N<=160). */
    for (int t = 0; t < N; t++) {
        if (tile_used[t] >= 0) continue;
        for (int r = 0; r < 3; r++) {
            if (!legal_place(s, t, r)) continue;
            if (out) { if (cap > 0 && n >= cap) return n; out[n] = t * 3 + r; }
            n++;
            if (cap > 0 && !out && n >= cap) return n;
        }
    }
    return n;
}

/* ---------------- upper bound for pruning ----------------
 * placed + (number of still-empty slots that currently have >=1 legal
 * candidate).  This dominates the trivial "placed + empty_slots" bound
 * whenever some empty slot is already dead (0 candidates), which happens
 * often once a partial gets dense. Cost: O(empty_slots) candidate-existence
 * probes, each O(few) via the pattern index (cap=1 early-exit count). */
static int upper_bound(void) {
    int ub = cur_count;
    for (int s = 0; s < N; s++) {
        if (cur_tile[s] >= 0) continue;
        int n = enum_candidates(s, NULL, 1); /* cap=1: just need existence */
        if (n > 0) ub++;
    }
    return ub;
}

/* Pick the most-constrained empty slot (fewest legal candidates, MRV).
 * Returns -1 if no empty slot remains. On return, *out_cand_cnt holds the
 * candidate count found for that slot and out_cands (size >= out_cand_cnt,
 * capped at MAXCAND) holds the packed (tile*3+rot) list -- reused directly
 * for branching, avoiding a second enumeration pass. */
#define MAXCAND (MAXN*3)
static int pick_mrv_slot(int *out_cands, int *out_cand_cnt) {
    int best_s = -1, best_n = 1 << 30;
    static int scratch[MAXCAND];
    int best_cache_cnt = 0;
    static int best_cache[MAXCAND];
    for (int s = 0; s < N; s++) {
        if (cur_tile[s] >= 0) continue;
        int n = enum_candidates(s, scratch, MAXCAND);
        if (n == 0) { *out_cand_cnt = 0; return s; } /* dead slot: report immediately, caller prunes */
        if (n < best_n) {
            best_n = n; best_s = s;
            best_cache_cnt = n;
            memcpy(best_cache, scratch, sizeof(int) * n);
            if (best_n == 1) break; /* can't do better than 1 */
        }
    }
    if (best_s < 0) { *out_cand_cnt = 0; return -1; }
    memcpy(out_cands, best_cache, sizeof(int) * best_cache_cnt);
    *out_cand_cnt = best_cache_cnt;
    return best_s;
}

static void place(int s, int t, int r) {
    cur_tile[s] = t; cur_rot[s] = r; tile_used[t] = s; cur_count++;
}
static void unplace(int s) {
    int t = cur_tile[s];
    cur_tile[s] = -1; tile_used[t] = -1; cur_count--;
}

static const char *g_outf;
static long long g_check_interval_mask = 0xFFF; /* check clock every 4096 nodes */

/* Depth-first branch and bound over the MRV slot at each step. Order of
 * candidates within a slot is shuffled by seed for restart diversification. */
static void dfs(void) {
    if (time_up) return;
    nodes++;
    if ((nodes & g_check_interval_mask) == 0) {
        if (elapsed_secs() >= budget_secs) { time_up = 1; return; }
    }

    if (cur_count >= best_count) maybe_improve(g_outf); /* '>' would miss ties at 160 already reflected; use maybe_improve's own > check */

    if (cur_count == N) return; /* full clique (160) -- nothing more to place */

    /* bound check: best possible from here */
    int ub = upper_bound();
    if (ub <= best_count) return; /* cannot beat current best; prune */

    int cands[MAXCAND], ncand;
    int s = pick_mrv_slot(cands, &ncand);
    if (s < 0) return; /* no empty slots (shouldn't happen since cur_count<N) */
    if (ncand == 0) return; /* dead slot: this branch cannot extend further */

    /* shuffle candidate order for diversification across seeds/restarts */
    for (int i = ncand - 1; i > 0; i--) {
        int j = ri(i + 1);
        int tmp = cands[i]; cands[i] = cands[j]; cands[j] = tmp;
    }

    for (int ci = 0; ci < ncand; ci++) {
        if (time_up) return;
        int t = cands[ci] / 3, r = cands[ci] % 3;
        if (tile_used[t] >= 0) continue; /* safety (shouldn't trigger; enum already filtered) */
        /* re-validate placement against current state: enum_candidates was
         * computed before any sibling placements at this level, and siblings
         * only ever unplace() before trying the next, so state here is
         * identical to when candidates were enumerated -- legal_place holds.
         * Kept as defense-in-depth (cheap, O(3)). */
        if (!legal_place(s, t, r)) continue;
        place(s, t, r);
        dfs();
        unplace(s);
        if (time_up) return;
    }
}

/* ---------------- warm start ---------------- */
/* Parse a "slot:tile:rot " file into arrays; returns count of entries
 * parsed (not necessarily placed -- caller applies with legality checks). */
static int load_warm(const char *path, int *w_tile, int *w_rot) {
    for (int i = 0; i < N; i++) w_tile[i] = -1;
    FILE *f = fopen(path, "r");
    if (!f) { fprintf(stderr, "CLIQUE_WARM: could not open %s\n", path); return 0; }
    int s, t, r, cnt = 0;
    while (fscanf(f, "%d:%d:%d", &s, &t, &r) == 3) {
        if (s >= 0 && s < N && t >= 0 && t < N && r >= 0 && r <= 2) {
            w_tile[s] = t; w_rot[s] = r; cnt++;
        }
    }
    fclose(f);
    return cnt;
}

int main(int argc, char **argv) {
    if (argc < 4) { fprintf(stderr, "usage: clique_solver instance seconds seed\n"); return 2; }
    const char *inst = argv[1];
    budget_secs = atof(argv[2]);
    unsigned long seed = strtoul(argv[3], NULL, 10);
    rngs = seed * 2654435761UL + 1;
    if (rngs == 0) rngs = 88172645463325252UL;
    g_outf = "clique_best.txt";

    FILE *f = fopen(inst, "r");
    if (!f) { perror("open"); return 2; }
    if (fscanf(f, "%d %d", &N, &E) != 2) { fprintf(stderr, "bad instance header\n"); return 2; }
    for (int s = 0; s < N; s++)
        for (int j = 0; j < 3; j++)
            fscanf(f, "%d %d", &nb_slot[s][j], &nb_edge[s][j]);
    char a[16], b2[16], c[16];
    for (int t = 0; t < N; t++) {
        fscanf(f, "%s %s %s", a, b2, c);
        tilepat[t][0] = pat_id(a); tilepat[t][1] = pat_id(b2); tilepat[t][2] = pat_id(c);
    }
    fclose(f);

    /* reverse pattern ids */
    for (int i = 0; i < npat; i++) {
        char r[12]; rev_str(pats[i], r); revid[i] = -1;
        for (int j = 0; j < npat; j++) if (!strncmp(pats[j], r, 11)) { revid[i] = j; break; }
    }

    /* pattern occurrence index (pattern -> list of tile<<2|edge) */
    for (int p = 0; p < npat; p++) pat_cnt[p] = 0;
    for (int t = 0; t < N; t++) for (int e = 0; e < 3; e++) pat_cnt[tilepat[t][e]]++;
    for (int p = 0; p < npat; p++) pat_list[p] = malloc(sizeof(int) * (pat_cnt[p] > 0 ? pat_cnt[p] : 1));
    { int tmp[MAXPAT]; for (int p = 0; p < npat; p++) tmp[p] = 0;
      for (int t = 0; t < N; t++) for (int e = 0; e < 3; e++) { int p = tilepat[t][e]; pat_list[p][tmp[p]++] = (t << 2) | e; } }

    for (int s = 0; s < N; s++) { cur_tile[s] = -1; cur_rot[s] = 0; }
    for (int t = 0; t < N; t++) tile_used[t] = -1;
    cur_count = 0;
    best_count = 0;
    for (int s = 0; s < N; s++) { best_tile[s] = -1; best_rot[s] = -1; }

    t_start = time(0);

    /* ---- warm start ---- */
    const char *warm_path = getenv("CLIQUE_WARM");
    if (warm_path) {
        int w_tile[MAXN], w_rot[MAXN];
        int parsed = load_warm(warm_path, w_tile, w_rot);
        if (parsed > 0) {
            /* First: establish best_count as a floor by validating the warm
             * file wholesale (self-checked) so pruning benefits immediately
             * even if we don't end up keeping it placed during the dive. */
            int wc = count_placed(w_tile);
            if (verify_assignment(w_tile, w_rot)) {
                if (wc > best_count) {
                    best_count = wc;
                    for (int s = 0; s < N; s++) { best_tile[s] = w_tile[s]; best_rot[s] = w_rot[s]; }
                    fprintf(stderr, "warm start: floor best=%d/%d from %s (validated)\n", best_count, N, warm_path);
                }
            } else {
                fprintf(stderr, "warm start: %s FAILED self-check, ignoring as floor (will not use as seed)\n", warm_path);
                wc = 0;
            }
            /* Second: begin the first dive by placing those warm placements
             * greedily in slot order, re-checking legality against the
             * (empty-so-far) board as we go -- guarantees the live partial
             * stays legal even if the file were subtly inconsistent. */
            if (wc > 0) {
                for (int s = 0; s < N; s++) {
                    if (w_tile[s] < 0) continue;
                    int t = w_tile[s], r = w_rot[s];
                    if (tile_used[t] >= 0) continue;
                    if (!legal_place(s, t, r)) continue;
                    place(s, t, r);
                }
                fprintf(stderr, "warm start: seeded dive with %d/%d placements\n", cur_count, N);
            }
        }
    }

    fprintf(stderr, "clique_solver: N=%d E=%d npat=%d budget=%.0fs seed=%lu\n", N, E, npat, budget_secs, seed);

    /* Anytime B&B main loop: run dfs() to exhaustion or time-out from the
     * (possibly warm-seeded) root.  On natural exhaustion (whole tree
     * proven, meaning best_count is optimal) before time is up, do
     * randomized restarts from empty (or re-seeded warm) to diversify --
     * exhaustive proof is astronomically unlikely at N=160 but this keeps
     * the anytime property if a small/synthetic instance IS fully solved
     * quickly. */
    long long restart_i = 0;
    while (!time_up && elapsed_secs() < budget_secs) {
        dfs();
        if (time_up) break;
        restart_i++;
        /* reset to empty (or warm-seeded) board for next restart, re-roll
         * the shuffle RNG state so ordering differs */
        for (int s = 0; s < N; s++) cur_tile[s] = -1;
        for (int t = 0; t < N; t++) tile_used[t] = -1;
        cur_count = 0;
        rngs ^= (unsigned long)(restart_i * 0x9E3779B97F4A7C15ULL + 0xABCDEF12345ULL);
        if (rngs == 0) rngs = 12345;
        if (warm_path) {
            int w_tile[MAXN], w_rot[MAXN];
            if (load_warm(warm_path, w_tile, w_rot) > 0 && verify_assignment(w_tile, w_rot)) {
                for (int s = 0; s < N; s++) {
                    if (w_tile[s] < 0) continue;
                    int t = w_tile[s], r = w_rot[s];
                    if (tile_used[t] >= 0) continue;
                    if (!legal_place(s, t, r)) continue;
                    place(s, t, r);
                }
            }
        }
        fprintf(stderr, "restart=%lld best=%d/%d nodes=%lld t=%.0f\n", restart_i, best_count, N, nodes, elapsed_secs());
        if (best_count == N) break; /* full solution found -- done */
    }

    if (!verify_assignment(best_tile, best_rot)) {
        fprintf(stderr, "FATAL: final best failed self-check (should be unreachable)\n");
        return 1;
    }
    write_best(g_outf);
    fprintf(stderr, "FINAL best=%d/%d nodes=%lld t=%.0f restarts=%lld -> %s\n",
        best_count, N, nodes, elapsed_secs(), restart_i, g_outf);
    printf("BEST %d\n", best_count);
    return 0;
}
