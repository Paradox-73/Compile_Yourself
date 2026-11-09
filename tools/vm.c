/* Local copy of the machine described in PROBLEM.pdf, for fast testing.
   usage: vm program.txt [max_steps] < input   (env VM_STATS=1 prints the step count) */
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#ifdef _WIN32
#include <io.h>
#include <fcntl.h>
#endif

#define N 1048576
#define IN (N - 2)
#define OUT (N - 1)
static int32_t mem[N];

int main(int argc, char **argv) {
    if (argc < 2) { fprintf(stderr, "usage: %s program.txt [max_steps] < input.txt\n", argv[0]); return 2; }
#ifdef _WIN32
    _setmode(_fileno(stdin), _O_BINARY);
    _setmode(_fileno(stdout), _O_BINARY);
#endif
    FILE *f = fopen(argv[1], "r");
    if (!f) { fprintf(stderr, "can't open %s\n", argv[1]); return 2; }
    long long limit = argc > 2 ? atoll(argv[2]) : 100000000LL;
    long long w; long n = 0; int c;
    while (fscanf(f, "%lld", &w) == 1) {
        if (w < INT32_MIN || w > INT32_MAX) { fprintf(stderr, "word %ld in program file doesn't fit in 32 bits\n", n); return 2; }
        if (n >= N) { fprintf(stderr, "program doesn't fit in memory (max %d words)\n", N); return 2; }
        mem[n++] = (int32_t)w;
    }
    if (!feof(f)) { fprintf(stderr, "bad token in program file after %ld words\n", n); return 2; }
    fclose(f);
    long long steps = 0; int64_t pc = 0;
    while (pc >= 0 && pc <= N - 3) {
        if (steps >= limit) { fprintf(stderr, "timeout after %lld steps\n", steps); fflush(stdout); return 3; }
        int32_t a = mem[pc], b = mem[pc + 1], cc = mem[pc + 2];
        if (a < 0 || a >= N || b < 0 || b >= N) { fprintf(stderr, "error at %lld: operand outside memory (%d %d %d)\n", (long long)pc, a, b, cc); fflush(stdout); return 4; }
        if (a == IN) { fprintf(stderr, "error at %lld: IN used as first operand (%d %d %d)\n", (long long)pc, a, b, cc); fflush(stdout); return 4; }
        int32_t vb;
        if (b == IN) { c = getchar(); vb = (c == EOF) ? -1 : (c & 255); }
        else if (b == OUT) vb = 0;
        else vb = mem[b];
        int32_t va = (a == OUT) ? 0 : mem[a];
        int32_t r = (int32_t)((uint32_t)va - (uint32_t)vb);
        if (a == OUT) putchar(r & 255); else mem[a] = r;
        steps++;
        if (r < 0) pc = cc; else pc = pc + 3;
    }
    fflush(stdout);
    if (getenv("VM_STATS")) fprintf(stderr, "halted after %lld steps\n", steps);
    return 0;
}
