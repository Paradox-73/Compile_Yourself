# Compile Yourself

A v1 compiler for a machine with one instruction, and the climb from hand-made
machine code to a compiler that compiles itself.

The machine has one instruction, `a b c`: `mem[a] -= mem[b]`, then jump to `c` if the
result is negative. It has no add, no move, no pointers and no calls; all of those are
built here out of that one instruction.

## Layout

| Path | What it is |
|---|---|
| `tier1/` | The four machine programs: `echo.txt`, `reverse.txt`, `bigmul.txt`, `hanoi.txt` |
| `tier2/v1c.py` | The v1 compiler (Python 3, no dependencies). How to run it: `tier2/BUILD.md` |
| `tier3/tier3.v1` | The v1 compiler written in v1 |
| `tools/vm.c` | A local copy of the machine for fast testing |
| `tests/` | v1 test programs |

## Quick start

```
gcc -O2 -o tools/vm tools/vm.c
python3 tier2/v1c.py < tests/ex1.v1 > ex1.txt
tools/vm ex1.txt < /dev/null        # prints 6
```

## How the compiler works

- **Arithmetic.** `x += y` is three instructions through a zero cell `Z`:
  `Z y; x Z; Z Z`. A jump is `M1 Z L`, where `M1` always holds -1.
- **Multiplication.** A shared routine does 32 rounds of "double the result, add the
  multiplicand if the top bit of the multiplier is set, double the multiplier".
- **Comparisons.** `a < b` compares the true signed values: when the signs differ, the
  answer is the sign of `a`; when they match, `a - b` cannot overflow.
- **Pointers.** An array access writes the element's address into the operand field of
  the instruction that reads or writes it, then runs that instruction.
- **Calls.** v1 lets a function call only itself or functions defined before it, so
  every function's variables live in fixed cells. A function calling itself first
  pushes the cells it still needs onto a stack and pops them after the call. The
  return address is written into the jump at the end of the called function.

Status and the design log are kept up to date as the tiers land.
