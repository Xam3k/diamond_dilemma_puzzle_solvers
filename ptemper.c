/* Parallel Tempering (replica-exchange Monte Carlo) local search for a COMPLETE
 * Diamond Dilemma edge-matching, built on top of the guided-move machinery in
 * solver_mc.c (same instance format, same conventions):
 *
 *   - tile edge (j+rot)%3 sits on slot-edge j
 *   - two tile patterns match iff revid[patA] == patB   (11-bit strings, reversed)
 *   - cost = number of mismatched board edges (of the 240 unique board edges)
 *   - full placement = permutation of all 160 tiles onto all 160 slots + a
 *     rotation in {0,1,2} for each; goal cost 0.
 *
 * This solver runs R independent replicas, each doing the same guided
 * Metropolis local search as solver_mc.c but each pinned to its OWN fixed
 * temperature on a geometric ladder from T_lo (cold, exploitative) to T_hi
 * (hot, exploratory). Periodically, adjacent replicas attempt a REPLICA
 * EXCHANGE: swap their entire configurations with the standard replica-
 * exchange Metropolis criterion
 *
 *     P(swap i,i+1) = min(1, exp((cost_i - cost_{i+1}) * (1/T_i - 1/T_{i+1})))
 *
 * This lets configurations random-walk in temperature: a replica that
 * random-walks down to T_lo carries with it whatever good structure it
 * built up at higher T, while replicas stuck in a bad basin at low T can
 * escape by trading places with a hot, more mobile replica. This is the
 * classic fix for simulated annealing getting stuck in deep local minima.
 *
 * Swaps between replicas exchange the ENTIRE (tile_at,rot_at,slot_of) state,
 * so each replica independently remains a valid permutation of all 160
 * tiles at all times (moves are pairwise tile swaps + rotation changes;
 * whole-state exchange trivially preserves "valid permutation").
 *
 * Build:  zig cc -O3 -o ptemper.exe ptemper.c
 * Usage:  ptemper.exe <instance.txt> <seconds> <seed>
 * Env:
 *   PT_R        number of replicas               (default 8)
 *   PT_TLO      coldest replica temperature       (default 0.05)
 *   PT_THI      hottest replica temperature       (default 3.0)
 *   PT_SWEEP    moves per replica between exchange attempts (default 100000)
 *   PT_WARM     path to a partial file to warm-start the cold replicas from
 *
 * Output:
 *   pt_full_best.txt     "slot:tile:rot " for all 160 slots (best full placement)
 *   pt_partial_best.txt  "slot:tile:rot " for a greedy-vertex-cover-derived
 *                        subset of slots that has ZERO internal mismatches
 *   stderr heartbeat ~every 20s, and a line on every global-best improvement:
 *       best=<m> partial=<k>/160 t=<elapsed> exchanges=<n>
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <math.h>

#define MAXN 160
#define MAXE 240
#define MAXPAT 2048
#define MAXR 64

static int N, E;
static int nb_slot[MAXN][3], nb_edge[MAXN][3];
static int tilepat[MAXN][3];            /* pattern id of tile t edge e */
static int revid[MAXPAT];               /* reverse pattern id, or -1 */
static int edgeA[MAXE], edgeAj[MAXE], edgeB[MAXE], edgeBk[MAXE];
static int eos[MAXN][3];                /* the 3 edge indices touching slot s */
static int eos_n[MAXN];

/* pattern table */
static char pats[MAXPAT][12];
static int npat = 0;
static int pat_id(const char *s) {
    for (int i = 0; i < npat; i++) if (!strncmp(pats[i], s, 11)) return i;
    strncpy(pats[npat], s, 11); pats[npat][11] = 0;
    return npat++;
}
static void rev_str(const char *s, char *o) { for (int i = 0; i < 11; i++) o[i] = s[10 - i]; o[11] = 0; }

/* index: for each pattern id, list of (tile<<2|edge) carrying it -- shared
 * across all replicas (instance-level, read-only after setup) */
static int *pat_list[MAXPAT];
static int pat_cnt[MAXPAT];

/* ---- per-replica state (struct-of-replicas, arrays sized MAXR) ---- */
typedef struct {
    int tile_at[MAXN];
    int rot_at[MAXN];
    int slot_of[MAXN];
    int cost;
    double T;
    unsigned long rng;
} Replica;

static Replica rep[MAXR];
static int Rn; /* number of replicas actually in use */

/* best-ever (global) */
static int best_cost;
static int best_tile[MAXN], best_rot[MAXN];

static inline unsigned long xr(Replica *rp){
    unsigned long x = rp->rng;
    x ^= x<<13; x ^= x>>7; x ^= x<<17;
    rp->rng = x;
    return x;
}
static inline int ri(Replica *rp, int m){ return (int)(xr(rp)%(unsigned)m); }
static inline double rd(Replica *rp){ return (xr(rp)>>11)*(1.0/9007199254740992.0); }

static inline int ebad_r(Replica *rp, int ei){
    int s=edgeA[ei], b=edgeB[ei];
    int pa=tilepat[rp->tile_at[s]][(edgeAj[ei]+rp->rot_at[s])%3];
    int pb=tilepat[rp->tile_at[b]][(edgeBk[ei]+rp->rot_at[b])%3];
    return revid[pa]==pb ? 0 : 1;
}
static int slot_bad_r(Replica *rp, int s){
    int c=0; for(int x=0;x<eos_n[s];x++) c+=ebad_r(rp, eos[s][x]); return c;
}
static int full_cost_r(Replica *rp){
    int c=0; for(int ei=0;ei<E;ei++) c+=ebad_r(rp, ei); return c;
}

/* one guided Metropolis move on replica rp (mirrors solver_mc.c's inner loop) */
static void step(Replica *rp){
    double T = rp->T;
    int ei = ri(rp, E);
    if(!ebad_r(rp, ei)){
        /* occasional random rotation kick to keep exploring even when the
         * randomly-picked edge is already fine */
        if((ri(rp,8))==0){
            int s = ri(rp, N);
            int old = rp->rot_at[s];
            int nw = (old + 1 + ri(rp,2)) % 3;
            int bef = slot_bad_r(rp, s);
            rp->rot_at[s] = nw;
            int aft = slot_bad_r(rp, s);
            int d = aft - bef;
            if(d<=0 || rd(rp) < exp(-d/T)) rp->cost += d; else rp->rot_at[s] = old;
        }
        return;
    }
    int s = (ri(rp,2) ? edgeA[ei] : edgeB[ei]);
    int j, bs, bk;
    if(s==edgeA[ei]){ j=edgeAj[ei]; bs=edgeB[ei]; bk=edgeBk[ei]; }
    else            { j=edgeBk[ei]; bs=edgeA[ei]; bk=edgeAj[ei]; }
    int pb = tilepat[rp->tile_at[bs]][(bk + rp->rot_at[bs])%3];
    int want = revid[pb];
    int s2, r2;
    if(want>=0 && pat_cnt[want]>0 && rd(rp) < 0.85){
        int pick = pat_list[want][ ri(rp, pat_cnt[want]) ];
        int t2 = pick>>2, e2 = pick&3;
        s2 = rp->slot_of[t2];
        r2 = ((e2 - j)%3 + 3)%3;
    } else { s2 = ri(rp, N); r2 = ri(rp,3); }

    if(s2==s){
        int old = rp->rot_at[s];
        int nw = ri(rp,3);
        int bef = slot_bad_r(rp, s);
        rp->rot_at[s] = nw;
        int aft = slot_bad_r(rp, s);
        int d = aft - bef;
        if(d<=0 || rd(rp) < exp(-d/T)) rp->cost += d; else rp->rot_at[s] = old;
        return;
    }

    int bef = slot_bad_r(rp, s) + slot_bad_r(rp, s2);
    int adj_shared = 0;
    for(int x=0;x<eos_n[s];x++) for(int y=0;y<eos_n[s2];y++)
        if(eos[s][x]==eos[s2][y]) adj_shared += ebad_r(rp, eos[s][x]);
    bef -= adj_shared;

    int t_s = rp->tile_at[s], t_s2 = rp->tile_at[s2];
    int ro_s = rp->rot_at[s], ro_s2 = rp->rot_at[s2];
    rp->tile_at[s] = t_s2; rp->tile_at[s2] = t_s;
    rp->slot_of[t_s2] = s; rp->slot_of[t_s] = s2;
    rp->rot_at[s] = r2; /* keep rot_at[s2] = ro_s2 */

    int aft = slot_bad_r(rp, s) + slot_bad_r(rp, s2);
    int adj2 = 0;
    for(int x=0;x<eos_n[s];x++) for(int y=0;y<eos_n[s2];y++)
        if(eos[s][x]==eos[s2][y]) adj2 += ebad_r(rp, eos[s][x]);
    aft -= adj2;

    int d = aft - bef;
    if(d<=0 || rd(rp) < exp(-d/T)){
        rp->cost += d;
    } else {
        rp->tile_at[s] = t_s; rp->tile_at[s2] = t_s2;
        rp->slot_of[t_s] = s; rp->slot_of[t_s2] = s2;
        rp->rot_at[s] = ro_s; rp->rot_at[s2] = ro_s2;
    }
}

/* greedy vertex cover over the current mismatched-edge set of a config:
 * repeatedly drop the slot touching the most still-uncovered bad edges,
 * until no bad edges remain among the surviving (kept) slots. Returns the
 * number of kept slots and fills keep[] (1=kept). */
static int greedy_cover_keep(int *tile_at, int *rot_at, int *keep){
    static int badcnt[MAXN];
    static unsigned char edge_bad[MAXE];
    static unsigned char edge_alive[MAXE];
    for(int s=0;s<N;s++) keep[s]=1;
    int nbad=0;
    for(int ei=0; ei<E; ei++){
        int s=edgeA[ei], b=edgeB[ei];
        int pa=tilepat[tile_at[s]][(edgeAj[ei]+rot_at[s])%3];
        int pb=tilepat[tile_at[b]][(edgeBk[ei]+rot_at[b])%3];
        int bad = (revid[pa]==pb) ? 0 : 1;
        edge_bad[ei]=(unsigned char)bad;
        edge_alive[ei]=(unsigned char)bad;
        if(bad) nbad++;
    }
    for(int s=0;s<N;s++) badcnt[s]=0;
    for(int ei=0; ei<E; ei++) if(edge_bad[ei]){ badcnt[edgeA[ei]]++; badcnt[edgeB[ei]]++; }
    while(nbad>0){
        int worst=-1, wc=0;
        for(int s=0;s<N;s++) if(keep[s] && badcnt[s]>wc){ wc=badcnt[s]; worst=s; }
        if(worst<0) break; /* shouldn't happen while nbad>0, but guard */
        keep[worst]=0;
        for(int x=0;x<eos_n[worst];x++){
            int ei=eos[worst][x];
            if(edge_alive[ei]){
                edge_alive[ei]=0; nbad--;
                int other = (edgeA[ei]==worst)?edgeB[ei]:edgeA[ei];
                badcnt[other]--; /* this edge no longer counts against 'other' */
                badcnt[worst]--;
            }
        }
    }
    int kept=0; for(int s=0;s<N;s++) kept += keep[s];
    return kept;
}

static void write_full(const char*path, int *tile_at, int *rot_at){
    FILE*o=fopen(path,"w"); if(!o) return;
    for(int s=0;s<N;s++) fprintf(o,"%d:%d:%d ",s,tile_at[s],rot_at[s]);
    fprintf(o,"\n"); fclose(o);
}
static void write_partial(const char*path, int *tile_at, int *rot_at, int *keep){
    FILE*o=fopen(path,"w"); if(!o) return;
    for(int s=0;s<N;s++) if(keep[s]) fprintf(o,"%d:%d:%d ",s,tile_at[s],rot_at[s]);
    fprintf(o,"\n"); fclose(o);
}

/* re-verify a full placement from scratch: valid permutation + recompute cost */
static int verify_full_cost(int *tile_at, int *rot_at){
    static unsigned char seen[MAXN];
    for(int t=0;t<N;t++) seen[t]=0;
    for(int s=0;s<N;s++){
        int t=tile_at[s];
        if(t<0||t>=N||seen[t]) return -1; /* invalid permutation */
        seen[t]=1;
    }
    int c=0;
    for(int ei=0; ei<E; ei++){
        int s=edgeA[ei], b=edgeB[ei];
        int pa=tilepat[tile_at[s]][(edgeAj[ei]+rot_at[s])%3];
        int pb=tilepat[tile_at[b]][(edgeBk[ei]+rot_at[b])%3];
        if(revid[pa]!=pb) c++;
    }
    return c;
}

int main(int argc, char**argv){
    if(argc<4){ fprintf(stderr,"usage: ptemper inst secs seed\n"); return 2; }
    const char*inst=argv[1];
    double budget=atof(argv[2]);
    unsigned long seed = (unsigned long)atol(argv[3]);

    FILE*f=fopen(inst,"r"); if(!f){perror("open");return 2;}
    fscanf(f,"%d %d",&N,&E);
    for(int s=0;s<N;s++) for(int j=0;j<3;j++) fscanf(f,"%d %d",&nb_slot[s][j],&nb_edge[s][j]);
    char a[16],b2[16],c[16];
    for(int t=0;t<N;t++){ fscanf(f,"%s %s %s",a,b2,c);
        tilepat[t][0]=pat_id(a); tilepat[t][1]=pat_id(b2); tilepat[t][2]=pat_id(c); }
    fclose(f);

    for(int i=0;i<npat;i++){ char r[12]; rev_str(pats[i],r); revid[i]=-1;
        for(int j=0;j<npat;j++) if(!strncmp(pats[j],r,11)){revid[i]=j;break;} }

    E=0; for(int s=0;s<N;s++) eos_n[s]=0;
    for(int s=0;s<N;s++) for(int j=0;j<3;j++){
        int b=nb_slot[s][j], k=nb_edge[s][j];
        if(s<b || (s==b && j<k)){
            edgeA[E]=s;edgeAj[E]=j;edgeB[E]=b;edgeBk[E]=k;
            eos[s][eos_n[s]++]=E; eos[b][eos_n[b]++]=E; E++;
        }
    }

    for(int p=0;p<npat;p++) pat_cnt[p]=0;
    for(int t=0;t<N;t++) for(int e=0;e<3;e++) pat_cnt[tilepat[t][e]]++;
    for(int p=0;p<npat;p++) pat_list[p]=malloc(sizeof(int)*(pat_cnt[p]>0?pat_cnt[p]:1));
    { int tmp[MAXPAT]; for(int p=0;p<npat;p++) tmp[p]=0;
      for(int t=0;t<N;t++) for(int e=0;e<3;e++){ int p=tilepat[t][e]; pat_list[p][tmp[p]++]=(t<<2)|e; } }

    /* ---- replica setup ---- */
    const char*renv=getenv("PT_R"); Rn = renv?atoi(renv):8;
    if(Rn<1) Rn=1; if(Rn>MAXR) Rn=MAXR;
    const char*tloenv=getenv("PT_TLO"); double Tlo = tloenv?atof(tloenv):0.05;
    const char*thienv=getenv("PT_THI"); double Thi = thienv?atof(thienv):3.0;
    if(Tlo<1e-6) Tlo=1e-6;
    if(Thi<Tlo) Thi=Tlo;
    const char*sweepenv=getenv("PT_SWEEP"); long sweep_steps = sweepenv?atol(sweepenv):100000;
    if(sweep_steps<1) sweep_steps=1;
    const char*warmenv=getenv("PT_WARM");

    /* geometric ladder T_lo .. T_hi across Rn replicas (replica 0 = coldest) */
    for(int r=0;r<Rn;r++){
        if(Rn==1) rep[r].T = Tlo;
        else {
            double frac = (double)r/(double)(Rn-1);
            rep[r].T = Tlo * pow(Thi/Tlo, frac);
        }
        rep[r].rng = (unsigned long)(seed*2654435761UL + (unsigned long)(r+1)*40503UL + 12345UL);
        if(rep[r].rng==0) rep[r].rng = 2463534242UL + (unsigned long)r;
    }

    /* default: random full placement for every replica */
    for(int r=0;r<Rn;r++){
        Replica *rp=&rep[r];
        for(int s=0;s<N;s++) rp->tile_at[s]=s;
        for(int s=N-1;s>0;s--){ int j=ri(rp,s+1); int tp=rp->tile_at[s]; rp->tile_at[s]=rp->tile_at[j]; rp->tile_at[j]=tp; }
        for(int s=0;s<N;s++){ rp->rot_at[s]=ri(rp,3); rp->slot_of[rp->tile_at[s]]=s; }
        rp->cost = full_cost_r(rp);
    }

    /* warm start: load a partial file, place its listed (slot,tile,rot),
     * then fill the remaining slots with the unused tiles in random order
     * and random rotation. Only applied to the LOWER-temperature half of
     * the ladder (replica indices 0 .. Rn/2-1); the rest stay random for
     * diversity. */
    if(warmenv && warmenv[0]){
        FILE*wf=fopen(warmenv,"r");
        if(!wf){
            fprintf(stderr,"PT_WARM: could not open '%s', ignoring\n", warmenv);
        } else {
            static int wslot[MAXN], wtile[MAXN], wrot[MAXN];
            int wn=0;
            int s,t,rr;
            while(wn<MAXN && fscanf(wf,"%d:%d:%d",&s,&t,&rr)==3){ wslot[wn]=s; wtile[wn]=t; wrot[wn]=rr; wn++; }
            fclose(wf);
            /* validate: slots and tiles distinct and in range */
            static unsigned char slot_used[MAXN], tile_used[MAXN];
            memset(slot_used,0,sizeof(slot_used)); memset(tile_used,0,sizeof(tile_used));
            int ok=1;
            for(int i=0;i<wn;i++){
                if(wslot[i]<0||wslot[i]>=N||wtile[i]<0||wtile[i]>=N||wrot[i]<0||wrot[i]>2){ ok=0; break; }
                if(slot_used[wslot[i]] || tile_used[wtile[i]]){ ok=0; break; }
                slot_used[wslot[i]]=1; tile_used[wtile[i]]=1;
            }
            if(!ok){
                fprintf(stderr,"PT_WARM: file '%s' malformed/inconsistent, ignoring\n", warmenv);
            } else {
                int half = Rn/2; if(half<1) half=1;
                for(int r=0;r<half;r++){
                    Replica *rp=&rep[r];
                    static int free_tiles[MAXN]; int nfree=0;
                    for(int tt=0; tt<N; tt++) if(!tile_used[tt]) free_tiles[nfree++]=tt;
                    /* shuffle free_tiles using this replica's own rng so replicas differ */
                    for(int i=nfree-1;i>0;i--){ int j=ri(rp,i+1); int tp=free_tiles[i]; free_tiles[i]=free_tiles[j]; free_tiles[j]=tp; }
                    static unsigned char slot_filled[MAXN];
                    memset(slot_filled,0,sizeof(slot_filled));
                    for(int i=0;i<wn;i++){ rp->tile_at[wslot[i]]=wtile[i]; rp->rot_at[wslot[i]]=wrot[i]; slot_filled[wslot[i]]=1; }
                    int fi=0;
                    for(int s2=0;s2<N;s2++){
                        if(!slot_filled[s2]){
                            rp->tile_at[s2]=free_tiles[fi++];
                            rp->rot_at[s2]=ri(rp,3);
                        }
                    }
                    for(int s2=0;s2<N;s2++) rp->slot_of[rp->tile_at[s2]]=s2;
                    rp->cost = full_cost_r(rp);
                }
                fprintf(stderr,"PT_WARM: loaded %d placed tiles from '%s' into %d cold replica(s)\n", wn, warmenv, half);
            }
        }
    }

    /* global best init from replica 0 */
    best_cost = rep[0].cost;
    for(int s=0;s<N;s++){ best_tile[s]=rep[0].tile_at[s]; best_rot[s]=rep[0].rot_at[s]; }
    for(int r=1;r<Rn;r++){
        if(rep[r].cost < best_cost){
            best_cost = rep[r].cost;
            for(int s=0;s<N;s++){ best_tile[s]=rep[r].tile_at[s]; best_rot[s]=rep[r].rot_at[s]; }
        }
    }

    time_t t0 = time(0);
    time_t last_heartbeat = t0;
    long exchanges = 0;
    long exchange_attempts = 0;
    long total_moves = 0;
    int parity = 0; /* 0 = even pairs (0,1)(2,3).., 1 = odd pairs (1,2)(3,4).. */

    /* shared xorshift for the exchange-acceptance random draws (uses replica
     * 0's stream advanced separately so it doesn't perturb replica dynamics) */
    unsigned long exrng = (unsigned long)(seed*2654435761UL + 987654321UL);
    if(exrng==0) exrng = 2463534242UL;
    #define EXR_NEXT() ( exrng^=exrng<<13, exrng^=exrng>>7, exrng^=exrng<<17, exrng )
    #define EXR_D() ((EXR_NEXT()>>11)*(1.0/9007199254740992.0))

    double elapsed = 0;
    while(1){
        for(int r=0;r<Rn;r++){
            Replica *rp=&rep[r];
            for(long k=0;k<sweep_steps;k++) step(rp);
        }
        total_moves += (long)Rn * sweep_steps;

        /* replica exchange attempts on adjacent pairs, alternating parity */
        for(int i=parity; i+1<Rn; i+=2){
            Replica *ra=&rep[i], *rb=&rep[i+1];
            exchange_attempts++;
            double delta = (ra->cost - rb->cost) * (1.0/ra->T - 1.0/rb->T);
            int accept = (delta >= 0) || (EXR_D() < exp(delta));
            if(accept){
                /* swap entire configs (tile_at/rot_at/slot_of/cost); T stays
                 * fixed per replica slot, so the exchange itself changes which
                 * config sits at which temperature */
                static int tmp_tile[MAXN], tmp_rot[MAXN], tmp_slot[MAXN];
                memcpy(tmp_tile, ra->tile_at, sizeof(tmp_tile));
                memcpy(tmp_rot,  ra->rot_at,  sizeof(tmp_rot));
                memcpy(tmp_slot, ra->slot_of, sizeof(tmp_slot));
                int tmp_cost = ra->cost;

                memcpy(ra->tile_at, rb->tile_at, sizeof(tmp_tile));
                memcpy(ra->rot_at,  rb->rot_at,  sizeof(tmp_rot));
                memcpy(ra->slot_of, rb->slot_of, sizeof(tmp_slot));
                ra->cost = rb->cost;

                memcpy(rb->tile_at, tmp_tile, sizeof(tmp_tile));
                memcpy(rb->rot_at,  tmp_rot,  sizeof(tmp_rot));
                memcpy(rb->slot_of, tmp_slot, sizeof(tmp_slot));
                rb->cost = tmp_cost;

                exchanges++;
            }
        }
        parity ^= 1;

        /* update global best */
        for(int r=0;r<Rn;r++){
            if(rep[r].cost < best_cost){
                best_cost = rep[r].cost;
                for(int s=0;s<N;s++){ best_tile[s]=rep[r].tile_at[s]; best_rot[s]=rep[r].rot_at[s]; }

                int vc = verify_full_cost(best_tile, best_rot);
                if(vc < 0){
                    fprintf(stderr, "WARNING: best placement failed permutation re-verify, skipping write\n");
                } else {
                    static int keep[MAXN];
                    int kept = greedy_cover_keep(best_tile, best_rot, keep);
                    write_full("pt_full_best.txt", best_tile, best_rot);
                    write_partial("pt_partial_best.txt", best_tile, best_rot, keep);
                    elapsed = difftime(time(0), t0);
                    fprintf(stderr, "best=%d partial=%d/160 t=%.0f exchanges=%ld\n",
                        vc, kept, elapsed, exchanges);
                }
                if(best_cost==0){
                    fprintf(stderr, "*** COMPLETE MATCHING FOUND t=%.0f ***\n", difftime(time(0),t0));
                }
            }
        }

        time_t now = time(0);
        elapsed = difftime(now, t0);
        if(now - last_heartbeat >= 20){
            last_heartbeat = now;
            fprintf(stderr, "heartbeat t=%.0f best=%d moves=%ld exchange_att=%ld exchanges=%ld replicas:",
                elapsed, best_cost, total_moves, exchange_attempts, exchanges);
            for(int r=0;r<Rn;r++) fprintf(stderr, " [T=%.3f c=%d]", rep[r].T, rep[r].cost);
            fprintf(stderr, "\n");
        }

        if(elapsed >= budget || best_cost==0) break;
    }

    /* final re-verify + write (in case last write above was skipped, or to
     * guarantee freshest state, e.g. if best_cost==0 triggered mid-sweep) */
    {
        int vc = verify_full_cost(best_tile, best_rot);
        if(vc<0){
            fprintf(stderr, "FATAL: final best placement is not a valid permutation!\n");
        } else {
            static int keep[MAXN];
            int kept = greedy_cover_keep(best_tile, best_rot, keep);
            write_full("pt_full_best.txt", best_tile, best_rot);
            write_partial("pt_partial_best.txt", best_tile, best_rot, keep);
            double el = difftime(time(0), t0);
            fprintf(stderr, "FINAL best=%d partial=%d/160 t=%.0f exchanges=%ld moves=%ld\n",
                vc, kept, el, exchanges, total_moves);
            if(vc==0) printf("SOLVED 0\n"); else printf("BEST %d\n", vc);
        }
    }
    return 0;
}
