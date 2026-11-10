<div align="center">

<img src="docs/figures/banner.svg" alt="Compile Yourself. One instruction, a compiler, and a compiler that compiles itself. Synergy '26 Low Level Hackathon, IIIT Bangalore, Compilers track. Team Claude laggye." width="100%">

<br>
<br>

[![Python 3](https://img.shields.io/badge/Python-3.8%2B-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![C99](https://img.shields.io/badge/Local%20VM-C99-555555?style=for-the-badge&logo=c&logoColor=white)](tools/vm.c)
[![No dependencies](https://img.shields.io/badge/Dependencies-none-1baf7a?style=for-the-badge)](#quick-start)
<br>
[![One instruction](https://img.shields.io/badge/Instruction%20set-subleq-4fd1e0?style=for-the-badge&labelColor=0b1016)](#the-machine)
[![Tier 1](https://img.shields.io/badge/Tier%201-done-1baf7a?style=for-the-badge&labelColor=0b1016)](#status)
[![Tier 2](https://img.shields.io/badge/Tier%202-working-1baf7a?style=for-the-badge&labelColor=0b1016)](#status)
[![Bootstrap C2 = C3](https://img.shields.io/badge/Bootstrap-C1%20%3D%20C2%20%3D%20C3-1baf7a?style=for-the-badge&labelColor=0b1016)](#tier-3-the-bootstrap)

**[Repository](https://github.com/Paradox-73/Compile_Yourself)** &nbsp;|&nbsp; [Compiler](tier2/v1c.py) &nbsp;|&nbsp; [Build and run](tier2/BUILD.md) &nbsp;|&nbsp; [Design log](docs/design_log.md)

</div>

This repository is the entry of team Claude laggye for problem COMP01, "Compile Yourself", in the Compilers track of the Synergy '26 Low Level Hackathon at IIIT Bangalore. The target is a computer with a single instruction: subtract, and jump if the answer is negative. It has no add, no move, no pointers and no calls. We build all of those out of that one instruction, then write a compiler for the small language v1, then rewrite that compiler in v1 so that it compiles itself.

**Contents:**
[Status](#status) ·
[Quick start](#quick-start) ·
[Repository layout](#repository-layout) ·
[The machine](#the-machine) ·
[Building blocks](#building-blocks) ·
[Memory layout](#memory-layout) ·
[Expressions and comparisons](#expressions-and-comparisons) ·
[Multiplication](#multiplication) ·
[Arrays and pointers](#arrays-and-pointers) ·
[Function calls and recursion](#function-calls-and-recursion) ·
[The compiler pipeline](#the-compiler-pipeline) ·
[Tier 1 programs](#tier-1-programs) ·
[Tier 3: the bootstrap](#tier-3-the-bootstrap) ·
[Testing](#testing) ·
[Language choices](#language-choices) ·
[Limitations](#limitations) ·
[Team](#team)

## Status

| Tier | What it is | State |
|---|---|---|
| 1 | Four machine programs: `echo`, `reverse`, `bigmul`, `hanoi` | done: hanoi n=8 in 88k steps, two 40-digit numbers in 0.69M steps |
| 2 | `tier2/v1c.py`: v1 to machine code, in Python | 80 hand-written programs and 1,300+ random ones match the reference interpreter byte for byte; heaviest test 33M of the 100M steps |
| 3 | `tier3/tier3.v1`: the same compiler written in v1 | done: compiles itself in 151M steps (limit 10^10); C1, C2 and C3 are byte-identical |

This table is updated as each tier lands.

## Quick start

### 1. Get the code

```
git clone https://github.com/Paradox-73/Compile_Yourself.git
cd Compile_Yourself
```

### 2. Build the local machine

`tools/vm.c` follows the machine described in the brief and runs about a billion steps a minute. The official `vm` gives the same results.

```
gcc -O2 -o tools/vm tools/vm.c          # Linux, macOS (clang works too), Windows with MinGW
```

### 3. Compile and run a v1 program

```
python3 tier2/v1c.py < tests/ex1.v1 > ex1.txt
tools/vm ex1.txt < /dev/null            # prints 6
VM_STATS=1 tools/vm ex1.txt < /dev/null # also prints the step count on stderr
```

`v1c.py` reads a v1 program on standard input and writes the machine program, as whitespace-separated decimal words, on standard output. It needs Python 3 and nothing else.

## Repository layout

| Path | What it is |
|---|---|
| `tier1/` | `echo.txt`, `reverse.txt`, `bigmul.txt`, `hanoi.txt`: the Tier 1 machine programs |
| `tier1/src/` | The v1 sources the Tier 1 programs are compiled from |
| `tier2/v1c.py` | The v1 compiler (lexer, parser, two-pass code generator) |
| `tier2/BUILD.md` | How to run the compiler |
| `tier3/tier3.v1` | The v1 compiler written in v1 |
| `tools/vm.c` | Local copy of the machine, for fast tests |
| `tests/` | v1 test programs with inputs and expected outputs |
| `docs/design_log.md` | What we tried, what failed, and why |

## The machine

Memory is 1,048,576 signed 32-bit words. An instruction is three words `a b c`:

```
r = mem[a] - mem[b]
mem[a] = r
if r < 0: pc = c   else: pc = pc + 3
```

The program loads at address 0 and every other word starts at 0. Reading address `N-2` gives the next input byte (or -1 at the end); writing to `N-1` prints a byte. Jumping outside memory halts. Code and data share memory, so a program can rewrite its own instructions, and that is how pointers and returns work here.

## Building blocks

Two cells hold fixed values for the whole run: `Z` is 0 between instructions and `M1` is -1. Every other operation is a short sequence:

| Operation | Instructions | Why it works |
|---|---|---|
| `jump L` | `M1 Z L` | -1 - 0 is negative, so it always jumps, and `M1` keeps -1 |
| `x = 0` | `x x` | x - x = 0, never negative, falls through |
| `x -= y` | `x y` | the instruction itself |
| `x += y` | `Z y` · `x Z` · `Z Z` | Z becomes -y, x - (-y) = x + y, Z is cleared again |
| `x = y` | `x x` · `Z y` · `x Z` · `Z Z` | clear, then add |
| `x = -y` | `x x` · `x y` | 0 - y |
| `if x < 0 goto L` | `x Z L` | x - 0 = x, so x is unchanged |
| read a byte | `x x` · `Z IN` · `x Z` · `Z Z` | IN gives the byte; -1 at end of input |
| print `x` | `T T` · `T x` · `OUT T` | the machine prints the low 8 bits of 0 - (-x) |

Every instruction that is not a jump names the next instruction as its `c`, so both outcomes of the comparison carry on in a straight line.

## Memory layout

```
0                code: start-up, every function, the multiply routine
                 initialised cells: constants (-1, 1, 32, label addresses, ...) and the stack pointer
data_base        Z, scratch cells, globals, arrays, one fixed frame per function     <- all zero, not in the file
stack_base       the recursion stack, growing upwards
N-2, N-1         IN, OUT
```

Only code and constants are written to the output file. Globals, arrays and frames start at zero, which is exactly what memory beyond the file holds, so a 60,000-word array costs nothing in file size.

## Expressions and comparisons

Expressions are compiled straight into the cell that needs the result. A variable or a literal needs no code at all (literals live in the constant pool); anything else goes into a temporary cell of the current function. `a + b` into `d` is five instructions: `d d · Z a · Z b · d Z · Z Z`.

Comparisons follow the brief's rule that `<` compares true signed values, even when `a - b` would overflow:

```
if a < 0:  if b >= 0: true           else: test a - b (both negative, no overflow)
else:      if b <  0: false          else: test a - b (both non-negative, no overflow)
```

`==` subtracts and checks that the difference is neither negative nor positive; wrap-around cannot make two different values equal. Inside `if` and `while`, comparisons become jumps and no 0/1 value is ever built.

## Multiplication

There is no multiply, so one shared routine computes `a * b` modulo 2^32 in 32 rounds:

```
r = 0
repeat 32 times:
    r = r + r                 # shift the result left
    if b < 0: r = r + a       # the top bit of b is set
    b = b + b                 # move the next bit of b to the top
```

Reading the top bit is just "is b negative", which the machine tests for free. The routine works for any signs because it is exact arithmetic modulo 2^32.

## Arrays and pointers

The machine has no indirect addressing, so the compiler writes the address into the instruction that needs it. To read `a[i]`:

```
T2 = -(base_of_a + i)
field = 0 ; field -= T2        # field is the b operand of the next instruction
Z [field]                      # Z = -mem[base_of_a + i]
d d ; d Z ; Z Z                # d = mem[base_of_a + i]
```

A store patches three operand fields (two to clear the word, one to write it) the same way.

## Function calls and recursion

In v1 a function may call only itself or functions defined earlier. So when `f` calls `g`, `g` cannot already be running unless `g` is `f`. That lets every function keep its parameters, locals and temporaries in fixed cells, which the code reads and writes directly with no pointer arithmetic.

- **A call** evaluates the arguments left to right into temporaries, copies them into the callee's parameter cells, stores minus the return address in the callee's `nret` cell, and jumps.
- **A return** puts the value in `RV`, writes `0 - nret` into the jump field of the function's last instruction, and runs it.
- **A call of a function to itself** first pushes `nret`, the parameters, the locals and the live temporaries onto the stack, and pops them after the call returns. Only self-calls pay this cost.

## The compiler pipeline

1. **Lexer and parser** build a tree of statements and expressions, resolving each name to a global, a local, an array or a function as they go. Blocks have their own scope.
2. **Pass 1** generates the code but writes nothing; it only learns how big the code is and where every label lands.
3. **Pass 2** generates the same code again, now with every address known, and writes it.

Two passes mean no back-patching table and no code buffer, which keeps the Tier 3 port small.

## Tier 1 programs

The four programs are written in v1 (`tier1/src/`) and compiled with `v1c.py`. The brief allows any route to the machine code, and this one keeps them readable.

| Program | Idea | Worst case within 10^8 steps |
|---|---|---|
| `echo` | read bytes until -1, print each | a few steps per byte |
| `reverse` | store up to 1000 bytes, print them backwards | well under 1M steps |
| `bigmul` | 40-digit numbers as digit arrays, schoolbook multiply, carries by repeated subtraction (no division) | 0.69M steps for 40 x 40 digits |
| `hanoi` | the recursive solution, two letters and a newline per move | 88k steps for n = 8 |

## Tier 3: the bootstrap

`tier3/tier3.v1` is a line-by-line port of `v1c.py` into v1: the same lexer, the same tree, the same two passes, with arrays in place of Python lists and character codes in place of strings. Because it is the same algorithm, it must print exactly what `v1c.py` prints for any input. That gives a strong check: `v1c.py X` and `C1 X` must be byte-identical for every test program `X`, and then `C1 = C2 = C3` follows.

```
python3 tier2/v1c.py < tier3/tier3.v1 > C1.txt       # Step 1
tools/vm C1.txt 10000000000 < tier3/tier3.v1 > C2.txt  # Step 3: about 151M steps
tools/vm C2.txt 10000000000 < tier3/tier3.v1 > C3.txt
cmp C1.txt C2.txt && cmp C2.txt C3.txt                 # all three identical
```

v1 has no mutual recursion, so every recursive part of the compiler is a single function that calls itself: `pexp(level)` parses all four precedence levels, `pstmts()` parses nested blocks, and `gx(mode, ...)` generates expressions, conditions and calls.

## Testing

- **Reference interpreter.** `tools/v1ref.py` runs v1 directly, following the brief word for word.
- **Corpus.** Hand-written programs for every operator, precedence level, wrap-around edge, comparison overflow case, recursion 1,000 deep, 8 parameters and shadowing.
- **Random programs.** A generator writes valid v1 programs; each is compiled, run on the machine and compared byte for byte with the reference interpreter.
- **Invalid programs.** 56 programs that break a rule of the brief, each with the error it must give.

| Check | Result |
|---|---|
| `v1c.py` on the corpus and random programs | 80 corpus + 1,300 random: all match the reference interpreter |
| Self-compiled compiler (C1) on the same | 80 corpus + 1,300 random: all match |
| C1's output vs `v1c.py`'s output | byte-identical on every corpus program |
| Bootstrap on the organisers' `VM_tier3` (Ubuntu 24.04) | C1 = C2 = C3, 150,629,572 steps |
| 59.8 KB input to C1 | 214M steps (limit 10^10), output identical to `v1c.py` |
| Tier 1 programs on the organisers' `VM_tier1and2` | all correct |

```
python3 tools/run_tests.py --compiler "python3 tier2/v1c.py" --gen 300
python3 tools/run_tests.py --compiler "/abs/path/vm /abs/path/C1.txt 10000000000" --gen 300
python3 tools/stress.py --c1 C1.txt     # worst-case sizes: both compilers, same output
```

## Language choices

The brief leaves a few points open. Where it does, we chose the C-like reading and asked the organisers:

- a `var` declared inside a block is visible until the end of that block, and an inner block may declare the same name again;
- in `a[i] = e;` the index is evaluated before `e`.

## Limitations

- Multiplying two variables costs up to about 350 steps (fewer when the multiplier is small); a literal factor becomes a dozen additions.
- A function calling itself saves its whole frame, not only the cells still needed after the call.
- The brief leaves two scope questions open. Both compilers accept a local used after the block that declared it (a live local or a global of that name wins first), and a name declared twice in one block (the second declaration hides the first). `tests/lenient/` covers both.
- `tier3.v1` keeps its tables in fixed arrays: 60,000 tree nodes, 8,000 globals, 6,000 arrays, 256 temporaries per function. It generates code recursively, so one flat expression of more than about 4,000 operators runs out of stack (2,000 nested `if`s and 1,000 nested parentheses are fine). `v1c.py` has no such limits.

## Team

Team Claude laggye, Synergy '26 Low Level Hackathon, IIIT Bangalore:

- Kanav Bhardwaj
- Bhavya Jain
- Aaryan Antala
