# Design log

What we tried, what failed, and what we kept.

- **Fixed frames instead of a stack for every call.** v1 only lets a function call itself
  or earlier functions, so a frame can only be in use twice when a function calls itself.
  Fixed cells make every variable access direct; only self-calls push and pop.
- **Return address sign.** The first version stored the return address with the wrong
  sign, so every function returned to a negative address and the program halted silently
  after the first call. Callers now store minus the address; the return writes
  `0 - nret` into its jump.
- **Two passes, no back-patching.** Pass 1 only measures; pass 2 writes with every
  address known. This keeps the Tier 3 port free of a fix-up table.
