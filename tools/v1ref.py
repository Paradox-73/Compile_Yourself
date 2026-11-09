"""Reference interpreter for v1.

usage: python tools/v1ref.py prog.v1 [--max-ops N] [--stats] < input > output

Exit codes: 0 main returned, 1 compile error, 3 operation budget exceeded,
4 undefined behaviour. Programs are checked strictly so that tests never rely
on behaviour the language leaves open; see the error messages for each rule.
"""
import re
import sys
import threading

MAX_SOURCE = 60000
MAX_FUNCS = 200
MAX_NAME = 24
MAX_LITERAL = 2147483647
MAX_DEPTH = 1000          # nested calls below main
MEMORY_WORDS = 1 << 20
DEFAULT_MAX_OPS = 10_000_000
KEYWORDS = {"var", "array", "func", "if", "else", "while", "return"}
BUILTINS = {"getc": 0, "putc": 1}
B = 0x80000000
M = 0xFFFFFFFF


class V1Error(Exception):
    kind, code = "error", 1

    def __init__(self, line, msg):
        super().__init__(f"line {line}: {self.kind}: {msg}" if line else f"{self.kind}: {msg}")
        self.output = b""
        self.ops = 0


class CompileError(V1Error):
    kind, code = "compile error", 1


class BudgetExceeded(V1Error):
    kind, code = "operation budget exceeded", 3


class UndefinedBehaviour(V1Error):
    kind, code = "undefined behaviour", 4


TOKEN = re.compile(r"[ \t\r\n]+|//[^\n]*|[A-Za-z_][A-Za-z0-9_]*|[0-9][A-Za-z0-9_]*|<=|>=|==|!=|[-+*<>=(){}\[\];,]|.", re.S)


def tokenize(text):
    toks, line = [], 1
    for m in TOKEN.finditer(text):
        s = m.group()
        c = s[0]
        if c in " \t\r\n":
            line += s.count("\n")
        elif s.startswith("//"):
            pass
        elif c.isalpha() or c == "_":
            if len(s) > MAX_NAME:
                raise CompileError(line, f"name longer than {MAX_NAME} characters: {s}")
            toks.append((s if s in KEYWORDS else "name", s, line))
        elif c.isdigit():
            if not s.isdigit():
                raise CompileError(line, f"bad number: {s}")
            if len(s) > 1 and c == "0":
                raise CompileError(line, f"number with a leading zero: {s}")
            if int(s) > MAX_LITERAL:
                raise CompileError(line, f"literal larger than {MAX_LITERAL}: {s}")
            toks.append(("num", int(s), line))
        elif len(s) == 1 and s not in "-+*<>=(){}[];," :
            raise CompileError(line, f"unexpected character {s!r}")
        else:
            toks.append((s, s, line))
    toks.append(("end", None, line))
    return toks


class Func:
    def __init__(self, name, nparams, line):
        self.name, self.nparams, self.line = name, nparams, line
        self.nslots = nparams
        self.body = None


class State:
    def __init__(self, inp, max_ops):
        self.inp, self.ip = inp, 0
        self.out = bytearray()
        self.budget = [max_ops]
        self.max_ops = max_ops
        self.depth = [0]


class Compiler:
    def __init__(self, src, st):
        if len(src) > MAX_SOURCE:
            raise CompileError(0, f"source is {len(src)} bytes, more than {MAX_SOURCE}")
        self.toks = tokenize(src.decode("latin-1"))
        self.pos = 0
        self.st = st
        self.globals = {}      # name -> ("var", index) | ("array", list) | ("func", Func)
        self.gvals = []
        self.array_words = 0
        self.nfuncs = 0
        self.fn = None
        self.scopes = []

    # token helpers
    def peek(self, k=0):
        return self.toks[self.pos + k]

    def take(self, kind):
        t = self.toks[self.pos]
        if t[0] != kind:
            what = "end of file" if t[0] == "end" else repr(t[1])
            raise CompileError(t[2], f"expected {kind!r}, found {what}")
        self.pos += 1
        return t

    def check_new_name(self, name, line):
        if name in BUILTINS:
            raise CompileError(line, f"'{name}' is built in and cannot be redefined")
        g = self.globals.get(name)
        if g and (g[0] == "func" or not self.scopes):
            raise CompileError(line, f"'{name}' already declared at top level")

    # program
    def program(self):
        while self.peek()[0] != "end":
            kind, _, line = self.peek()
            if kind == "var":
                self.pos += 1
                name = self.take("name")[1]
                self.take(";")
                self.check_new_name(name, line)
                self.globals[name] = ("var", len(self.gvals))
                self.gvals.append(0)
            elif kind == "array":
                self.pos += 1
                name = self.take("name")[1]
                self.take("[")
                size = self.take("num")[1]
                self.take("]")
                self.take(";")
                self.check_new_name(name, line)
                if size == 0:
                    raise CompileError(line, "array size must be positive")
                self.array_words += size
                if self.array_words > MEMORY_WORDS:
                    raise CompileError(line, "arrays do not fit in the machine's memory")
                self.globals[name] = ("array", [0] * size)
            elif kind == "func":
                self.function()
            else:
                raise CompileError(line, f"expected a declaration, found {self.peek()[1]!r}")
        main = self.globals.get("main")
        if not main or main[0] != "func":
            raise CompileError(0, "no function main")
        if main[1].nparams:
            raise CompileError(main[1].line, "main must take no parameters")
        return main[1]

    def function(self):
        line = self.take("func")[2]
        name = self.take("name")[1]
        self.check_new_name(name, line)
        self.nfuncs += 1
        if self.nfuncs > MAX_FUNCS:
            raise CompileError(line, f"more than {MAX_FUNCS} functions")
        self.take("(")
        params = []
        if self.peek()[0] != ")":
            while True:
                p, _, pl = self.take("name")
                params.append(self.take_name_for_local(pl, params))
                if self.peek()[0] != ",":
                    break
                self.pos += 1
        self.take(")")
        if len(params) > 8:
            raise CompileError(line, "more than 8 parameters")
        fn = Func(name, len(params), line)
        self.globals[name] = ("func", fn)
        self.fn = fn
        self.scopes = [{p: i for i, p in enumerate(params)}]
        body = self.block(new_scope=False)
        self.scopes = []
        fn.body = body

    def take_name_for_local(self, line, existing):
        name = self.toks[self.pos - 1][1]
        if name in BUILTINS:
            raise CompileError(line, f"'{name}' is built in and cannot be redefined")
        g = self.globals.get(name)
        if g and g[0] == "func":
            raise CompileError(line, f"'{name}' is a function name")
        if name in existing:
            raise CompileError(line, f"parameter '{name}' declared twice")
        return name

    # statements
    def block(self, new_scope=True):
        self.take("{")
        if new_scope:
            self.scopes.append({})
        stmts = []
        while self.peek()[0] != "}":
            stmts.append(self.statement())
        self.pos += 1
        if new_scope:
            self.scopes.pop()
        if not stmts:
            return lambda f: None
        if len(stmts) == 1:
            return stmts[0]

        def run(f):
            for s in stmts:
                r = s(f)
                if r is not None:
                    return r
        return run

    def statement(self):
        kind, val, line = self.peek()
        bud = self.st.budget
        over = self.over

        if kind == "var":
            self.pos += 1
            self.take("name")
            name = self.toks[self.pos - 1][1]
            self.take(";")
            if name in BUILTINS or (self.globals.get(name, ("",))[0] == "func"):
                raise CompileError(line, f"'{name}' cannot name a local variable")
            if name in self.scopes[-1]:
                raise CompileError(line, f"'{name}' declared twice in the same block")
            slot = self.fn.nslots
            self.fn.nslots += 1
            self.scopes[-1][name] = slot

            def run(f):
                bud[0] -= 1
                if bud[0] < 0:
                    over()
                f[slot] = None
            return run

        if kind == "if":
            self.pos += 1
            self.take("(")
            cond, c = self.expr()
            self.take(")")
            then = self.block()
            if self.peek()[0] == "else":
                self.pos += 1
                if self.peek()[0] != "{":
                    raise CompileError(self.peek()[2], "'else' must be followed by a block")
                other = self.block()
            else:
                other = None
            c += 1

            def run(f):
                bud[0] -= c
                if bud[0] < 0:
                    over()
                if cond(f):
                    return then(f)
                if other is not None:
                    return other(f)
            return run

        if kind == "while":
            self.pos += 1
            self.take("(")
            cond, c = self.expr()
            self.take(")")
            body = self.block()
            c += 1

            def run(f):
                while True:
                    bud[0] -= c
                    if bud[0] < 0:
                        over()
                    if not cond(f):
                        return None
                    r = body(f)
                    if r is not None:
                        return r
            return run

        if kind == "return":
            self.pos += 1
            if self.peek()[0] == ";":
                raise CompileError(line, "return needs a value")
            e, c = self.expr()
            self.take(";")
            c += 1

            def run(f):
                bud[0] -= c
                if bud[0] < 0:
                    over()
                return e(f)
            return run

        if kind != "name":
            raise CompileError(line, f"expected a statement, found {val!r}")
        nxt = self.peek(1)[0]
        if nxt == "(":
            e, c = self.primary()
            self.take(";")
            c += 1

            def run(f):
                bud[0] -= c
                if bud[0] < 0:
                    over()
                e(f)
            return run
        if nxt == "=":
            self.pos += 2
            e, c = self.expr()
            self.take(";")
            c += 1
            loc = self.lookup_local(val)
            if loc is not None:
                def run(f):
                    bud[0] -= c
                    if bud[0] < 0:
                        over()
                    f[loc] = e(f)
                return run
            g = self.global_of(val, "var", line)
            gv, gi = self.gvals, g[1]

            def run(f):
                bud[0] -= c
                if bud[0] < 0:
                    over()
                gv[gi] = e(f)
            return run
        if nxt == "[":
            arr = self.array_of(val, line)
            self.pos += 2
            ix, c1 = self.expr()
            self.take("]")
            self.take("=")
            e, c2 = self.expr()
            self.take(";")
            c = c1 + c2 + 1
            n = len(arr)

            def run(f):
                bud[0] -= c
                if bud[0] < 0:
                    over()
                i = ix(f)
                v = e(f)
                if not 0 <= i < n:
                    raise UndefinedBehaviour(line, f"index {i} outside {val}[{n}]")
                arr[i] = v
            return run
        raise CompileError(line, f"expected '=', '[' or '(' after {val!r}")

    def over(self):
        raise BudgetExceeded(0, f"more than {self.st.max_ops} operations")

    # names
    def lookup_local(self, name):
        for sc in reversed(self.scopes):
            if name in sc:
                return sc[name]
        return None

    def global_of(self, name, want, line):
        g = self.globals.get(name)
        if g is None:
            if name in BUILTINS:
                raise CompileError(line, f"'{name}' is a function")
            raise CompileError(line, f"'{name}' is not declared")
        if g[0] != want:
            raise CompileError(line, f"'{name}' is a {g[0]}, not a {want}")
        return g

    def array_of(self, name, line):
        if self.lookup_local(name) is not None:
            raise CompileError(line, f"'{name}' is a local variable, not an array")
        return self.global_of(name, "array", line)[1]

    # expressions: each returns (closure, static operation count)
    def expr(self):
        l, c = self.additive()
        while self.peek()[0] in ("<", "<=", ">", ">=", "==", "!="):
            op = self.toks[self.pos][0]
            self.pos += 1
            r, c2 = self.additive()
            l, c = CMP[op](l, r), c + c2 + 1
        return l, c

    def additive(self):
        l, c = self.term()
        while self.peek()[0] in ("+", "-"):
            op = self.toks[self.pos][0]
            self.pos += 1
            r, c2 = self.term()
            l, c = (add if op == "+" else sub)(l, r), c + c2 + 1
        return l, c

    def term(self):
        l, c = self.unary()
        while self.peek()[0] == "*":
            self.pos += 1
            r, c2 = self.unary()
            l, c = mul(l, r), c + c2 + 1
        return l, c

    def unary(self):
        if self.peek()[0] == "-":
            self.pos += 1
            e, c = self.unary()
            return (lambda f: ((B - e(f)) & M) - B), c + 1
        return self.primary()

    def primary(self):
        kind, val, line = self.peek()
        self.pos += 1
        if kind == "num":
            return (lambda f: val), 1
        if kind == "(":
            e, c = self.expr()
            self.take(")")
            return e, c
        if kind != "name":
            raise CompileError(line, f"expected an expression, found {'end of file' if kind == 'end' else repr(val)}")
        nxt = self.peek()[0]
        if nxt == "(":
            return self.call(val, line)
        if nxt == "[":
            arr = self.array_of(val, line)
            self.pos += 1
            ix, c = self.expr()
            self.take("]")
            n = len(arr)

            def rd(f):
                i = ix(f)
                if 0 <= i < n:
                    return arr[i]
                raise UndefinedBehaviour(line, f"index {i} outside {val}[{n}]")
            return rd, c + 1
        loc = self.lookup_local(val)
        if loc is not None:
            def rd(f):
                v = f[loc]
                if v is None:
                    raise UndefinedBehaviour(line, f"local '{val}' read before it was assigned")
                return v
            return rd, 1
        gv, gi = self.gvals, self.global_of(val, "var", line)[1]
        return (lambda f: gv[gi]), 1

    def call(self, name, line):
        self.take("(")
        args, c = [], 1
        if self.peek()[0] != ")":
            while True:
                a, ca = self.expr()
                args.append(a)
                c += ca
                if self.peek()[0] != ",":
                    break
                self.pos += 1
        self.take(")")
        if self.lookup_local(name) is not None:
            raise CompileError(line, f"'{name}' is a local variable, not a function")
        st = self.st
        if name in BUILTINS:
            if len(args) != BUILTINS[name]:
                raise CompileError(line, f"{name} takes {BUILTINS[name]} argument(s)")
            if name == "getc":
                def getc(f):
                    i = st.ip
                    if i < len(st.inp):
                        st.ip = i + 1
                        return st.inp[i]
                    return -1
                return getc, c
            a = args[0]

            def putc(f):
                st.out.append(a(f) & 255)
                return 0
            return putc, c
        g = self.globals.get(name)
        if g is None:
            raise CompileError(line, f"function '{name}' is not defined before this call")
        if g[0] != "func":
            raise CompileError(line, f"'{name}' is a {g[0]}, not a function")
        fn = g[1]
        if len(args) != fn.nparams:
            raise CompileError(line, f"{name} takes {fn.nparams} argument(s), got {len(args)}")
        depth = st.depth

        def call(f):
            fr = [a(f) for a in args]
            if depth[0] >= MAX_DEPTH:
                raise UndefinedBehaviour(line, f"recursion deeper than {MAX_DEPTH} calls")
            depth[0] += 1
            fr.extend([None] * (fn.nslots - fn.nparams))
            r = fn.body(fr)
            depth[0] -= 1
            return 0 if r is None else r
        return call, c


def add(l, r):
    return lambda f: ((l(f) + r(f) + B) & M) - B


def sub(l, r):
    return lambda f: ((l(f) - r(f) + B) & M) - B


def mul(l, r):
    return lambda f: ((l(f) * r(f) + B) & M) - B


CMP = {
    "<": lambda l, r: lambda f: 1 if l(f) < r(f) else 0,
    "<=": lambda l, r: lambda f: 1 if l(f) <= r(f) else 0,
    ">": lambda l, r: lambda f: 1 if l(f) > r(f) else 0,
    ">=": lambda l, r: lambda f: 1 if l(f) >= r(f) else 0,
    "==": lambda l, r: lambda f: 1 if l(f) == r(f) else 0,
    "!=": lambda l, r: lambda f: 1 if l(f) != r(f) else 0,
}


def _run(src, inp, max_ops):
    st = State(inp, max_ops)
    try:
        main = Compiler(src, st).program()
        main.body([None] * main.nslots)
    except V1Error as e:
        e.output, e.ops = bytes(st.out), max_ops - st.budget[0]
        raise
    return bytes(st.out), max_ops - st.budget[0]


def run(src, inp=b"", max_ops=DEFAULT_MAX_OPS):
    """Compile and run v1 source bytes; returns (output bytes, operations). Raises V1Error."""
    result = {}

    def target():
        try:
            result["ok"] = _run(src, inp, max_ops)
        except BaseException as e:  # re-raised in the calling thread
            result["err"] = e

    # Deep v1 recursion becomes deep Python recursion, which needs a big C stack.
    old = threading.stack_size(200 << 20)
    try:
        t = threading.Thread(target=target)
        t.start()
    finally:
        threading.stack_size(old)
    t.join()
    if "err" in result:
        raise result["err"]
    return result["ok"]


def main(argv):
    args = [a for a in argv if not a.startswith("--")]
    max_ops, stats = DEFAULT_MAX_OPS, "--stats" in argv
    for a in argv:
        if a.startswith("--max-ops="):
            max_ops = int(a.split("=", 1)[1])
    if "--max-ops" in argv:
        max_ops = int(argv[argv.index("--max-ops") + 1])
        args.remove(str(max_ops))
    if len(args) != 1:
        print(__doc__.strip().splitlines()[2], file=sys.stderr)
        return 2
    with open(args[0], "rb") as fh:
        src = fh.read()
    try:
        out, ops = run(src, sys.stdin.buffer.read(), max_ops)
        code = 0
    except V1Error as e:
        out, ops, code = e.output, e.ops, e.code
        print(f"v1ref: {e}", file=sys.stderr)
    sys.stdout.buffer.write(out)
    sys.stdout.flush()
    if stats:
        print(f"ops {ops}", file=sys.stderr)
    return code


sys.setrecursionlimit(1_000_000)

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
