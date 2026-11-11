# Design log

One page: what we built, in what order, what failed, and what we kept.

## 1. Choosing the shape of the compiler

- **Port first, optimise later.** Tier 3 has to be the same compiler written in v1, a
  language with no strings, no division and no mutual recursion. So the Python compiler
  (`tier2/v1c.py`) was written from the start in a way that ports line by line: plain
  integer tables, one tree, two passes. The payoff is a test oracle: for any program,
  `v1c.py` and the self-compiled compiler must print byte-identical output.
- **Fixed frames, not a stack frame per call.** v1 lets a function call only itself or
  functions defined before it. So when `f` calls `g`, `g` cannot already be running
  unless `g` is `f`. Every function keeps its variables in fixed cells (direct addressing,
  no pointer arithmetic), and only a call of a function to itself pushes and pops.
- **Two passes instead of back-patching.** Pass 1 generates everything but only counts;
  pass 2 generates again with every label known and prints. No fix-up table, no code
  buffer, which kept the Tier 3 port small.
- **Zero data stays out of the file.** Globals, arrays and frames live after the code
  and constants. Memory beyond the file is zero, so a 60,000-word array costs nothing.

## 2. Bugs we hit, and the fixes

| Symptom | Cause | Fix |
|---|---|---|
| Every program with a call printed nothing and halted | The return address was stored with the wrong sign, so returns jumped to a negative address (which halts) | Callers store minus the address; the return writes `0 - nret` into its jump |
| Patched loads and returns jumped into data | Field offsets in the self-modifying sequences were off by a few words | Offsets recomputed from the instruction layout (`pc + 7` for a load's b field, `pc + 8` for a return's c field) |
| `hanoi` printed wrong moves | A self-call passed `via` and `to` swapped: copying arguments into our own parameters overwrote a parameter before it was read | Variable arguments of a self-call are copied to temporaries first |
| `bigmul` printed `00` for 0 x 0 | The highest-digit index was not reset before the scan | Reset to 0 |
| One test took 45M of the 100M steps | `i * 7` and `s * 31` went through the 32-round multiply routine (about 350 steps each) | A literal factor becomes doublings and additions (about 12 instructions); now 6.6M steps |
| `v1c.py` crashed on one 29,000-term sum | Python's recursion limit | The compiler runs in a thread with a 255 MB stack |
| Tier 3 ran out of stack on a 5,000-term sum after its tables grew | The tables took memory from the stack | Grew only the tables a 60 KB file can fill; measured the limit (about 4,000 terms) |
| Tier 3 still crashed on a 9,900-term sum (`IN used as first operand`) | The real cause: code generation recursed down the sum's chain of left operands, three saved frames (about 65 words) per term, until the stack reached the IN/OUT cells at the top of memory | `gx` walks that chain with a loop. A 29,900-term sum (60 KB) now compiles in 0.98B steps. Constants are found by hashing and temps by one comparison, so long expressions no longer cost quadratic steps |

## 3. Things we chose not to do

- **No register-style optimiser.** It would make Tier 3 much larger and the bootstrap
  riskier; the step budgets (10^8 per test, 10^10 per self-compile) leave plenty of room.
- **No faster general multiply.** The routine already skips the multiplier's leading zero
  bits. The heaviest test (`bignum`, 33M of 100M steps) spends its time on `k * width` in
  array indexes; a faster routine would add code to both compilers for a test that passes.

## 4. How we checked it

- A reference interpreter (`tools/v1ref.py`) written from the brief alone.
- 81 hand-written programs and thousands of random ones: compiled, run on the machine,
  compared byte for byte with the reference interpreter. 56 invalid programs must be
  rejected by the reference interpreter.
- The self-compiled compiler on the same tests, and its output compared with `v1c.py`'s.
- A 59.8 KB program (the brief allows 60 KB) through Tier 3: 197M steps, identical output.
- Generated worst cases (6,500 globals, 4,500 arrays, deep nesting) through both compilers.
- Everything again on the organisers' own `VM_tier1and2` and `VM_tier3` in Ubuntu 24.04.
