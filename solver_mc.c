/* Guided min-conflicts / simulated-annealing local search for a COMPLETE
 * Diamond Dilemma edge-matching.  Full placement of all 160 tiles; cost = number
 * of mismatched board edges; goal cost 0.
 *
 * Guided repair: pick a violated edge, find a tile that actually FITS one side,
 * swap it in (Metropolis acceptance), with reheat/restart to escape minima.
 *
 * Instance format (same as the Python tools produce):
 *   line1: "N E"
 *   N lines: "n0 k0 n1 k1 n2 k2"  (neighbor slot + neighbor edge for each of 3 edges)
 *   N lines: three 11-bit strings (a tile's edge patterns)
 *   then seed lines (ignored here)
 *
 * Build:  zig cc -O3 -o solver_mc.exe solver_mc.c
 * Usage:  solver_mc.exe <instance.txt> <seconds> <seed> [outfile]
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <math.h>

#define MAXN 160
#define MAXE 240
#define MAXPAT 2048

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

/* state */
static int tile_at[MAXN], rot_at[MAXN], slot_of[MAXN];
/* index: for each pattern id, list of (tile<<2|edge) carrying it */
static int *pat_list[MAXPAT];
static int pat_cnt[MAXPAT];

static unsigned long rngs;
static inline unsigned long xr(){ rngs^=rngs<<13; rngs^=rngs>>7; rngs^=rngs<<17; return rngs; }
static inline int ri(int m){ return (int)(xr()%(unsigned)m); }
static inline double rd(){ return (xr()>>11)*(1.0/9007199254740992.0); }

static inline int ebad(int ei){
    int s=edgeA[ei], b=edgeB[ei];
    int pa=tilepat[tile_at[s]][(edgeAj[ei]+rot_at[s])%3];
    int pb=tilepat[tile_at[b]][(edgeBk[ei]+rot_at[b])%3];
    return revid[pa]==pb ? 0 : 1;
}
static int slot_bad(int s){ int c=0; for(int x=0;x<eos_n[s];x++) c+=ebad(eos[s][x]); return c; }

int main(int argc,char**argv){
    if(argc<4){ fprintf(stderr,"usage: solver_mc inst secs seed [out]\n"); return 2; }
    const char*inst=argv[1]; double budget=atof(argv[2]); rngs=atol(argv[3])*2654435761UL+1;
    const char*outf=argc>4?argv[4]:"mc_solution.txt";
    FILE*f=fopen(inst,"r"); if(!f){perror("open");return 2;}
    fscanf(f,"%d %d",&N,&E);
    for(int s=0;s<N;s++) for(int j=0;j<3;j++) fscanf(f,"%d %d",&nb_slot[s][j],&nb_edge[s][j]);
    char a[16],b2[16],c[16];
    for(int t=0;t<N;t++){ fscanf(f,"%s %s %s",a,b2,c);
        tilepat[t][0]=pat_id(a); tilepat[t][1]=pat_id(b2); tilepat[t][2]=pat_id(c); }
    fclose(f);
    /* reverse ids (add reversed patterns to table if missing) */
    for(int i=0;i<npat;i++){ char r[12]; rev_str(pats[i],r); revid[i]=-1;
        for(int j=0;j<npat;j++) if(!strncmp(pats[j],r,11)){revid[i]=j;break;} }
    /* build unique board edges + slot->edge map */
    E=0; for(int s=0;s<N;s++) eos_n[s]=0;
    for(int s=0;s<N;s++) for(int j=0;j<3;j++){
        int b=nb_slot[s][j], k=nb_edge[s][j];
        if(s<b || (s==b && j<k)){
            edgeA[E]=s;edgeAj[E]=j;edgeB[E]=b;edgeBk[E]=k;
            eos[s][eos_n[s]++]=E; eos[b][eos_n[b]++]=E; E++;
        }
    }
    /* pattern occurrence index */
    for(int p=0;p<npat;p++){ pat_cnt[p]=0; }
    for(int t=0;t<N;t++) for(int e=0;e<3;e++) pat_cnt[tilepat[t][e]]++;
    for(int p=0;p<npat;p++) pat_list[p]=malloc(sizeof(int)*(pat_cnt[p]>0?pat_cnt[p]:1));
    { int tmp[MAXPAT]; for(int p=0;p<npat;p++) tmp[p]=0;
      for(int t=0;t<N;t++) for(int e=0;e<3;e++){ int p=tilepat[t][e]; pat_list[p][tmp[p]++]=(t<<2)|e; } }

    /* initial random full placement */
    for(int s=0;s<N;s++) tile_at[s]=s;
    for(int s=N-1;s>0;s--){ int j=ri(s+1); int tp=tile_at[s];tile_at[s]=tile_at[j];tile_at[j]=tp; }
    for(int s=0;s<N;s++){ rot_at[s]=ri(3); slot_of[tile_at[s]]=s; }
    int cost=0; for(int ei=0;ei<E;ei++) cost+=ebad(ei);
    int best=cost; time_t t0=time(0); double T=1.2; long iters=0,lastimp=0,restarts=0;
    int best_tile[MAXN], best_rot[MAXN];
    for(int s=0;s<N;s++){best_tile[s]=tile_at[s];best_rot[s]=rot_at[s];}
    /* clean SA: cool slowly from T_HI->T_LO across the budget; restart cooling cycle
     * (from best) only after a long stall. No per-iter reheat thrash. */
    const char*tenv=getenv("MC_T"); double TC = tenv?atof(tenv):0.20; /* constant low temp */
    long stall_lim = 100000000000L; /* effectively no restart for this test */
    const char*senv=getenv("MC_RESTART"); if(senv) stall_lim=atol(senv);
    T=TC;
    double elapsed=0;
    while(cost>0){
        if((iters & 0x1FFFF)==0){ elapsed=difftime(time(0),t0); if(elapsed>=budget) break; }
        iters++;
        /* pick a random violated edge */
        int ei=ri(E);
        if(!ebad(ei)){ /* occasionally also do a random rotation kick */
            if((iters&7)==0){ int s=ri(N); int old=rot_at[s]; int nw=(old+1+ri(2))%3;
                int bef=slot_bad(s); rot_at[s]=nw; int aft=slot_bad(s); int d=aft-bef;
                if(d<=0||rd()<exp(-d/T)) cost+=d; else rot_at[s]=old; }
            continue;
        }
        /* guided: fix side A of edge ei by bringing in a tile that matches B's pattern */
        int s = (ri(2)? edgeA[ei] : edgeB[ei]);
        int j, bs, bk;
        if(s==edgeA[ei]){ j=edgeAj[ei]; bs=edgeB[ei]; bk=edgeBk[ei]; }
        else            { j=edgeBk[ei]; bs=edgeA[ei]; bk=edgeAj[ei]; }
        int pb=tilepat[tile_at[bs]][(bk+rot_at[bs])%3];
        int want=revid[pb];            /* slot s edge j should carry pattern 'want' */
        int s2, r2;
        if(want>=0 && pat_cnt[want]>0 && rd()<0.85){
            int pick=pat_list[want][ri(pat_cnt[want])];
            int t2=pick>>2, e2=pick&3;
            s2=slot_of[t2];
            r2=( (e2 - j)%3 + 3)%3;      /* rotation so tile edge e2 lands on slot-edge j */
        } else { s2=ri(N); r2=ri(3); }   /* random move for diversification */
        if(s2==s){ /* just retry rotation of s */
            int old=rot_at[s]; int nw=ri(3); int bef=slot_bad(s); rot_at[s]=nw;
            int aft=slot_bad(s); int d=aft-bef; if(d<=0||rd()<exp(-d/T)) cost+=d; else rot_at[s]=old;
            continue;
        }
        /* swap tiles of s and s2; set s's rotation to r2, keep s2's rotation */
        int bef = slot_bad(s) + slot_bad(s2);
        int adj_shared = 0;            /* if s,s2 adjacent, their shared edge counted twice */
        for(int x=0;x<eos_n[s];x++) for(int y=0;y<eos_n[s2];y++) if(eos[s][x]==eos[s2][y]) adj_shared+=ebad(eos[s][x]);
        bef -= adj_shared;
        int t_s=tile_at[s], t_s2=tile_at[s2], ro_s=rot_at[s], ro_s2=rot_at[s2];
        tile_at[s]=t_s2; tile_at[s2]=t_s; slot_of[t_s2]=s; slot_of[t_s]=s2;
        rot_at[s]=r2;                  /* keep rot_at[s2] = ro_s2 */
        int aft = slot_bad(s) + slot_bad(s2);
        int adj2=0; for(int x=0;x<eos_n[s];x++) for(int y=0;y<eos_n[s2];y++) if(eos[s][x]==eos[s2][y]) adj2+=ebad(eos[s][x]);
        aft -= adj2;
        int d = aft - bef;
        if(d<=0 || rd()<exp(-d/T)){ cost+=d; }
        else { tile_at[s]=t_s; tile_at[s2]=t_s2; slot_of[t_s]=s; slot_of[t_s2]=s2;
               rot_at[s]=ro_s; rot_at[s2]=ro_s2; }

        if(cost<best){ best=cost; lastimp=iters;
            for(int s=0;s<N;s++){best_tile[s]=tile_at[s];best_rot[s]=rot_at[s];}
            if(best<=10) fprintf(stderr,"best=%d iters=%ld t=%.0f restarts=%ld\n",best,iters,difftime(time(0),t0),restarts);
        }
        /* optional restart from best after a long stall (off by default) */
        if(iters-lastimp>stall_lim){
            for(int s=0;s<N;s++){tile_at[s]=best_tile[s];rot_at[s]=best_rot[s];slot_of[tile_at[s]]=s;}
            cost=best; lastimp=iters; restarts++;
        }
        if((iters%40000000)==0) fprintf(stderr,"iters=%ld cost=%d best=%d T=%.3f restarts=%ld t=%.0f\n",
            iters,cost,best,T,restarts,difftime(time(0),t0));
    }
    double el=difftime(time(0),t0);
    if(cost==0){
        FILE*o=fopen(outf,"w");
        for(int s=0;s<N;s++) fprintf(o,"%d:%d:%d ",s,tile_at[s],rot_at[s]);
        fprintf(o,"\n"); fclose(o);
        fprintf(stderr,"*** COMPLETE MATCHING FOUND iters=%ld t=%.0f -> %s ***\n",iters,el,outf);
        printf("SOLVED 0\n");
    } else {
        fprintf(stderr,"stopped best=%d (mismatched edges of %d) cost_now=%d iters=%ld restarts=%ld t=%.0f\n",
            best,E,cost,iters,restarts,el);
        printf("BEST %d\n",best);
    }
    return 0;
}
