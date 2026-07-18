/*
 * tabu_solver.c  --  Tabu-search conflict minimizer for Diamond Dilemma
 *
 * ROTATION / MATCH CONVENTIONS (identical to solver_mc.c):
 *   - Tile t has 3 edge patterns: tilepat[t][0..2].
 *   - When tile t sits in slot s with rotation r, tile-edge (j+r)%3 faces
 *     slot-direction j.  Pattern on slot-direction j is:
 *       tilepat[t][(j + rot_at[s]) % 3]
 *   - A board edge connects slot s (direction j) to slot b (direction k).
 *     It is MATCHED iff  revid[patA] == patB, where
 *       patA = tilepat[tile_at[s]][(j + rot_at[s]) % 3]
 *       patB = tilepat[tile_at[b]][(k + rot_at[b]) % 3]
 *     revid[p] = bit-reversal of p, or -1 for boundary patterns.
 *
 * BOARD: N=160 slots, E=240 internal edges.
 *
 * ALGORITHM: Tabu search with aspiration criterion.
 *   Each iteration:
 *     1. Pick a random violated board edge ei.
 *     2. Build a candidate set of ~64 random slots + guided (pattern-index)
 *        partners for the two endpoint slots of ei.
 *     3. For each candidate pair (s_fix, s2), evaluate three move types:
 *          A) Pure rotation of s_fix (3 options).
 *          B) Swap tiles of s_fix and s2, keep both rotations.
 *          C) Swap + greedily re-optimize both rotations (9 combos).
 *     4. Select the best non-tabu move by delta-cost (fully incremental).
 *        Aspiration override: allow a tabu move if new_cost < best_ever.
 *     5. Always apply a move: fall back to best non-tabu worsening move
 *        or a random forced swap if no neutral/improving move exists.
 *   Tabu: after placing tile t in slot s, forbid returning t to s for
 *     TABU_BASE + rand[0,TABU_RAND) iterations, encoded as
 *     last_at[t][s] = current_iter + tenure (expires when current_iter > it).
 *   Hard restart from a fresh random permutation every STALL_RESTART iters
 *   without a global-best improvement.
 *
 * PARTIAL EXTRACTION:
 *   Greedy vertex-cover on the mismatched-edge subgraph of the best full
 *   placement: repeatedly remove the slot (endpoint) covering the most
 *   remaining mismatched edges.
 *
 * OUTPUTS:
 *   mc_full_best.txt    -- best full placement (slot:tile:rot ...)
 *   mc_partial_best.txt -- partial after vertex-cover extraction
 *   stderr              -- progress lines on each improvement + heartbeat
 *
 * Build:  zig cc -O3 -o tabu_solver.exe tabu_solver.c
 * Run:    tabu_solver.exe instance_gold.txt 3600 42
 * Tune:   TABU_TENURE=300 tabu_solver.exe ...
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

/* ---------- compile-time constants ---------- */
#define MAXN          160
#define MAXE          240
#define MAXPAT        2048
#define RAND_PARTNERS  64    /* random partner slots sampled per iter */
#define TABU_BASE     200    /* base tabu tenure (iterations) */
#define TABU_RAND     200    /* additional random tenure in [0, TABU_RAND) */
#define STALL_RESTART 400000000L
#define HEARTBEAT      50000000L

/* ---------- instance data ---------- */
static int N, E;
static int nb_slot[MAXN][3], nb_edge[MAXN][3];
static int tilepat[MAXN][3];   /* tilepat[t][e] = pattern id of tile t, edge e */
static int revid[MAXPAT];      /* revid[p] = reverse pattern id, or -1 */

/* board edge table */
static int edgeA[MAXE], edgeAj[MAXE];
static int edgeB[MAXE], edgeBk[MAXE];
static int eos[MAXN][3];   /* board-edge indices touching slot s */
static int eos_n[MAXN];

/* pattern occurrence index: pat_list[p] = array of (tile<<2)|edge entries */
static int *pat_list[MAXPAT];
static int  pat_cnt[MAXPAT];

/* ---------- pattern string table ---------- */
static char pats[MAXPAT][12];
static int  npat = 0;

static int pat_id(const char *s) {
    for (int i = 0; i < npat; i++)
        if (!strncmp(pats[i], s, 11)) return i;
    strncpy(pats[npat], s, 11);
    pats[npat][11] = '\0';
    return npat++;
}
static void rev_str(const char *s, char *o) {
    for (int i = 0; i < 11; i++) o[i] = s[10 - i];
    o[11] = '\0';
}

/* ---------- solver state (all static -- no malloc in hot loop) ---------- */
static int tile_at[MAXN];
static int rot_at[MAXN];
static int slot_of[MAXN];  /* inverse: slot_of[t] = slot holding tile t */

/*
 * Tabu table: last_at[t][s] stores the iteration number until which
 * tile t is forbidden from being placed into slot s.
 * A move is tabu iff last_at[t][s] >= current_iter.
 * Use long to avoid 32-bit overflow at high iter counts.
 * 160x160 = 25600 longs = 200 KB -- fits comfortably.
 */
static long last_at[MAXN][MAXN];

/* global best */
static int best_cost;
static int best_tile[MAXN], best_rot[MAXN];

/* ---------- xorshift64 RNG ---------- */
static unsigned long rngs;
static inline unsigned long xr(void) {
    rngs ^= rngs << 13;
    rngs ^= rngs >> 7;
    rngs ^= rngs << 17;
    return rngs;
}
static inline int ri(int m) { return (int)(xr() % (unsigned)m); }

/* ---------- edge-cost helpers ---------- */

/* Is board-edge ei currently mismatched? */
static inline int ebad(int ei) {
    int s  = edgeA[ei], b  = edgeB[ei];
    int pa = tilepat[tile_at[s]][(edgeAj[ei] + rot_at[s]) % 3];
    int pb = tilepat[tile_at[b]][(edgeBk[ei] + rot_at[b]) % 3];
    return (revid[pa] == pb) ? 0 : 1;
}

/* Mismatched edges touching slot s */
static inline int slot_bad(int s) {
    int c = 0;
    for (int x = 0; x < eos_n[s]; x++) c += ebad(eos[s][x]);
    return c;
}

/*
 * Delta cost for swapping tiles of s1 and s2 with new rotations.
 * Semantics:
 *   tile_at[s1] (= t_old1) will go to slot s2 with rotation r1new.
 *   tile_at[s2] (= t_old2) will go to slot s1 with rotation r2new.
 *
 * Returns (new_cost_contribution) - (old_cost_contribution) for the
 * affected edge set (all edges touching s1 or s2).
 * Shared edges (touching both s1 and s2) are counted exactly once.
 *
 * Temporarily mutates state, then restores.
 */
static int delta_swap(int s1, int s2, int r1new, int r2new) {
    int t1 = tile_at[s1], t2 = tile_at[s2];
    int ro1 = rot_at[s1], ro2 = rot_at[s2];

    /* --- old cost contribution --- */
    int old_s1 = slot_bad(s1);
    int old_s2 = slot_bad(s2);
    /* subtract shared edges counted twice */
    int sh_old = 0;
    for (int x = 0; x < eos_n[s1]; x++)
        for (int y = 0; y < eos_n[s2]; y++)
            if (eos[s1][x] == eos[s2][y])
                sh_old += ebad(eos[s1][x]);

    /* --- temporarily apply swap --- */
    tile_at[s1] = t2; rot_at[s1] = r2new;
    tile_at[s2] = t1; rot_at[s2] = r1new;
    slot_of[t2] = s1; slot_of[t1] = s2;

    /* --- new cost contribution --- */
    int new_s1 = slot_bad(s1);
    int new_s2 = slot_bad(s2);
    int sh_new = 0;
    for (int x = 0; x < eos_n[s1]; x++)
        for (int y = 0; y < eos_n[s2]; y++)
            if (eos[s1][x] == eos[s2][y])
                sh_new += ebad(eos[s1][x]);

    /* --- restore --- */
    tile_at[s1] = t1; rot_at[s1] = ro1;
    tile_at[s2] = t2; rot_at[s2] = ro2;
    slot_of[t1] = s1; slot_of[t2] = s2;

    return (new_s1 + new_s2 - sh_new) - (old_s1 + old_s2 - sh_old);
}

/* Delta cost for purely rotating slot s to new rotation r (tile stays). */
static int delta_rotate(int s, int r) {
    int old_r  = rot_at[s];
    int before = slot_bad(s);
    rot_at[s]  = r;
    int after  = slot_bad(s);
    rot_at[s]  = old_r;
    return after - before;
}

/* ---------- instance loader ---------- */
static void load_instance(const char *path) {
    FILE *f = fopen(path, "r");
    if (!f) { perror("open instance"); exit(2); }

    fscanf(f, "%d %d", &N, &E);
    for (int s = 0; s < N; s++)
        for (int j = 0; j < 3; j++)
            fscanf(f, "%d %d", &nb_slot[s][j], &nb_edge[s][j]);

    char a[16], b[16], c[16];
    for (int t = 0; t < N; t++) {
        fscanf(f, "%s %s %s", a, b, c);
        tilepat[t][0] = pat_id(a);
        tilepat[t][1] = pat_id(b);
        tilepat[t][2] = pat_id(c);
    }
    fclose(f);

    /* reverse-pattern table */
    for (int i = 0; i < npat; i++) {
        char r[12]; rev_str(pats[i], r);
        revid[i] = -1;
        for (int j = 0; j < npat; j++)
            if (!strncmp(pats[j], r, 11)) { revid[i] = j; break; }
    }

    /* build unique board edges + slot-to-edge map */
    E = 0;
    for (int s = 0; s < N; s++) eos_n[s] = 0;
    for (int s = 0; s < N; s++)
        for (int j = 0; j < 3; j++) {
            int b2 = nb_slot[s][j], k = nb_edge[s][j];
            if (s < b2 || (s == b2 && j < k)) {
                edgeA[E] = s;  edgeAj[E] = j;
                edgeB[E] = b2; edgeBk[E] = k;
                eos[s][eos_n[s]++] = E;
                eos[b2][eos_n[b2]++] = E;
                E++;
            }
        }

    /* pattern occurrence index */
    for (int p = 0; p < npat; p++) pat_cnt[p] = 0;
    for (int t = 0; t < N; t++)
        for (int e = 0; e < 3; e++)
            pat_cnt[tilepat[t][e]]++;
    for (int p = 0; p < npat; p++)
        pat_list[p] = (int *)malloc(sizeof(int) * (pat_cnt[p] > 0 ? pat_cnt[p] : 1));
    {
        int tmp[MAXPAT];
        for (int p = 0; p < npat; p++) tmp[p] = 0;
        for (int t = 0; t < N; t++)
            for (int e = 0; e < 3; e++) {
                int p = tilepat[t][e];
                pat_list[p][tmp[p]++] = (t << 2) | e;
            }
    }
}

/* ---------- random full-placement (Fisher-Yates) ---------- */
static void random_placement(void) {
    for (int s = 0; s < N; s++) tile_at[s] = s;
    for (int s = N - 1; s > 0; s--) {
        int j = ri(s + 1);
        int tmp = tile_at[s]; tile_at[s] = tile_at[j]; tile_at[j] = tmp;
    }
    for (int s = 0; s < N; s++) {
        rot_at[s]           = ri(3);
        slot_of[tile_at[s]] = s;
    }
}

/* ---------- warm start from a partial file ("slot:tile:rot ...") ----------
 * Places listed tiles at their slots/rotations, then fills remaining slots with
 * the unused tiles (random rotation). Returns 1 on success, 0 if file missing. */
static int warm_start(const char *path) {
    FILE *f = fopen(path, "r");
    if (!f) return 0;
    int has[MAXN]; int used_t[MAXN];
    for (int s = 0; s < N; s++) { has[s] = 0; tile_at[s] = -1; }
    for (int t = 0; t < N; t++) used_t[t] = 0;
    int s, t, r;
    while (fscanf(f, " %d:%d:%d", &s, &t, &r) == 3) {
        if (s >= 0 && s < N && t >= 0 && t < N) {
            tile_at[s] = t; rot_at[s] = r % 3; has[s] = 1; used_t[t] = 1;
        }
    }
    fclose(f);
    /* collect unused tiles, shuffle, fill empty slots */
    int pool[MAXN], np = 0;
    for (int tt = 0; tt < N; tt++) if (!used_t[tt]) pool[np++] = tt;
    for (int i = np - 1; i > 0; i--) { int j = ri(i + 1); int tm = pool[i]; pool[i] = pool[j]; pool[j] = tm; }
    int pi = 0;
    for (int ss = 0; ss < N; ss++) if (!has[ss]) { tile_at[ss] = pool[pi++]; rot_at[ss] = ri(3); }
    for (int ss = 0; ss < N; ss++) slot_of[tile_at[ss]] = ss;
    return 1;
}

/* ---------- full cost from scratch ---------- */
static int full_cost(void) {
    int c = 0;
    for (int ei = 0; ei < E; ei++) c += ebad(ei);
    return c;
}

/* ---------- greedy vertex-cover partial extraction ----------
 *
 * Operates on best_tile/best_rot (not current state).
 * Writes mc_partial_best.txt and returns #placed tiles.
 */
static int extract_partial(const char *path) {
    /* temporarily load best into live state */
    int save_t[MAXN], save_r[MAXN];
    for (int s = 0; s < N; s++) {
        save_t[s] = tile_at[s]; save_r[s] = rot_at[s];
        tile_at[s] = best_tile[s]; rot_at[s] = best_rot[s];
        slot_of[tile_at[s]] = s;
    }

    /* collect mismatched edges and per-slot degrees */
    int mbad[MAXE], nm = 0;
    int deg[MAXN];
    for (int s = 0; s < N; s++) deg[s] = 0;
    for (int ei = 0; ei < E; ei++) {
        if (ebad(ei)) {
            mbad[nm++] = ei;
            deg[edgeA[ei]]++;
            deg[edgeB[ei]]++;
        }
    }

    /* restore live state */
    for (int s = 0; s < N; s++) {
        tile_at[s] = save_t[s]; rot_at[s] = save_r[s];
        slot_of[tile_at[s]] = s;
    }

    /* greedy vertex cover */
    int removed[MAXN], covered[MAXE];
    for (int s = 0; s < N; s++) removed[s] = 0;
    for (int i = 0; i < nm; i++) covered[i] = 0;
    int remaining = nm;

    while (remaining > 0) {
        int best_s = -1, best_d = 0;
        for (int s = 0; s < N; s++)
            if (!removed[s] && deg[s] > best_d) { best_d = deg[s]; best_s = s; }
        if (best_s < 0) break;

        removed[best_s] = 1;
        for (int i = 0; i < nm; i++) {
            if (!covered[i] &&
                (edgeA[mbad[i]] == best_s || edgeB[mbad[i]] == best_s)) {
                covered[i] = 1;
                remaining--;
                int other = (edgeA[mbad[i]] == best_s)
                            ? edgeB[mbad[i]] : edgeA[mbad[i]];
                if (deg[other] > 0) deg[other]--;
            }
        }
        deg[best_s] = 0;
    }

    FILE *fp = fopen(path, "w");
    if (!fp) { perror("open partial"); return -1; }
    int placed = 0;
    for (int s = 0; s < N; s++) {
        if (!removed[s]) {
            fprintf(fp, "%d:%d:%d ", s, best_tile[s], best_rot[s]);
            placed++;
        }
    }
    fprintf(fp, "\n");
    fclose(fp);
    return placed;
}

/* ================================================================
 * MAIN TABU SEARCH
 * ================================================================ */
int main(int argc, char **argv) {
    if (argc < 4) {
        fprintf(stderr, "usage: tabu_solver <instance> <seconds> <seed>\n");
        return 2;
    }

    const char *inst_path = argv[1];
    double budget         = atof(argv[2]);
    unsigned long seed_in = (unsigned long)atol(argv[3]);
    rngs = seed_in * 2654435761UL + 1;  /* same scaling as solver_mc.c */

    load_instance(inst_path);

    const char *tenv = getenv("TABU_TENURE");
    int tenure_base  = tenv ? atoi(tenv) : TABU_BASE;

    memset(last_at, 0, sizeof(last_at));
    const char *warm = getenv("TABU_WARM");
    if (warm && warm_start(warm))
        fprintf(stderr, "warm start from %s\n", warm);
    else
        random_placement();
    int cost = full_cost();

    best_cost = cost;
    for (int s = 0; s < N; s++) { best_tile[s] = tile_at[s]; best_rot[s] = rot_at[s]; }

    time_t t0      = time(NULL);
    long   iters   = 0;
    long   lastimp = 0;
    long   restarts = 0;
    long   lasthb  = 0;

    fprintf(stderr, "start cost=%d N=%d E=%d tenure_base=%d\n",
            cost, N, E, tenure_base);

    /* candidate set (static to avoid repeated stack allocation) */
    static int cands[MAXN];
    static int in_cands[MAXN];

    while (1) {
        /* time check every 128 K iterations to amortize syscall */
        if ((iters & 0x1FFFF) == 0) {
            if (difftime(time(NULL), t0) >= budget) break;
        }

        /* heartbeat */
        if (iters - lasthb >= HEARTBEAT) {
            lasthb = iters;
            fprintf(stderr,
                "heartbeat iters=%ld cost=%d best=%d restarts=%ld t=%.0f\n",
                iters, cost, best_cost, restarts, difftime(time(NULL), t0));
        }

        /* hard restart on long stall */
        if (iters - lastimp > STALL_RESTART) {
            random_placement();
            cost    = full_cost();
            lastimp = iters;
            restarts++;
            memset(last_at, 0, sizeof(last_at));
            fprintf(stderr, "restart #%ld cost=%d best=%d iters=%ld\n",
                    restarts, cost, best_cost, iters);
        }

        iters++;

        /* pick a random board edge; skip if currently matched */
        int ei = ri(E);
        if (!ebad(ei)) continue;

        /*
         * Decide which endpoint to "fix" (s_fix) and which is "other" (s_oth).
         * We want to bring to s_fix a tile whose pattern on direction j_fix
         * matches what s_oth currently presents on direction k_oth.
         */
        int s_fix, j_fix, s_oth, k_oth;
        if (ri(2)) {
            s_fix = edgeA[ei]; j_fix = edgeAj[ei];
            s_oth = edgeB[ei]; k_oth = edgeBk[ei];
        } else {
            s_fix = edgeB[ei]; j_fix = edgeBk[ei];
            s_oth = edgeA[ei]; k_oth = edgeAj[ei];
        }
        (void)j_fix; /* used implicitly via the 'want' pattern and rotation calc */

        /* Pattern wanted on s_fix's direction j_fix */
        int pb   = tilepat[tile_at[s_oth]][(k_oth + rot_at[s_oth]) % 3];
        int want = revid[pb];   /* -1 if no reverse exists (boundary) */

        /* ---- build candidate partner set ---- */
        /* Clear only the entries we inserted last time */
        {
            /* ncands from prev iter stored in static; reset via loop below */
        }
        int ncands = 0;
        /* note: in_cands was zeroed at end of last iter (see bottom of loop) */

#define ADD_CAND(ss) do {                                   \
    int _ss = (ss);                                         \
    if (_ss != s_fix && !in_cands[_ss]) {                  \
        in_cands[_ss] = 1; cands[ncands++] = _ss;          \
    }                                                       \
} while(0)

        for (int i = 0; i < RAND_PARTNERS; i++) ADD_CAND(ri(N));

        if (want >= 0 && pat_cnt[want] > 0) {
            int gc = pat_cnt[want];
            if (gc <= 20) {
                for (int i = 0; i < gc; i++)
                    ADD_CAND(slot_of[pat_list[want][i] >> 2]);
            } else {
                for (int i = 0; i < 20; i++)
                    ADD_CAND(slot_of[pat_list[want][ri(gc)] >> 2]);
            }
        }

        /*
         * Evaluate moves and track the best.
         *
         * We track:
         *   best_delta, best_s2, best_r1, best_r2, best_is_rot
         *
         * After applying the chosen swap (s_fix, best_s2):
         *   s_fix gets  tile_at[best_s2]  with rotation best_r1
         *   best_s2 gets tile_at[s_fix]   with rotation best_r2
         *
         * For pure rotation:
         *   s_fix rotation -> best_r1
         *
         * We accept non-tabu moves improving over best_delta (initially INT_MAX
         * so ANY non-tabu move qualifies), or any move beating best_cost
         * (aspiration regardless of tabu).
         *
         * If no move was selected at all (all tabu, none aspirational),
         * we fall through to a random forced swap.
         */
        int best_delta  = 0x7fffffff;
        int best_s2     = -1;
        int best_r1     = -1;
        int best_r2     = -1;
        int best_is_rot = 0;
        int found_any   = 0;

        /* --- Move type A: pure rotation of s_fix --- */
        /* Tile stays; no tabu applies to rotation-only moves. */
        for (int r = 0; r < 3; r++) {
            if (r == rot_at[s_fix]) continue;
            int d = delta_rotate(s_fix, r);
            if (d < best_delta) {
                best_delta = d; best_r1 = r; best_is_rot = 1;
                best_s2 = -1; found_any = 1;
            }
        }

        /* --- Move types B and C: swap s_fix with each candidate s2 --- */
        int t_fix = tile_at[s_fix];
        int r_fix = rot_at[s_fix];

        for (int ci = 0; ci < ncands; ci++) {
            int s2  = cands[ci];
            int t2  = tile_at[s2];
            int r2  = rot_at[s2];

            /*
             * Tabu check: is this swap forbidden?
             * After the swap, t_fix lands in s2 and t2 lands in s_fix.
             * The swap is tabu iff either placement was recently forbidden.
             */
            int is_tabu = (last_at[t_fix][s2  ] >= iters) ||
                          (last_at[t2  ][s_fix] >= iters);

            /*
             * Try all 9 rotation combos (includes "keep both rotations" as
             * one specific combo).
             *
             * delta_swap(s_fix, s2, r1new, r2new):
             *   t_fix (= tile_at[s_fix]) goes to s2    with rotation r1new
             *   t2    (= tile_at[s2])    goes to s_fix with rotation r2new
             *
             * We record:
             *   best_r1 = rotation of t2 at s_fix  (= r2new in delta_swap)
             *   best_r2 = rotation of t_fix at s2  (= r1new in delta_swap)
             */
            for (int r_t2_at_sfix = 0; r_t2_at_sfix < 3; r_t2_at_sfix++) {
                for (int r_tfix_at_s2 = 0; r_tfix_at_s2 < 3; r_tfix_at_s2++) {
                    int d = delta_swap(s_fix, s2, r_tfix_at_s2, r_t2_at_sfix);
                    int new_cost = cost + d;

                    int ok = (!is_tabu && d < best_delta)
                           || (new_cost < best_cost);   /* aspiration */
                    if (ok) {
                        best_delta  = d;
                        best_s2     = s2;
                        best_r1     = r_t2_at_sfix;  /* s_fix gets t2 with this rot */
                        best_r2     = r_tfix_at_s2;  /* s2 gets t_fix with this rot */
                        best_is_rot = 0;
                        found_any   = 1;
                        /* If aspiration override, note we used it */
                    }
                }
            }
            (void)r2; (void)r_fix; /* available for future use */
        }

        /* ---- apply the chosen move ---- */
        if (best_is_rot && found_any) {
            /* pure rotation of s_fix */
            rot_at[s_fix] = best_r1;
            cost += best_delta;

        } else if (!best_is_rot && found_any && best_s2 >= 0) {
            /* swap */
            int s2 = best_s2;
            int t1 = tile_at[s_fix], t2 = tile_at[s2];

            /* record tabu: tile t1 is forbidden from s_fix, t2 from s2 */
            long tenure = tenure_base + (long)(xr() % (unsigned)TABU_RAND);
            last_at[t1][s_fix] = iters + tenure;
            last_at[t2][s2   ] = iters + tenure;

            tile_at[s_fix] = t2; rot_at[s_fix] = best_r1;
            tile_at[s2   ] = t1; rot_at[s2   ] = best_r2;
            slot_of[t2]    = s_fix;
            slot_of[t1]    = s2;
            cost += best_delta;

        } else {
            /*
             * All candidate moves were tabu and none beat best_cost.
             * Forced random swap to keep moving (tabu search must not stall).
             */
            if (ncands > 0) {
                int s2 = cands[ri(ncands)];
                int t1 = tile_at[s_fix], t2 = tile_at[s2];

                long tenure = tenure_base + (long)(xr() % (unsigned)TABU_RAND);
                last_at[t1][s_fix] = iters + tenure;
                last_at[t2][s2   ] = iters + tenure;

                /* pick random rotations for both */
                int rr1 = ri(3), rr2 = ri(3);
                int d = delta_swap(s_fix, s2, rr2, rr1);

                tile_at[s_fix] = t2; rot_at[s_fix] = rr1;
                tile_at[s2   ] = t1; rot_at[s2   ] = rr2;
                slot_of[t2]    = s_fix;
                slot_of[t1]    = s2;
                cost += d;
            }
        }

        /* ---- global best tracking ---- */
        if (cost < best_cost) {
            best_cost = cost;
            lastimp   = iters;
            for (int s = 0; s < N; s++) {
                best_tile[s] = tile_at[s];
                best_rot[s]  = rot_at[s];
            }

            /* write full best */
            FILE *fp = fopen("mc_full_best.txt", "w");
            if (fp) {
                for (int s = 0; s < N; s++)
                    fprintf(fp, "%d:%d:%d ", s, best_tile[s], best_rot[s]);
                fprintf(fp, "\n");
                fclose(fp);
            }

            /* extract partial and report */
            int placed = extract_partial("mc_partial_best.txt");
            fprintf(stderr,
                "best=%d iters=%ld t=%.0f restarts=%ld partial=%d/160\n",
                best_cost, iters, difftime(time(NULL), t0), restarts, placed);

            if (best_cost == 0) break;
        }

        /* clear in_cands for next iter */
        for (int i = 0; i < ncands; i++) in_cands[cands[i]] = 0;
    }

    double el = difftime(time(NULL), t0);
    fprintf(stderr, "done best=%d iters=%ld t=%.0f restarts=%ld\n",
            best_cost, iters, el, restarts);
    printf("BEST %d\n", best_cost);
    return 0;
}
