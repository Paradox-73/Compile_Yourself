# Demo guide

Live demo: **14 Nov 2026, 09:00 IST**. The judges ask us to run our programs and our
compiler, explain how pointer access and function calls work, and change a rule on the
spot. "Work that a team cannot explain may be disregarded."

**Lead: Aaryan Antala.** Aaryan drives the laptop and gives the walkthrough.
Kanav and Bhavya take questions on their parts and do the live rule change with Aaryan.
Everyone reads this whole page and does drill 1 before 13 Nov.

## 1. Before the demo (13 Nov)

1. Fresh clone, build the VM, run every command in section 2 once. Nothing should be new
   on the day.
2. Have both machines ready: the laptop with Docker (`ubuntu:24.04`) and the official
   `VM_tier1and2` / `VM_tier3` copied in; a terminal with large font; this page open.
3. Each person does at least one drill from section 5 end to end, including the tests.

```
git clone https://github.com/Paradox-73/Compile_Yourself.git && cd Compile_Yourself
gcc -O2 -o vm tools/vm.c            # or use the official VM inside ubuntu:24.04
```

## 2. The demo, in order (about 8 minutes)

| Step | Say | Run |
|---|---|---|
| 1 | "One instruction: subtract, jump if negative. Everything else we built from it." | `cat README.md` top table |
| 2 | Tier 1: four hand-built programs | `printf '3\n' \| ./vm tier1/hanoi.txt` · `printf '123\n456\n' \| ./vm tier1/bigmul.txt` |
| 3 | Tier 2: the compiler in Python | `python3 tier2/v1c.py < tests/ex1.v1 > ex1.txt && ./vm ex1.txt` prints `6` |
| 4 | Tier 3: the compiler compiles itself | the four commands below |
| 5 | Testing: how we know it is right | `python3 tools/run_tests.py --compiler "python3 tier2/v1c.py" --gen 50` |

```
python3 tier2/v1c.py < tier3/tier3.v1 > C1.txt        # our Python compiler builds C1
./vm C1.txt 10000000000 < tier3/tier3.v1 > C2.txt     # C1 compiles tier3.v1 (147M steps)
./vm C2.txt 10000000000 < tier3/tier3.v1 > C3.txt     # C2 compiles it again
cmp C2.txt C3.txt && cmp C1.txt C2.txt && echo "C1 = C2 = C3"
```

Point out: C1 is equal to C2 too, because tier3.v1 is a line-by-line port of v1c.py. That is
our strongest test: for any program, both compilers print the same bytes.

## 3. The two things they will ask: explain in your own words

**The building blocks.** Two cells never change: `Z` is 0, `M1` is -1.
- jump to L: `M1 Z L` (-1 - 0 is negative, so it always jumps)
- x += y: `Z y`, `x Z`, `Z Z` (Z becomes -y, x - (-y) = x + y, Z back to 0)
- if x < 0 goto L: `x Z L` (x - 0 leaves x unchanged)

**Pointer access (array read `a[i]`).** The machine can only use fixed addresses. So we
compute the element's address, `base + i`, and *write that number into the operand field
of the instruction that does the read*, then run that instruction. Code and data share
memory, so a program may rewrite its own instructions. A store patches three fields the
same way (two to clear the word, one to write the value).
Code: `load_index` / `store_index` in v1c.py, `loadidx` / `storeidx` in tier3.v1.

**Function calls.** In v1 a function can only call itself or a function defined before
it. So if f calls g, g cannot already be running (unless g is f). That lets every function
keep its parameters, locals and temporaries in fixed cells.
- Call: copy the arguments into the callee's parameter cells, store minus the return
  address in the callee's `nret` cell, jump to the callee.
- Return: put the value in `RV`, write `0 - nret` into the jump field of the function's
  last instruction, and run that jump.
- Recursion: only a function calling itself needs a stack. Before the call it pushes
  `nret`, its parameters, locals and live temporaries; after the call it pops them.
Code: `gen_call`, `push`, `pop`, `gen_func` in v1c.py; `gx` mode 5, `push`, `pop`,
`run` in tier3.v1.

**Comparisons.** `a < b` must be right even when `a - b` overflows. If the signs differ,
the negative one is smaller. If the signs match, `a - b` cannot overflow, so test its
sign. Code: `less`.

**Multiplication.** No multiply instruction: 32 rounds of "double the result; if the top
bit of b is set add a; double b". Reading the top bit is "is b negative". A literal factor
becomes a short chain of doublings and additions. Code: `gen_mul`, `mul_const` /
`genmul`, `mulk`.

## 4. Question bank (practise the answers out loud)

| Question | Short answer |
|---|---|
| Why is the output program so small? | Only code and constants are in the file; globals, arrays and frames are zero, and memory past the file is zero. |
| How do you know where a forward jump goes? | Two passes: pass 1 only measures where every label lands, pass 2 writes. |
| How deep can recursion go? | 1000 calls is the rule; our stack grows into free memory (about 400k words). |
| What happens on a self-call with arguments that use our own parameters? | They are copied to temporaries first, so overwriting parameters cannot change them. (We hit this bug in hanoi.) |
| How is v1 without mutual recursion able to have a recursive-descent parser? | Each recursive part is one self-calling function: `pexp(level)`, `pstmts()`, `gx(mode, ...)`. |
| How many steps does the self-compile take? | 147M, limit 10^10. |
| How did you test? | A reference interpreter written from the brief, 80 hand-written programs, thousands of random programs, 56 invalid ones; both compilers; the official VMs. |
| What was hardest? | Getting the self-modifying offsets exact, and the bootstrap: v1 has no strings or division, so names are slices of the source and numbers are printed by subtracting powers of ten. |

## 5. Rule-change drills

Change **both** compilers (v1c.py and tier3.v1), then run:

```
python3 tools/run_tests.py --compiler "python3 tier2/v1c.py" --gen 50
python3 tier2/v1c.py < tier3/tier3.v1 > C1.txt && ./vm C1.txt 10000000000 < tier3/tier3.v1 > C2.txt && cmp C1.txt C2.txt
```

| Drill | What changes | Where in v1c.py | Where in tier3.v1 |
|---|---|---|---|
| 1. New operator `%` (remainder) | precedence like `*`; a routine like multiply (repeated subtraction, or shift-and-subtract) | `parse_term`, `gen_bin`, new routine next to `gen_mul` | `pexp` level 2 (`tp == 37`), `gx` binary part, routine next to `genmul` |
| 2. Machine jumps on `r <= 0` instead of `< 0` | every "if negative" test needs the zero case; jumps still work with `M1` | `jlt`, `less`, `equal`, `gen_cond`, `gen_mul` | `jlt`, `less`, `equal`, `gx` mode 2, `genmul` |
| 3. IN and OUT move to other addresses | two constants | `IN`, `OUT` at the top | literals 1048574 and 1048575 in `gx` |
| 4. Add `for (init; cond; step) { }` | parse it into the same tree as a `while` | `parse_stmt` | `pstmts` (new keyword via `word(...)`) |
| 5. Add `&&` and `||` | short-circuit with labels inside conditions | `parse_expr`, `gen_cond` | `pexp` level 0, `gx` mode 2 |
| 6. Comparisons become unsigned | flip the top bit of both sides, then compare as signed | `less` | `less` |
| 7. putc prints the number in decimal | call a print routine (subtract powers of ten, like tier3's `putnum`) | `gen_expr_into` putc branch | `gx` kind 8 |

Remember: the judges care that we understand the change, not that we finish every drill.
Say what you would change and why before typing.
