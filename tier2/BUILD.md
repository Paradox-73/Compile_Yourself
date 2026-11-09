# Building and running the Tier 2 compiler

The compiler is one Python 3 file with no dependencies, so there is nothing to build.

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
