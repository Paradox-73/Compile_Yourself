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

## 3. Things we chose not to do

- **No register-style optimiser.** It would make Tier 3 much larger and the bootstrap
  riskier; the step budgets (10^8 per test, 10^10 per self-compile) leave plenty of room.
- **No early exit in the multiply routine.** Skipping leading zero bits saves about one
  instruction per round, not worth the extra code in both compilers.

## 4. How we checked it

- A reference interpreter (`tools/v1ref.py`) written from the brief alone.
- 68 hand-written programs and thousands of random ones: compiled, run on the machine,
  compared byte for byte with the reference interpreter. 53 invalid programs must be
  rejected.
- The self-compiled compiler on the same tests, and its output compared with `v1c.py`'s.
- A 59.8 KB program (the brief allows 60 KB) through Tier 3: 214M steps, identical output.
- Everything again on the organisers' own `VM_tier1and2` and `VM_tier3` in Ubuntu 24.04.
