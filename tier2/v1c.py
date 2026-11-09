#!/usr/bin/env python3
"""v1c - compiles a v1 program (standard input) into a program for the one-instruction
machine (standard output: whitespace-separated decimal words).

Layout of the output program:
    [code][initialised cells: constants and the stack pointer]
followed in memory (not in the file, so it starts as 0) by globals, arrays, function
frames, scratch cells and the recursion stack.

Instruction "a b c": mem[a] -= mem[b]; if the result < 0 jump to c, else go on.
Cells used everywhere: Z (always 0 between instructions), M1 (constant -1).
  jump L      = M1 Z L        (-1 < 0, always jumps; M1 keeps -1)
  x -= y      = x y next
  x += y      = Z y; x Z; Z Z
  if x < 0 L  = x Z L         (x is unchanged)

Functions may only call themselves or functions defined earlier, so a function's frame
can only be in use once unless it calls itself. Frames are therefore fixed cells; a
call of a function to itself first pushes the cells it still needs on a stack and pops
them afterwards.

The compiler is written so that it can be ported line by line to v1 (Tier 3): plain
arrays of integers, no dictionaries in the code generator's decisions.
"""
import sys

N = 1048576
IN = N - 2
OUT = N - 1
MAXINT = 2147483647

# ---------------------------------------------------------------------------
# Lexer
# ---------------------------------------------------------------------------
T_EOF, T_NUM, T_ID, T_PUNCT = 0, 1, 2, 3
KEYWORDS = ('var', 'array', 'func', 'if', 'else', 'while', 'return')


class CompileError(Exception):
    pass


class Lexer(object):
    def __init__(self, src):
        self.s = src
        self.i = 0
        self.line = 1
        self.kind = T_EOF
        self.text = ''
        self.val = 0
        self.next()

    def err(self, msg):
        raise CompileError('line %d: %s' % (self.line, msg))

    def next(self):
        s = self.s
        n = len(s)
        i = self.i
        while i < n:
            c = s[i]
            if c == '\n':
                self.line += 1
                i += 1
            elif c in ' \t\r':
                i += 1
            elif c == '/' and i + 1 < n and s[i + 1] == '/':
                while i < n and s[i] != '\n':
                    i += 1
            else:
                break
        if i >= n:
            self.i = i
            self.kind = T_EOF
            self.text = ''
            return
        c = s[i]
        if c.isdigit():
            j = i
            while j < n and s[j].isdigit():
                j += 1
            if j < n and (s[j].isalpha() or s[j] == '_'):
                self.i = j
                self.err('bad number')
            self.text = s[i:j]
            v = int(self.text)
            if v > MAXINT:
                self.i = j
                self.err('number too large')
            self.kind, self.val, self.i = T_NUM, v, j
            return
        if c.isalpha() or c == '_':
            j = i
            while j < n and (s[j].isalnum() or s[j] == '_'):
                j += 1
            self.text = s[i:j]
            if len(self.text) > 24:
                self.i = j
                self.err('name longer than 24 characters')
            self.kind, self.i = T_ID, j
            return
        two = s[i:i + 2]
        if two in ('<=', '>=', '==', '!='):
            self.kind, self.text, self.i = T_PUNCT, two, i + 2
            return
        if c in '{}()[];,=<>+-*':
            self.kind, self.text, self.i = T_PUNCT, c, i + 1
            return
        self.i = i + 1
        self.err('unexpected character %r' % c)

    def is_(self, t):
        return self.kind in (T_PUNCT, T_ID) and self.text == t

    def expect(self, t):
        if not self.is_(t):
            self.err('expected %r, found %r' % (t, self.text))
        self.next()

    def ident(self):
        if self.kind != T_ID or self.text in KEYWORDS:
            self.err('expected a name, found %r' % self.text)
        t = self.text
        self.next()
        return t


# ---------------------------------------------------------------------------
# Parser -> tree. Expression nodes: ('num', v) ('var', cell) ('idx', arr, e)
# ('call', fn, [args]) ('neg', e) ('bin', op, l, r) ('getc',) ('putc', e)
# Statements: ('set', cell, e) ('aset', arr, ie, e) ('expr', call) ('if', c, A, B)
# ('while', c, A) ('ret', e). A cell is ('g', index) for globals or ('l', index) for a
# local / parameter of the current function.
# ---------------------------------------------------------------------------
class Func(object):
    def __init__(self, name, idx):
        self.name = name
        self.idx = idx
        self.nparams = 0
        self.nlocals = 0          # parameters are locals 0..nparams-1
        self.body = None
        self.self_calls = False


class Parser(object):
    def __init__(self, src):
        self.lx = Lexer(src)
        self.globals = {}         # name -> global index
        self.nglobals = 0
        self.arrays = {}          # name -> (array index, size)
        self.array_sizes = []
        self.funcs = {}
        self.flist = []
        self.cur = None
        self.scopes = []

    def parse(self):
        lx = self.lx
        while lx.kind != T_EOF:
            if lx.is_('var'):
                lx.next()
                name = lx.ident()
                lx.expect(';')
                self.declare_global(name)
            elif lx.is_('array'):
                lx.next()
                name = lx.ident()
                lx.expect('[')
                if lx.kind != T_NUM or lx.val <= 0:
                    lx.err('array size must be a positive number')
                size = lx.val
                lx.next()
                lx.expect(']')
                lx.expect(';')
                if name in self.arrays or name in self.globals:
                    lx.err('%s declared twice' % name)
                self.arrays[name] = (len(self.array_sizes), size)
                self.array_sizes.append(size)
            elif lx.is_('func'):
                self.parse_func()
            else:
                lx.err('expected var, array or func')
        if 'main' not in self.funcs or self.funcs['main'].nparams != 0:
            raise CompileError('missing main() without parameters')

    def declare_global(self, name):
        if name in self.globals or name in self.arrays:
            self.lx.err('%s declared twice' % name)
        self.globals[name] = self.nglobals
        self.nglobals += 1

    def parse_func(self):
        lx = self.lx
        lx.next()
        name = lx.ident()
        if name in self.funcs or name in ('getc', 'putc'):
            lx.err('function %s defined twice' % name)
        f = Func(name, len(self.flist))
        self.cur = f
        self.scopes = [{}]
        lx.expect('(')
        if not lx.is_(')'):
            while True:
                p = lx.ident()
                if p in self.scopes[0]:
                    lx.err('parameter %s listed twice' % p)
                self.scopes[0][p] = f.nlocals
                f.nlocals += 1
                if lx.is_(','):
                    lx.next()
                    continue
                break
        lx.expect(')')
        f.nparams = f.nlocals
        if f.nparams > 8:
            lx.err('more than 8 parameters')
        self.funcs[name] = f      # visible inside its own body: a function may call itself
        self.flist.append(f)
        f.body = self.parse_block(new_scope=False)
        self.cur = None

    def parse_block(self, new_scope=True):
        lx = self.lx
        lx.expect('{')
        if new_scope:
            self.scopes.append({})
        out = []
        while not lx.is_('}'):
            if lx.kind == T_EOF:
                lx.err('missing }')
            st = self.parse_stmt()
            if st is not None:
                out.append(st)
        lx.next()
        if new_scope:
            self.scopes.pop()
        return out

    def lookup_var(self, name):
        for sc in reversed(self.scopes):
            if name in sc:
                return ('l', sc[name])
        if name in self.globals:
            return ('g', self.globals[name])
        self.lx.err('unknown variable %s' % name)

    def parse_stmt(self):
        lx = self.lx
        if lx.is_('var'):
            lx.next()
            name = lx.ident()
            lx.expect(';')
            sc = self.scopes[-1]
            if name in sc and len(self.scopes) > 1:
                lx.err('%s declared twice in one block' % name)
            sc[name] = self.cur.nlocals
            self.cur.nlocals += 1
            return None
        if lx.is_('if'):
            lx.next()
            lx.expect('(')
            c = self.parse_expr()
            lx.expect(')')
            a = self.parse_block()
            b = []
            if lx.is_('else'):
                lx.next()
                b = self.parse_block()
            return ('if', c, a, b)
        if lx.is_('while'):
            lx.next()
            lx.expect('(')
            c = self.parse_expr()
            lx.expect(')')
            return ('while', c, self.parse_block())
        if lx.is_('return'):
            lx.next()
            e = self.parse_expr()
            lx.expect(';')
            return ('ret', e)
        if lx.kind == T_ID and lx.text not in KEYWORDS:
            name = lx.ident()
            if lx.is_('('):
                e = self.parse_call(name)
                lx.expect(';')
                return ('expr', e)
            if lx.is_('['):
                arr = self.lookup_array(name)
                lx.next()
                ie = self.parse_expr()
                lx.expect(']')
                lx.expect('=')
                e = self.parse_expr()
                lx.expect(';')
                return ('aset', arr, ie, e)
            cell = self.lookup_var(name)
            lx.expect('=')
            e = self.parse_expr()
            lx.expect(';')
            return ('set', cell, e)
        lx.err('unexpected %r' % lx.text)

    def lookup_array(self, name):
        for sc in self.scopes:
            if name in sc:
                self.lx.err('%s is a variable, not an array' % name)
        if name not in self.arrays:
            self.lx.err('unknown array %s' % name)
        return self.arrays[name][0]

    def parse_call(self, name):
        lx = self.lx
        lx.expect('(')
        args = []
        if not lx.is_(')'):
            while True:
                args.append(self.parse_expr())
                if lx.is_(','):
                    lx.next()
                    continue
                break
        lx.expect(')')
        if name == 'getc':
            if args:
                lx.err('getc takes no arguments')
            return ('getc',)
        if name == 'putc':
            if len(args) != 1:
                lx.err('putc takes one argument')
            return ('putc', args[0])
        f = self.funcs.get(name)
        if f is None:
            lx.err('function %s used before it is defined' % name)
        if len(args) != f.nparams:
            lx.err('%s takes %d arguments' % (name, f.nparams))
        if f is self.cur:
            f.self_calls = True
        return ('call', f.idx, args)

    def parse_expr(self):
        lx = self.lx
        l = self.parse_sum()
        while lx.kind == T_PUNCT and lx.text in ('<', '<=', '>', '>=', '==', '!='):
            op = lx.text
            lx.next()
            r = self.parse_sum()
            l = ('bin', op, l, r)
        return l

    def parse_sum(self):
        lx = self.lx
        l = self.parse_term()
        while lx.kind == T_PUNCT and lx.text in ('+', '-'):
            op = lx.text
            lx.next()
            r = self.parse_term()
            l = ('bin', op, l, r)
        return l

    def parse_term(self):
        lx = self.lx
        l = self.parse_unary()
        while lx.is_('*'):
            lx.next()
            r = self.parse_unary()
            l = ('bin', '*', l, r)
        return l

    def parse_unary(self):
        lx = self.lx
        if lx.is_('-'):
            lx.next()
            return ('neg', self.parse_unary())
        if lx.kind == T_NUM:
            v = lx.val
            lx.next()
            return ('num', v)
        if lx.is_('('):
            lx.next()
            e = self.parse_expr()
            lx.expect(')')
            return e
        if lx.kind == T_ID and lx.text not in KEYWORDS:
            name = lx.ident()
            if lx.is_('('):
                return self.parse_call(name)
            if lx.is_('['):
                arr = self.lookup_array(name)
                lx.next()
                ie = self.parse_expr()
                lx.expect(']')
                return ('idx', arr, ie)
            return ('var', self.lookup_var(name))
        lx.err('unexpected %r in expression' % lx.text)


# ---------------------------------------------------------------------------
# Code generation
# ---------------------------------------------------------------------------
# Operand kinds
ABS, LAB, CON, DAT, NXT = 0, 1, 2, 3, 4


def wrap(v):
    v &= 0xFFFFFFFF
    return v - 0x100000000 if v & 0x80000000 else v


class Gen(object):
    def __init__(self, prog, pass_no, info):
        self.p = prog
        self.pass_no = pass_no
        self.info = info              # results of pass 1 (sizes, label addresses)
        self.code = []                # words (pass 2) or just a count (pass 1)
        self.pc = 0
        self.nlabels = 0
        self.lab_addr = info['lab_addr'] if pass_no == 2 else {}
        self.consts = []              # values; label-valued constants are ('L', id, sign)
        self.const_ids = {}
        self.ndata = 0

    # --- low level ---
    def new_label(self):
        self.nlabels += 1
        return self.nlabels

    def place(self, lab):
        self.lab_addr[lab] = self.pc

    def data(self, n=1):
        d = self.ndata
        self.ndata += n
        return d

    def const(self, v):
        v = wrap(v)
        key = ('v', v)
        if key not in self.const_ids:
            self.const_ids[key] = len(self.consts)
            self.consts.append(v)
        return (CON, self.const_ids[key])

    def const_label(self, lab, sign):
        key = ('l', lab, sign)
        if key not in self.const_ids:
            self.const_ids[key] = len(self.consts)
            self.consts.append(key)
        return (CON, self.const_ids[key])

    def resolve(self, op):
        k, v = op
        if k == ABS:
            return v
        if k == LAB:
            return self.lab_addr[v]
        if k == CON:
            return self.info['code_size'] + v
        if k == DAT:
            return self.info['data_base'] + v
        return self.pc + 3

    def emit(self, a, b, c=(NXT, 0)):
        if self.pass_no == 2:
            self.code.append(self.resolve(a))
            self.code.append(self.resolve(b))
            self.code.append(self.resolve(c))
        self.pc += 3

    def field(self, which):
        """Operand that names a field (0=a, 1=b, 2=c) of the instruction emitted next."""
        return (ABS, self.pc + which)

    # --- macros ---
    def jmp(self, lab):
        self.emit(self.M1, self.Z, (LAB, lab))

    def clr(self, x):
        self.emit(x, x)

    def add(self, x, y):
        self.emit(self.Z, y)
        self.emit(x, self.Z)
        self.emit(self.Z, self.Z)

    def mov(self, x, y):
        if x == y:
            return
        self.clr(x)
        if not (y[0] == CON and self.consts[y[1]] == 0):
            self.add(x, y)

    def neg_into(self, x, y):
        self.clr(x)
        self.emit(x, y)

    def jlt(self, x, lab):
        """if x < 0 goto lab"""
        self.emit(x, self.Z, (LAB, lab))

    # --- program ---
    def run(self):
        p = self.p
        self.Z = (DAT, self.data())
        self.T1 = (DAT, self.data())
        self.T2 = (DAT, self.data())
        self.RV = (DAT, self.data())
        self.M1 = self.const(-1)
        self.SP = self.const_label(0, 0)     # placeholder entry: holds the stack base
        self.gcells = [(DAT, self.data()) for _ in range(p.nglobals)]
        self.abase = []
        for size in p.array_sizes:
            self.abase.append(self.data(size))
        self.fr = []
        for f in p.flist:
            fr = {'nret': (DAT, self.data()), 'loc': [(DAT, self.data()) for _ in range(f.nlocals)],
                  'temps': [], 'entry': self.new_label(), 'exit': self.new_label()}
            self.fr.append(fr)
        self.mul_entry = self.new_label()
        self.mul_ret = self.new_label()
        self.MA = (DAT, self.data())
        self.MB = (DAT, self.data())
        self.MR = (DAT, self.data())
        self.MC = (DAT, self.data())
        self.MNRET = (DAT, self.data())
        self.used_mul = self.info.get('used_mul', True)
        # start: call main, then halt
        main = p.funcs['main']
        halt = self.new_label()
        mfr = self.fr[main.idx]
        self.clr(mfr['nret'])
        self.emit(mfr['nret'], self.const_label(halt, 1))
        self.jmp(mfr['entry'])
        self.place(halt)
        self.emit(self.M1, self.Z, (ABS, -1))
        for f in p.flist:
            self.gen_func(f)
        if self.used_mul:
            self.gen_mul()
        self.code_size = self.pc

    def frame_cell(self, cell):
        kind, i = cell
        if kind == 'g':
            return self.gcells[i]
        return self.fr[self.f.idx]['loc'][i]

    def temp(self):
        fr = self.fr[self.f.idx]
        if self.ntemp == len(fr['temps']):
            fr['temps'].append((DAT, self.data()))
        t = fr['temps'][self.ntemp]
        self.ntemp += 1
        return t

    def free_temps(self, n):
        self.ntemp = n

    def gen_func(self, f):
        self.f = f
        self.ntemp = 0
        fr = self.fr[f.idx]
        self.place(fr['entry'])
        self.gen_block(f.body)
        # falling off the end returns 0
        self.clr(self.RV)
        self.place(fr['exit'])
        # return: jump to the address whose negation is in nret
        tgt_next = (ABS, self.pc + 3 * 2 + 2)
        self.clr(tgt_next)
        self.emit(tgt_next, fr['nret'])
        self.emit(self.M1, self.Z, (ABS, 0))

    def gen_block(self, stmts):
        for st in stmts:
            self.gen_stmt(st)

    def gen_stmt(self, st):
        k = st[0]
        mark = self.ntemp
        if k == 'set':
            self.gen_expr_into(st[2], self.frame_cell(st[1]))
        elif k == 'aset':
            ie, e = st[2], st[3]
            ix = self.gen_expr_safe(ie, e)
            v = self.gen_expr(e)
            self.store_index(st[1], ix, v)
        elif k == 'expr':
            self.gen_expr(st[1])
        elif k == 'if':
            lt, lf, lend = self.new_label(), self.new_label(), self.new_label()
            self.gen_cond(st[1], lt, lf)
            self.place(lt)
            self.gen_block(st[2])
            if st[3]:
                self.jmp(lend)
                self.place(lf)
                self.gen_block(st[3])
                self.place(lend)
            else:
                self.place(lf)
        elif k == 'while':
            ltop, lbody, lend = self.new_label(), self.new_label(), self.new_label()
            self.place(ltop)
            self.gen_cond(st[1], lbody, lend)
            self.place(lbody)
            self.gen_block(st[2])
            self.jmp(ltop)
            self.place(lend)
        elif k == 'ret':
            self.gen_expr_into(st[1], self.RV)
            self.jmp(self.fr[self.f.idx]['exit'])
        self.free_temps(mark)

    # --- expressions ---
    def has_effects(self, e):
        k = e[0]
        if k in ('call', 'getc', 'putc'):
            return True
        if k == 'idx':
            return self.has_effects(e[2])
        if k == 'neg':
            return self.has_effects(e[1])
        if k == 'bin':
            return self.has_effects(e[2]) or self.has_effects(e[3])
        return False

    def gen_expr_safe(self, e, later):
        """Value of e that stays correct while `later` is evaluated afterwards."""
        v = self.gen_expr(e)
        if v[0] == DAT and v not in self.fr[self.f.idx]['temps'] and self.has_effects(later):
            t = self.temp()
            self.mov(t, v)
            return t
        return v

    def gen_expr(self, e):
        """Return an operand holding the value of e (a constant, a variable or a temp)."""
        k = e[0]
        if k == 'num':
            return self.const(e[1])
        if k == 'var':
            return self.frame_cell(e[1])
        t = self.temp()
        self.gen_expr_into(e, t)
        return t

    def gen_expr_into(self, e, dst):
        k = e[0]
        if k == 'num':
            self.mov(dst, self.const(e[1]))
        elif k == 'var':
            self.mov(dst, self.frame_cell(e[1]))
        elif k == 'neg':
            if e[1][0] == 'num':
                self.mov(dst, self.const(-e[1][1]))
                return
            mark = self.ntemp
            v = self.gen_expr(e[1])
            if v == dst:
                t = self.temp()
                self.mov(t, v)
                v = t
            self.neg_into(dst, v)
            self.free_temps(mark)
        elif k == 'getc':
            self.clr(dst)
            self.emit(self.Z, (ABS, IN))
            self.emit(dst, self.Z)
            self.emit(self.Z, self.Z)
        elif k == 'putc':
            mark = self.ntemp
            v = self.gen_expr(e[1])
            self.neg_into(self.T1, v)
            self.emit((ABS, OUT), self.T1)
            self.clr(dst)
            self.free_temps(mark)
        elif k == 'idx':
            mark = self.ntemp
            ix = self.gen_expr(e[2])
            self.load_index(e[1], ix, dst)
            self.free_temps(mark)
        elif k == 'call':
            self.gen_call(e)
            self.mov(dst, self.RV)
        elif k == 'bin':
            self.gen_bin(e, dst)
        else:
            raise CompileError('bad expression')

    def gen_bin(self, e, dst):
        op, l, r = e[1], e[2], e[3]
        mark = self.ntemp
        if op in ('<', '<=', '>', '>=', '==', '!='):
            lt, lf, lend = self.new_label(), self.new_label(), self.new_label()
            self.gen_cond(e, lt, lf)
            self.place(lt)
            self.clr(dst)
            self.emit(dst, self.M1)
            self.jmp(lend)
            self.place(lf)
            self.clr(dst)
            self.place(lend)
            self.free_temps(mark)
            return
        a = self.gen_expr_safe(l, r)
        b = self.gen_expr(r)
        if op == '+':
            if dst == a:
                self.add(dst, b)
            elif dst == b:
                self.add(dst, a)
            else:
                self.clr(dst)
                self.emit(self.Z, a)
                self.emit(self.Z, b)
                self.emit(dst, self.Z)
                self.emit(self.Z, self.Z)
        elif op == '-':
            if dst == b and dst != a:
                t = self.temp()
                self.mov(t, b)
                b = t
            self.mov(dst, a)
            self.emit(dst, b)
        elif op == '*':
            if not self.mul_const(a, b, dst) and not self.mul_const(b, a, dst):
                self.gen_mul_call(a, b, dst)
        self.free_temps(mark)

    def mul_const(self, x, c, dst):
        """x * literal as doublings and additions, most significant bit first, when that
        is shorter than the shared routine. Returns False when it does not apply."""
        if c[0] != CON or isinstance(self.consts[c[1]], tuple):
            return False
        v = self.consts[c[1]]
        neg = v < 0
        if neg:
            v = -v
        if v >= 1 << 31:
            return False
        if v == 0:
            self.clr(dst)
            return True
        top = 30
        while (1 << top) > v:
            top -= 1
        ones = 0
        for i in range(top + 1):
            if v & (1 << i):
                ones += 1
        if top + ones > 20:
            return False
        t = self.temp()
        self.mov(t, x)
        i = top - 1
        while i >= 0:
            self.add(t, t)
            if v & (1 << i):
                self.add(t, x)
            i -= 1
        if neg:
            self.neg_into(dst, t)
        else:
            self.mov(dst, t)
        return True

    def gen_mul_call(self, a, b, dst):
        self.mov(self.MA, a)
        self.mov(self.MB, b)
        back = self.new_label()
        self.clr(self.MNRET)
        self.emit(self.MNRET, self.const_label(back, 1))
        self.jmp(self.mul_entry)
        self.place(back)
        self.mov(dst, self.MR)

    def gen_mul(self):
        """MR = MA * MB modulo 2^32: 32 rounds of MR += MR; if MB < 0: MR += MA; MB += MB."""
        self.place(self.mul_entry)
        top, skip, done = self.new_label(), self.new_label(), self.new_label()
        self.clr(self.MR)
        self.clr(self.MC)
        self.emit(self.MC, self.const(32))        # MC = -32, counts up to 0
        # leading zero bits of MB only shift it: 6 instructions per bit instead of 10
        lz, ret = self.new_label(), self.new_label()
        self.place(lz)
        self.jlt(self.MB, top)
        self.add(self.MB, self.MB)
        self.emit(self.MC, self.M1)
        self.jlt(self.MC, lz)
        self.jmp(ret)
        self.place(top)
        self.add(self.MR, self.MR)
        self.emit(self.MB, self.Z, (LAB, skip))   # if MB < 0 add
        self.jmp(done)  # placeholder replaced below
        self.place(skip)
        self.add(self.MR, self.MA)
        self.place(done)
        self.add(self.MB, self.MB)
        self.emit(self.MC, self.M1)               # MC += 1
        self.emit(self.MC, self.Z, (LAB, top))    # loop while MC < 0
        self.place(ret)
        tgt_next = (ABS, self.pc + 3 * 2 + 2)
        self.clr(tgt_next)
        self.emit(tgt_next, self.MNRET)
        self.emit(self.M1, self.Z, (ABS, 0))

    # --- conditions ---
    def gen_cond(self, e, lt, lf):
        """Jump to lt if e is non-zero, else to lf."""
        mark = self.ntemp
        if e[0] == 'bin' and e[1] in ('<', '<=', '>', '>=', '==', '!='):
            op = e[1]
            a = self.gen_expr_safe(e[2], e[3])
            b = self.gen_expr(e[3])
            if op == '<':
                self.less(a, b, lt, lf)
            elif op == '>':
                self.less(b, a, lt, lf)
            elif op == '<=':
                self.less(b, a, lf, lt)
            elif op == '>=':
                self.less(a, b, lf, lt)
            elif op == '==':
                self.equal(a, b, lt, lf)
            else:
                self.equal(a, b, lf, lt)
        else:
            v = self.gen_expr(e)
            # v != 0 -> lt
            self.jlt(v, lt)
            self.neg_into(self.T1, v)
            self.jlt(self.T1, lt)
            self.jmp(lf)
        self.free_temps(mark)

    def less(self, a, b, lt, lf):
        """True signed a < b, even when a - b overflows."""
        aneg, diff = self.new_label(), self.new_label()
        self.jlt(a, aneg)
        self.jlt(b, lf)          # a >= 0 > b
        self.jmp(diff)
        self.place(aneg)
        self.jlt(b, diff)        # both negative
        self.jmp(lt)             # a < 0 <= b
        self.place(diff)         # same sign: a - b cannot overflow
        self.mov(self.T1, a)
        self.emit(self.T1, b)
        self.jlt(self.T1, lt)
        self.jmp(lf)

    def equal(self, a, b, lt, lf):
        self.mov(self.T1, a)
        self.emit(self.T1, b)
        self.jlt(self.T1, lf)
        self.neg_into(self.T2, self.T1)
        self.jlt(self.T2, lf)
        self.jmp(lt)

    # --- arrays: the address is patched into the instruction that uses it ---
    def addr_neg(self, arr, ix):
        """T2 = -(base + index)"""
        self.neg_into(self.T2, ix)
        self.emit(self.T2, self.const_data(self.abase[arr]))

    def const_data(self, off):
        """A constant cell holding the address of data offset `off`."""
        key = ('d', off)
        if key not in self.const_ids:
            self.const_ids[key] = len(self.consts)
            self.consts.append(key)
        return (CON, self.const_ids[key])

    def load_index(self, arr, ix, dst):
        self.addr_neg(arr, ix)
        f = (ABS, self.pc + 3 * 2 + 1)        # b field of the instruction after the next two
        self.clr(f)
        self.emit(f, self.T2)
        self.emit(self.Z, (ABS, 0))           # Z = -mem[address]   (b field patched)
        if dst == self.Z:
            raise CompileError('internal: load into Z')
        self.clr(dst)
        self.emit(dst, self.Z)
        self.emit(self.Z, self.Z)

    def store_index(self, arr, ix, v):
        if v == self.T2:
            raise CompileError('internal: store from T2')
        self.neg_into(self.T1, v)             # T1 = -v (v may be a temp the address uses)
        self.addr_neg(arr, ix)
        base = self.pc
        # fields to patch: instruction P (a and b) and instruction Q (a) below
        pa, pb, qa = (ABS, base + 3 * 6), (ABS, base + 3 * 6 + 1), (ABS, base + 3 * 7)
        self.clr(pa)
        self.emit(pa, self.T2)
        self.clr(pb)
        self.emit(pb, self.T2)
        self.clr(qa)
        self.emit(qa, self.T2)
        self.emit((ABS, 0), (ABS, 0))         # P: mem[addr] = 0
        self.emit((ABS, 0), self.T1)          # Q: mem[addr] -= -v

    # --- calls ---
    def gen_call(self, e):
        fi, args = e[1], e[2]
        callee = self.fr[fi]
        mark = self.ntemp
        vals = []
        for n, a in enumerate(args):
            later_effects = any(self.has_effects(x) for x in args[n + 1:])
            v = self.gen_expr(a)
            mine = v[0] == DAT and v not in self.fr[self.f.idx]['temps']
            # a self-call overwrites our own parameters, so a variable argument must be
            # copied out first; so must one that a later argument's call could change
            if mine and (later_effects or fi == self.f.idx):
                t = self.temp()
                self.mov(t, v)
                v = t
            vals.append(v)
        recursive = (fi == self.f.idx)
        saved = []
        if recursive:
            me = self.fr[self.f.idx]
            arg_temps = set(v for v in vals if v in me['temps'])
            saved = [me['nret']] + me['loc'] + [t for t in me['temps'][:self.ntemp] if t not in arg_temps]
            self.push(saved)
        # arguments go into the callee's parameter cells only after all are evaluated
        for n, v in enumerate(vals):
            self.mov(callee['loc'][n], v)
        back = self.new_label()
        self.clr(callee['nret'])
        self.emit(callee['nret'], self.const_label(back, 1))
        self.jmp(callee['entry'])
        self.place(back)
        if recursive:
            self.pop(saved)
        self.free_temps(mark)

    def push(self, cells):
        """mem[SP + i] = cells[i]; SP += len(cells)."""
        self.neg_into(self.T2, self.SP)           # T2 = -SP
        for c in cells:
            self.neg_into(self.T1, c)             # T1 = -value
            base = self.pc
            pa, pb, qa = (ABS, base + 3 * 6), (ABS, base + 3 * 6 + 1), (ABS, base + 3 * 7)
            self.clr(pa)
            self.emit(pa, self.T2)
            self.clr(pb)
            self.emit(pb, self.T2)
            self.clr(qa)
            self.emit(qa, self.T2)
            self.emit((ABS, 0), (ABS, 0))
            self.emit((ABS, 0), self.T1)
            self.emit(self.T2, self.const(1))     # T2 = -(SP + i + 1)
        self.emit(self.SP, self.const(-len(cells)))

    def pop(self, cells):
        """SP -= len(cells); cells[i] = mem[SP + i]."""
        self.emit(self.SP, self.const(len(cells)))
        self.neg_into(self.T2, self.SP)
        for c in cells:
            f = (ABS, self.pc + 3 * 2 + 1)
            self.clr(f)
            self.emit(f, self.T2)
            self.emit(self.Z, (ABS, 0))
            self.clr(c)
            self.emit(c, self.Z)
            self.emit(self.Z, self.Z)
            self.emit(self.T2, self.const(1))


def compile_v1(src):
    prog = Parser(src)
    prog.parse()
    g1 = Gen(prog, 1, {'lab_addr': {}, 'used_mul': True})
    g1.run()
    info = {'lab_addr': g1.lab_addr, 'code_size': g1.code_size,
            'data_base': g1.code_size + len(g1.consts), 'used_mul': True}
    g2 = Gen(prog, 2, info)
    g2.run()
    stack_base = info['data_base'] + g2.ndata
    if stack_base + 4096 >= N - 2:
        raise CompileError('program and data do not fit in memory')
    words = list(g2.code)
    for c in g2.consts:
        if isinstance(c, tuple):
            if c[0] == 'l':
                if c[1] == 0:
                    words.append(stack_base)          # the stack pointer's start
                else:
                    a = info['lab_addr'][c[1]]
                    words.append(-a if c[2] == 0 else a)  # callers store 0 - value, so nret holds -address
            else:
                words.append(info['data_base'] + c[1])
        else:
            words.append(c)
    return words


def main():
    src = sys.stdin.buffer.read().decode('latin-1')
    try:
        words = compile_v1(src)
    except CompileError as e:
        sys.stderr.write('v1c: %s\n' % e)
        return 1
    out = []
    for i in range(0, len(words), 12):
        out.append(' '.join(str(w) for w in words[i:i + 12]))
    sys.stdout.buffer.write(('\n'.join(out) + '\n').encode('ascii'))
    return 0


if __name__ == '__main__':
    sys.setrecursionlimit(100000)
    sys.exit(main())
