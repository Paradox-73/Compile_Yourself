# Building and running the Tier 2 compiler

The compiler is one Python 3 file with no dependencies, so there is nothing to build.
Tested with Python 3.12 (the `python3` of Ubuntu 24.04, and 3.12 on Windows).

```
python3 tier2/v1c.py < program.v1 > program.txt
```

It reads a v1 program on standard input and writes the machine program, as
whitespace-separated decimal words, to standard output. On an invalid program it prints
`v1c: line N: ...` on standard error and exits with status 1.

Run the result on the machine:

```
./vm program.txt < input.txt
```

`./vm` is the organisers' machine. Our local copy builds with `gcc -O2 -o tools/vm tools/vm.c`
and runs as `tools/vm program.txt < input.txt`.

Smoke test (prints `6`):

```
python3 tier2/v1c.py < tests/ex1.v1 > ex1.txt && ./vm ex1.txt
```

Tier 3, step 1 (compile the Tier 3 compiler with this one):

```
python3 tier2/v1c.py < tier3/tier3.v1 > C1.txt
```

More detail, the bootstrap steps and the tests: [README](../README.md).
