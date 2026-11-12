#!/usr/bin/env python
"""
rebrand.py -- build Cheat Engine as "Turing Explorer": a private build with no Cheat Engine name or vocabulary in the
files it ships.

The repository keeps upstream's source as it is.  This script works on COPIES:

  stage  copy "Cheat Engine" (the source, without bin/lib) to a staging folder and rebrand the copy.  Two kinds of
         change:
           1. The brand, in text: "Cheat Engine" -> "Turing Explorer" (every spelling and case), "Dark Byte" -> "Turing",
              "Cheat Table" -> "Code Table", cheatengine.org (any host) -> turing-explorer.invalid (a reserved name:
              nothing can ever answer it); a link to Cheat Engine's page on another site (its Patreon) ->
              https://turing-explorer.invalid/ (renamed, it would lead to whoever owns that name there).
           2. Cheat Engine's own vocabulary (WORDS: its name, its driver dbk, its hypervisor dbvm, ultimap, speedhack,
              d3dhook, ...), everywhere it ends up in the binary: identifiers (unit, class, form, component, event and
              resource-string names are all stored in the exe), file and folder names, text.
         Names other programs or scripts rely on keep their VALUE: Lua function names (getCheatEngineDir,
         dbk_getCR3), table format keys (CheatEngineTableVersion), file magic ('CHEATENGINE'), registry value names,
         exports looked up in the injectable DLLs.  In code they are rebuilt at run time from pieces --
         (Copy(AnsiString('dbv'),1,MaxInt)+Copy(AnsiString('m_getCR3'),1,MaxInt)) -- so the word is not in the file.
         Where the language needs a constant (const/resourcestring declarations, case labels) they are renamed and
         listed in <stage>\\rebrand-constants.txt.
         Comments are not touched (they are not in the binary).  Identifiers that Lazarus/FPC themselves declare are
         never renamed (OldBkMode contains "dBk").
         The project: title, version info, manifest, output name (turing-explorer.exe), -dTURING_EXPLORER.  The
         program icon and the logos are Cheat Engine's with its blue turned purple (--art purple, the default);
         --art ce keeps them as they are, --art mark puts the generated Turing Explorer mark in their place.
  dist   assemble the runnable folder: turing-explorer.exe, the trusted thvbridge.exe + turinghv.dll, the Lua runtime and
         the scripts/data it reads at run time -- text rebranded, signatures and debug paths scrubbed from the DLLs, no
         injectable DLLs, no driver, no update check / online sharing scripts.
  scan   look through every file of a folder for the old names (ASCII and UTF-16, any case) and print what is left.

  python rebrand.py stage --src "<repo>\\Cheat Engine" --stage <dir>
  python rebrand.py dist  --src "<repo>\\Cheat Engine" --stage <dir> --dist <dir>
  python rebrand.py scan  --dist <dir>
"""
import argparse
import colorsys
import os
import re
import shutil
import struct
import sys

NAME = 'Turing Explorer'
EXE = 'turing-explorer'
PROJECT = 'turingexplorer'          # the staged project: turingexplorer.lpi / .lpr / .res / .ico
LAZARUS = r'C:\lazarus'

# ---------------------------------------------------------------------------------------------------------- the words

# Cheat Engine's vocabulary and what it becomes.  Matched case-insensitively ANYWHERE in an identifier (Pascal does not
# care about case, so the declaration and every use must change together), longest first.  Every stem is unused in the
# source (checked when this was written), so a renamed identifier cannot meet an existing one.
WORDS = [
    ('cheatengine', 'turingexplorer'),
    ('thvbridge', 'tebroker'),          # the broker process (in text and file names: te-broker, see rename_text)
    ('darkbyte', 'turing'),
    ('vehdebug', 'vxdebug'),
    ('speedhack', 'timewarp'),
    ('cetrainer', 'xtrainer'),
    ('ceserver', 'hvserver'),
    ('d3dhook', 'gfxhook'),
    ('ultimap', 'tracemap'),
    ('cepack', 'tepack'),
    ('celua', 'lxua'),
    ('dbvm', 'hvmx'),
    ('dbk', 'kmdrv'),
]
WORD_RE = re.compile('|'.join(w for w, _ in WORDS), re.I)
STEM = dict(WORDS)

DOMAIN_RE = re.compile(r'(?:[a-z0-9-]+\.)*cheat-?engine\.org', re.I)
URL_RE = re.compile(r'https?://([^/\s\'"<>]+)[^\s\'"<>]*', re.I)
BRAND_RE = re.compile(r'cheat-?engine|dark-?byte', re.I)
CE_RE = re.compile(r'(cheat)([ _-]?)(engine)', re.I)
DB_RE = re.compile(r'dark ?byte', re.I)
CT_RE = re.compile(r'(cheat)( )(table)', re.I)
IDENT_RE = re.compile(r'[A-Za-z0-9_]*')
LUACALL_RE = re.compile(r'[A-Za-z_][A-Za-z0-9_]*(?=\()')


def _case(word, like):
    if like.isupper():
        return word.upper()
    if like[0].isupper():
        return word[0].upper() + word[1:]
    return word.lower()


def _ce(m):
    a, sep, b = m.group(1), m.group(2), m.group(3)
    if sep == '' and not a[0].isupper() and not b[0].isupper():
        return 'turingexplorer'
    return _case('turing', a) + sep + _case('explorer', b)


def wmap(s):
    """The vocabulary, inside an identifier or a file name: anywhere (Pascal ignores case, so every spelling of an
    identifier must change the same way)."""
    return WORD_RE.sub(lambda m: _case(STEM[m.group(0).lower()], m.group(0)), s)


# words that also occur inside ordinary words: in text they count only where a word starts
# ("dbk64.sys", "Use dbk32", "isDBKLoaded" -- not "oldbkmode", "ServicePack", "sourcepackage", "forceLua")
INNER = {'dbk', 'cepack', 'celua', 'ceserver'}


def inner_false(text, m):
    w = m.group(0)
    return w.lower() in INNER and m.start() > 0 and text[m.start() - 1].isalpha() and not w[0].isupper()


def tmap(s):
    """The vocabulary, inside text."""
    def sub(m):
        if inner_false(s, m):
            return m.group(0)
        return _case(STEM[m.group(0).lower()], m.group(0))
    return WORD_RE.sub(sub, s)


def has_word(s):
    return WORD_RE.search(s) is not None or DB_RE.search(s) is not None or re.search(r'cheat[ _-]engine', s, re.I) is not None


def rename_text(s, spaced_only=False):
    """The brand, in text.  spaced_only: only the two-word spellings (Lua/text files, where CheatEngine is an identifier)."""
    # Cheat Engine's page on someone else's site (patreon.com/cheatengine): the whole link goes, a renamed one would
    # lead to whoever holds that name there
    s = URL_RE.sub(lambda m: 'https://turing-explorer.invalid/' if BRAND_RE.search(m.group(0))
                   and not DOMAIN_RE.fullmatch(m.group(1).split(':')[0]) else m.group(0), s)
    s = DOMAIN_RE.sub('turing-explorer.invalid', s)
    # the broker's file name (a process list shows it): te-broker.exe, the same length as thvbridge so the trusted
    # binary's own text can be patched in place
    s = re.sub(r'thvbridge', lambda m: _case('te-broker', m.group(0)), s, flags=re.I)
    if spaced_only:
        s = re.sub(r'(cheat)([ ])(engine)', _ce, s, flags=re.I)
    else:
        s = CE_RE.sub(_ce, s)
    s = DB_RE.sub(lambda m: 'TURING' if m.group(0).isupper() else 'Turing', s)
    s = CT_RE.sub(lambda m: _case('code', m.group(1)) + m.group(2) + _case('table', m.group(3)), s)
    return s


# Names that keep their value wherever they appear in a literal -- collected over the WHOLE source first
# (collect_kept), so a name kept in one literal is kept in every other one too: Lua globals a generated script assigns
# (dbk_OpenProcess=...), functions a generated script defines in one literal and wires up in another
# (D3DHookSpriteClick), assembler symbols ('CELUA_ServerName:').  Plain words (DBVM, Speedhack) are not in it: as
# text they are renamed.
KEPT = set()
NAME_IN_TEXT_RE = re.compile(r'[A-Za-z_][A-Za-z0-9_]*')
EXT_LIT_RE = re.compile(r'\.[A-Za-z0-9_]+')      # a file extension ('.CETRAINER'): existing files keep opening


def plain_word(t):
    return re.fullmatch(r'(?:%s)\d*' % '|'.join(w for w, _ in WORDS), t, re.I) is not None


def collect_kept(lit):
    """Pass 1 over every literal: the compound names that must keep their value."""
    if IDENT_RE.fullmatch(lit):
        if has_word(lit) and not plain_word(lit):
            KEPT.add(lit.lower())
        return
    for m in NAME_IN_TEXT_RE.finditer(lit):
        t = m.group(0)
        if WORD_RE.search(t) and not plain_word(t) and ('_' in t or lit[m.end():m.end() + 1] == '('):
            KEPT.add(t.lower())


def literal_value(lit):
    """What a Pascal literal's content should become.  Returns (new content, keep) -- keep: parts of it are names other
    code relies on (a whole identifier-like literal, a file extension, or a KEPT name inside text) and still hold
    their words."""
    if IDENT_RE.fullmatch(lit) or (EXT_LIT_RE.fullmatch(lit) and has_word(lit)):
        return lit, has_word(lit)
    out, last, kept = [], 0, False
    for m in NAME_IN_TEXT_RE.finditer(lit):
        if m.group(0).lower() in KEPT:
            out.append(tmap(rename_text(lit[last:m.start()])))
            out.append(m.group(0))
            last = m.end()
            kept = True
    out.append(tmap(rename_text(lit[last:])))
    return ''.join(out), kept


def split_expr(content, pchar):
    """A literal's content as an expression the compiler cannot fold back: each word split in two."""
    cuts = sorted({m.start() + max(1, (m.end() - m.start()) // 2) for rx in (WORD_RE, DB_RE, re.compile(r'cheat[ _-]engine', re.I))
                   for m in rx.finditer(content)})
    pieces, last = [], 0
    for c in cuts:
        pieces.append(content[last:c])
        last = c
    pieces.append(content[last:])
    e = '+'.join("Copy(AnsiString('%s'),1,MaxInt)" % p for p in pieces if p != '')
    return ('PChar(%s)' % e) if pchar else '(%s)' % e


# ------------------------------------------------------------------------------------------- Pascal / LFM tokenizer

def tokens(text):
    """(kind, text): comment (incl. {$directives}), str (content of '...', raw), ident, other."""
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c == '{':
            j = text.find('}', i + 1)
            j = n - 1 if j < 0 else j
            yield 'comment', text[i:j + 1]
            i = j + 1
        elif c == '(' and text.startswith('(*', i):
            j = text.find('*)', i + 2)
            j = n - 2 if j < 0 else j
            yield 'comment', text[i:j + 2]
            i = j + 2
        elif c == '/' and text.startswith('//', i):
            j = text.find('\n', i)
            j = n if j < 0 else j
            yield 'comment', text[i:j]
            i = j
        elif c == "'":
            j = i + 1
            while j < n:
                if text[j] == "'":
                    if j + 1 < n and text[j + 1] == "'":
                        j += 2
                        continue
                    break
                if text[j] in '\r\n':
                    break
                j += 1
            yield 'str', text[i + 1:j]
            i = j + 1 if (j < n and text[j] == "'") else j
        elif c.isalpha() or c == '_':
            j = i + 1
            while j < n and (text[j].isalnum() or text[j] == '_'):
                j += 1
            yield 'ident', text[i:j]
            i = j
        elif c == '#' or c == '$' or c == '&' or c.isdigit():
            # numbers and char codes (#13, #$0D, $FF, &777, 1e5): kept together so 'e5'/'FF' are not identifiers
            j = i + 1
            while j < n and (text[j].isalnum() or text[j] in '$_.' and not text.startswith('..', j)):
                j += 1
            yield 'other', text[i:j]
            i = j
        elif c.isspace():
            j = i + 1
            while j < n and text[j].isspace():
                j += 1
            yield 'space', text[i:j]
            i = j
        else:
            yield 'other', c
            i += 1


DIRECTIVE_FILE_RE = re.compile(r'^(\{\$(?:i|include|r|resource)\s+)([^}%*]+?)(\s*\})$', re.I)
CODE_ON = {'begin', 'initialization', 'finalization'}
CODE_OPEN = {'begin', 'case', 'try', 'asm'}
# never inside a statement: seeing one means the code block ended (protects against begin/end counts that {$ifdef}
# branches throw off)
CODE_OFF = {'const', 'resourcestring', 'type', 'var', 'threadvar', 'procedure', 'function', 'constructor', 'destructor',
            'uses', 'interface', 'implementation', 'exports'}


class Pascal:
    """Rewrites one Pascal or LFM file (see the module doc)."""

    def __init__(self, external, lfm=False, start_in_code=False):
        self.external = external
        self.lfm = lfm
        self.start_in_code = start_in_code
        self.constants = []          # (literal, why) renamed where the language needs a constant
        self.names = set()           # identifier-like literals that keep their words (Lua function names, ...)
        self.split = 0
        self.literals = 0
        self.idents = 0

    def ident(self, t):
        if not WORD_RE.search(t) or t.lower() in self.external:
            return t
        self.idents += 1
        return wmap(t)

    def run(self, text):
        toks = list(tokens(text))
        out = []
        code = self.start_in_code
        depth = 1 if code else 0
        sig = [k for k, (kind, _) in enumerate(toks) if kind not in ('comment', 'space')]
        pos_in_sig = {k: s for s, k in enumerate(sig)}

        def neighbour(k, step):
            s = pos_in_sig.get(k)
            if s is None:
                return None, ''
            s += step
            if 0 <= s < len(sig):
                return toks[sig[s]]
            return None, ''

        for k, (kind, t) in enumerate(toks):
            if kind == 'comment':
                m = DIRECTIVE_FILE_RE.match(t)
                out.append(m.group(1) + wmap(rename_text(m.group(2))) + m.group(3) if m else t)
            elif kind == 'ident':
                lw = t.lower()
                if not self.lfm:
                    if lw in CODE_ON and not code:
                        code, depth = True, 1
                    elif code and lw in CODE_OPEN:
                        depth += 1
                    elif code and lw == 'end':
                        depth -= 1
                        if depth <= 0:
                            code = False
                    elif code and lw in CODE_OFF:
                        code, depth = False, 0
                out.append(self.ident(t))
            elif kind == 'str':
                out.append(self.literal(toks, k, t, code, neighbour))
            else:
                out.append(t)
        return ''.join(out)

    def literal(self, toks, k, lit, code, neighbour):
        # "Do you want Cheat '+'Engine to ..." : the compiler joins the two, so the brand is renamed across the +
        if neighbour(k, -1)[1] == '+' and neighbour(k, -2)[0] == 'str' and re.search(r'(?i)\bcheat\s*$', neighbour(k, -2)[1]):
            lit = re.sub(r'(?i)^(\s*)(engine|table)', lambda m: m.group(1) + _case('explorer' if m.group(2).lower() == 'engine' else 'table', m.group(2)), lit)
        if neighbour(k, +1)[1] == '+' and neighbour(k, +2)[0] == 'str' and re.match(r'(?i)\s*(engine|table)', neighbour(k, +2)[1]):
            nxt = re.match(r'(?i)\s*(engine|table)', neighbour(k, +2)[1]).group(1).lower()
            lit = re.sub(r'(?i)\b(cheat)(\s*)$', lambda m: _case('turing' if nxt == 'engine' else 'code', m.group(1)) + m.group(2), lit)
        new, keep = literal_value(lit)
        if keep and IDENT_RE.fullmatch(lit):
            self.names.add(lit)
        if self.lfm:
            # an .lfm value is display text or a name the form itself uses: always renamed
            new = tmap(rename_text(lit))
            keep = False
        if new != lit:
            self.literals += 1
        if not keep:
            return "'" + new + "'"
        pk, pt = neighbour(k, -1)
        nk, nt = neighbour(k, +1)
        # a case label (or a list of them: 'a','b': ...) must be a constant
        step = 1
        while neighbour(k, step)[1] == ',' and neighbour(k, step + 1)[0] == 'str':
            step += 2
        case_label = neighbour(k, step)[1] == ':' and neighbour(k, step + 1)[1] != '='
        if not code or case_label:
            self.constants.append((lit, 'case label' if case_label else 'declaration'))
            return "'" + tmap(rename_text(lit)) + "'"
        # in code: keep the value, hide the word.  A whole call argument may need to be a PChar (lua_register, ...).
        self.split += 1
        expr = split_expr(new, pchar=(pt in ('(', ',') and nt in (')', ',')))
        joined_before = pk == 'other' and pt.startswith('#')
        joined_after = nk == 'other' and nt.startswith('#') or nk == 'str'
        return ('+' if joined_before else '') + expr + ('+' if joined_after else '')


# ------------------------------------------------------------------------------------------------------ the pictures

def draw_mark(size):
    """The Turing Explorer mark: a rounded square, deep blue to teal, with a white T and a small lens."""
    from PIL import Image, ImageDraw
    ss = 4
    S = size * ss
    img = Image.new('RGBA', (S, S), (0, 0, 0, 0))
    grad = Image.new('RGBA', (S, S))
    gp = grad.load()
    c0, c1 = (15, 23, 42), (14, 116, 144)
    for y in range(S):
        for x in range(S):
            t = (x + y) / (2.0 * (S - 1))
            gp[x, y] = tuple(int(c0[k] + (c1[k] - c0[k]) * t) for k in range(3)) + (255,)
    mask = Image.new('L', (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, S - 1, S - 1], radius=int(S * 0.22), fill=255)
    img.paste(grad, (0, 0), mask)
    d = ImageDraw.Draw(img)
    w = (255, 255, 255, 255)
    d.rectangle([int(S * 0.20), int(S * 0.22), int(S * 0.80), int(S * 0.36)], fill=w)     # the T
    d.rectangle([int(S * 0.43), int(S * 0.22), int(S * 0.57), int(S * 0.80)], fill=w)
    r = S * 0.13                                                                       # the lens
    cx, cy = S * 0.72, S * 0.70
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(103, 232, 249, 255), width=max(ss, int(S * 0.055)))
    return img.resize((size, size), Image.LANCZOS)


# The art (--art): 'purple' (the default) -- Cheat Engine's own icon and logos with its blue turned purple; 'ce' --
# Cheat Engine's, unchanged; 'mark' -- the generated Turing Explorer mark.  Three places: the program icon (the exe's
# MAINICON, every window's icon, the tray), the logo bitmap on the main form and in the about box (47x68, .lfm), and
# the bigger logo the main form loads instead on a high-DPI screen (IMAGES_CELOGO in Images.res).
ART = ('purple', 'ce', 'mark')


def purple(r, g, b):
    """Cheat Engine's blue (hue 180-210 degrees) turned purple; black, white and grey stay."""
    h, s, v = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
    deg = h * 360
    if not 150 <= deg <= 250:
        return r, g, b
    r, g, b = colorsys.hsv_to_rgb((278 + (deg - 195) * 0.5) / 360.0, s, v)
    return int(round(r * 255)), int(round(g * 255)), int(round(b * 255))


def purple_image(img):
    img = img.convert('RGBA')
    p = img.load()
    for y in range(img.size[1]):
        for x in range(img.size[0]):
            r, g, b, a = p[x, y]
            p[x, y] = purple(r, g, b) + (a,)
    return img


def purple_bmp(bmp):
    """A BMP file with its pixels recolored in place (same size, same header): 24/32 bit, uncompressed."""
    off = struct.unpack_from('<I', bmp, 10)[0]
    w, h = struct.unpack_from('<ii', bmp, 18)
    bpp, comp = struct.unpack_from('<HI', bmp, 28)
    if bpp not in (24, 32) or comp != 0:
        raise SystemExit('rebrand: a logo bitmap with %d bits per pixel, compression %d: not handled' % (bpp, comp))
    out = bytearray(bmp)
    stride = (w * bpp + 31) // 32 * 4
    for row in range(abs(h)):
        for x in range(w):
            i = off + row * stride + x * (bpp // 8)
            b, g, r = out[i:i + 3]
            r, g, b = purple(r, g, b)
            out[i:i + 3] = bytes((b, g, r))
    return bytes(out)


def write_icon(path, art='mark'):
    # BMP entries: Lazarus 2.2 reads the small sizes of an icon as bitmaps only (a PNG entry fails at startup with
    # "Bitmap with unknown compression")
    from PIL import Image
    if art == 'mark':
        big, sizes = draw_mark(256), [16, 24, 32, 48, 64, 128, 256]
    else:                                   # purple: Cheat Engine's icon (one 128x128 picture), recolored
        with Image.open(path) as ico:
            big = purple_image(ico.copy())
        sizes = [16, 24, 32, 48, 64, 128]
    big.save(path, format='ICO', sizes=[(s, s) for s in sizes], bitmap_format='bmp')


def write_png(path, art):
    """images\\celogo.png (128x128, the high-DPI logo): recolored, or the mark."""
    from PIL import Image
    if art == 'mark':
        img = draw_mark(128)
    else:
        with Image.open(path) as im:
            img = purple_image(im.copy())
    img.save(path, format='PNG')
    with open(path, 'rb') as h:
        return h.read()


def res_replace(path, name, data):
    """A compiled .res file with the data of one resource (by name) replaced."""
    with open(path, 'rb') as h:
        d = h.read()
    out, o, found = bytearray(), 0, False
    while o + 8 <= len(d):
        ds, hs = struct.unpack_from('<II', d, o)
        hdr, body = bytearray(d[o:o + hs]), d[o + hs:o + hs + ds]
        q, ids = o + 8, []
        for _ in range(2):                                  # type, name: 0xFFFF + ordinal, or a UTF-16 string
            if struct.unpack_from('<H', d, q)[0] == 0xFFFF:
                ids.append(struct.unpack_from('<H', d, q + 2)[0])
                q += 4
            else:
                e = q
                while struct.unpack_from('<H', d, e)[0]:
                    e += 2
                ids.append(d[q:e].decode('utf-16le'))
                q = e + 2
        if ids[1] == name:
            body, found = data, True
            struct.pack_into('<I', hdr, 0, len(body))
        out += hdr + body
        out += b'\0' * (-len(out) % 4)
        o = (o + hs + ds + 3) & ~3
    if not found:
        raise SystemExit('rebrand: %s: no resource %s' % (path, name))
    with open(path, 'wb') as h:
        h.write(out)


def logo_picture_data(width, height):
    """LFM Picture.Data for a TImage: <len>TPortableNetworkGraphic, <u32 size>, PNG."""
    import io
    from PIL import Image
    side = min(width, height)
    mark = draw_mark(side)
    canvas = Image.new('RGBA', (width, height), (0, 0, 0, 0))
    canvas.paste(mark, ((width - side) // 2, (height - side) // 2), mark)
    b = io.BytesIO()
    canvas.save(b, format='PNG')
    png = b.getvalue()
    cls = b'TPortableNetworkGraphic'
    return bytes([len(cls)]) + cls + struct.pack('<I', len(png)) + png


PIC_RE = re.compile(r'(?P<indent>[ \t]*)Picture\.Data = \{(?P<hex>[0-9A-Fa-f\s]*)\}')


def replace_logos(text, stats, art):
    """Every Picture.Data that holds Cheat Engine's 47x68 logo bitmap: recolored (purple), or the mark."""
    def sub(m):
        raw = bytes.fromhex(re.sub(r'\s', '', m.group('hex')))
        if not raw.startswith(b'\x07TBitmap') or raw[12:14] != b'BM':   # <len>TBitmap <u32 size> BM...
            return m.group(0)
        w, h = struct.unpack_from('<ii', raw[12:], 18)
        if (w, abs(h)) != (47, 68):
            return m.group(0)
        if art == 'mark':
            data = logo_picture_data(47, 68).hex().upper()
        else:
            data = (raw[:12] + purple_bmp(raw[12:])).hex().upper()
        ind = m.group('indent')
        lines = [ind + '  ' + data[k:k + 64] for k in range(0, len(data), 64)]
        stats['logos'] += 1
        return ind + 'Picture.Data = {\n' + '\n'.join(lines) + '\n' + ind + '}'
    return PIC_RE.sub(sub, text)


# ---------------------------------------------------------------------------------------------------------- stage

SKIP_DIRS = {'bin', 'lib', 'backup', '__history', '.git', '.vs', 'test', 'unitbin'}
# cheatengine.res is generated by the build (version info, icon, manifest); the other .res files are inputs
SKIP_FILES = re.compile(r'(?i).*\.(lps|ppu|o|a|rsj|lrj|dbg|exe|dll|pdb|obj|ilk)$|cedebug\.txt$|cheatengine\.res$')
PAS_EXT = {'.pas', '.pp', '.inc', '.lpr', '.lfm'}


def external_identifiers():
    """Identifiers Lazarus and FPC declare that contain one of the words (Cheat Engine's code may use them)."""
    found = set()
    for root, dirs, files in os.walk(LAZARUS):
        for f in files:
            if os.path.splitext(f)[1].lower() not in ('.pas', '.pp', '.inc', '.lpr'):
                continue
            try:
                with open(os.path.join(root, f), 'rb') as h:
                    t = h.read().decode('latin-1')
            except OSError:
                continue
            for m in EXT_RE.finditer(t):
                found.add(m.group(0).lower())
    return found


EXT_RE = re.compile(r'[A-Za-z0-9_]*(?:%s)[A-Za-z0-9_]*' % '|'.join(w for w, _ in WORDS), re.I)


def stage(src, dst, art='purple'):
    src = os.path.abspath(src)
    dst = os.path.abspath(dst)
    cache = os.path.join(dst, 'lazarus-identifiers.txt')       # (the scan takes a while; kept across runs)
    key = '# ' + ' '.join(w for w, _ in WORDS) + ' | ' + LAZARUS
    external = None
    if os.path.isfile(cache):
        with open(cache) as h:
            lines = h.read().splitlines()
        if lines and lines[0] == key:
            external = set(lines[1:])
    if os.path.isdir(dst):
        shutil.rmtree(dst)
    if external is None:
        external = external_identifiers()
    os.makedirs(dst)
    with open(cache, 'w') as h:
        h.write('\n'.join([key] + sorted(external)))
    # pass 1: the names that keep their value in every literal (see KEPT)
    KEPT.clear()
    for root, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs if d.lower() not in SKIP_DIRS]
        for f in files:
            if os.path.splitext(f)[1].lower() in PAS_EXT - {'.lfm'} and not SKIP_FILES.match(f):
                with open(os.path.join(root, f), 'rb') as h:
                    for kind, t in tokens(h.read().decode('latin-1')):
                        if kind == 'str':
                            collect_kept(t)
    stats = {'files': 0, 'changed': 0, 'literals': 0, 'logos': 0, 'idents': 0, 'split': 0, 'renamed': 0}
    constants = []
    names = set()
    for root, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs if d.lower() not in SKIP_DIRS]
        rel = os.path.relpath(root, src)
        out = os.path.join(dst, wmap(rename_text(rel))) if rel != '.' else dst
        os.makedirs(out, exist_ok=True)
        for f in files:
            if SKIP_FILES.match(f):
                continue
            sp = os.path.join(root, f)
            nf = wmap(rename_text(f))
            if nf != f:
                stats['renamed'] += 1
            dp = os.path.join(out, nf)
            ext = os.path.splitext(f)[1].lower()
            stats['files'] += 1
            if ext in PAS_EXT:
                with open(sp, 'rb') as h:
                    text = h.read().decode('latin-1')
                p = Pascal(external, lfm=(ext == '.lfm'))
                new = p.run(text)
                if ext == '.lfm' and art != 'ce':
                    new = replace_logos(new, stats, art)
                stats['literals'] += p.literals
                stats['idents'] += p.idents
                stats['split'] += p.split
                constants += [(os.path.relpath(dp, dst), lit, why) for lit, why in p.constants]
                names |= p.names
                if new != text:
                    stats['changed'] += 1
                with open(dp, 'wb') as h:
                    h.write(new.encode('latin-1'))
            else:
                shutil.copy2(sp, dp)

    project(os.path.join(dst, PROJECT + '.lpi'))
    # the program icon (cheatengine.ico, copied as turingexplorer.ico) and the high-DPI logo: see ART
    if art != 'ce':
        write_icon(os.path.join(dst, PROJECT + '.ico'), art)
        res_replace(os.path.join(dst, 'Images.res'), 'IMAGES_CELOGO',
                    write_png(os.path.join(dst, 'images', 'celogo.png'), art))
        stats['logos'] += 2
    # the window titles: no Cheat Engine version number next to the new name (ceversion, the number Lua's
    # getCEVersion() returns and tables test, stays)
    edit_file(os.path.join(dst, PROJECT + '.lpr'), r"Application\.Title:='[^']*'", "Application.Title:='%s'" % NAME)
    edit_file(os.path.join(dst, 'MainUnit2.pas'), r"strVersionPart='[^']*'", "strVersionPart='1.0'")
    with open(os.path.join(dst, 'rebrand-names.txt'), 'w') as h:
        h.write('\n'.join(sorted(names)))
    with open(os.path.join(dst, 'rebrand-kept.txt'), 'w') as h:
        h.write('\n'.join(sorted(KEPT)))
    with open(os.path.join(dst, 'rebrand-constants.txt'), 'w') as h:
        h.write('# literals that keep a name other code relies on, renamed because the language needs a constant there\n')
        for f, lit, why in constants:
            h.write('%s\t%s\t%s\n' % (f, why, lit))
    print('stage: %(files)d files (%(renamed)d renamed), %(changed)d rewritten: %(literals)d literals, %(idents)d '
          'identifiers, %(split)d names rebuilt at run time' % stats)
    print('stage: art %s: %d pictures changed (icon, logos)' % (art, stats['logos']))
    print('stage: %d constants renamed (rebrand-constants.txt)' % len(constants))
    return stats


def edit_file(path, pattern, repl):
    with open(path, 'rb') as h:
        t = h.read().decode('latin-1')
    t, n = re.subn(pattern, lambda m: repl, t, count=1)
    if n != 1:
        raise SystemExit('rebrand: %s: %s not found' % (path, pattern))
    with open(path, 'wb') as h:
        h.write(t.encode('latin-1'))


LPI_PATH_RE = re.compile(r'(<(?:Filename|UnitName|OtherUnitFiles|IncludeFiles|SrcPath|ObjectPath|Libraries|ComponentName)'
                         r' Value=")([^"]*)(")')


def project(lpi):
    with open(lpi, 'rb') as h:
        t = h.read().decode('utf-8')
    t = re.sub(r'<Title Value="[^"]*"/>', '<Title Value="%s"/>' % NAME, t, count=1)
    t = re.sub(r'<TextName Value="[^"]*"/>', '<TextName Value="Turing.Explorer"/>', t, count=1)
    t = re.sub(r'<TextDesc Value="[^"]*"/>', '<TextDesc Value="%s"/>' % NAME, t, count=1)
    t = re.sub(r'<AutoIncrementBuild Value="True"/>', '<AutoIncrementBuild Value="False"/>', t, count=1)
    t = re.sub(r'<MajorVersionNr Value="\d+"/>', '<MajorVersionNr Value="1"/>', t, count=1)
    t = re.sub(r'<MinorVersionNr Value="\d+"/>', '<MinorVersionNr Value="0"/>', t, count=1)
    t = re.sub(r'<BuildNr Value="\d+"/>', '<BuildNr Value="0"/>', t, count=1)
    t = re.sub(r'<StringTable [^>]*/>',
               '<StringTable CompanyName="Turing" FileDescription="%s" InternalName="%s" OriginalFilename="%s.exe" '
               'ProductName="%s" ProductVersion="1.0"/>' % (NAME, EXE, EXE, NAME), t, count=1)
    t = t.replace('bin\\cheatengine-$(TargetCPU)-SSE4-AVX2', 'bin\\%s-SSE4-AVX2' % EXE)
    t = t.replace('bin\\cheatengine-$(TargetCPU)', 'bin\\' + EXE)
    t = re.sub(r'<CustomOptions Value="', '<CustomOptions Value="-dTURING_EXPLORER\n', t)
    # the files and folders were renamed with the same map
    t = LPI_PATH_RE.sub(lambda m: m.group(1) + wmap(rename_text(m.group(2))) + m.group(3), t)
    if 'bin\\cheatengine' in t:
        raise SystemExit('rebrand: an output name in the project was not renamed')
    with open(lpi, 'wb') as h:
        h.write(t.encode('utf-8'))


# ----------------------------------------------------------------------------------------------------------- dist

# what the program reads at run time from its own folder (from the repository's bin\, which git tracks)
DIST_FILES = ['main.lua', 'defines.lua', 'class.lua', 'classwrapper.lua', 'commonmodulelist.txt', 'donottrace.txt',
              'lua53-64.dll', 'thvbridge.exe', 'turinghv.dll']
DIST_DIRS = ['autorun', 'include', 'clibs64', 'win64']
# left out: the update check and the online table sharing (they call home), DLLs made for injecting into a game, and
# the scripts of features that cannot work with the hypervisor backend: ultimap2 (the kernel driver), speedhack, the
# Lua hook, mono and java (they inject into the game), the Android tools (ceserver)
DIST_SKIP = re.compile(r'(?i)^(autorun[\\/](versioncheck\.lua|ceshare\.lua|ceshare([\\/].*)?|dlls([\\/].*)?'
                       r'|ultimap2\.lua|forms[\\/]frmultimap2\.frm|speedhackv3\.lua|luahook\.lua|monoscript\.lua'
                       r'|java\.lua|javainfo\.lua|javasearch\.lua|andtools\.lua|andtools([\\/].*)?)'
                       r'|win64[\\/]old([\\/].*)?)$')
TEXT_EXT = {'.lua', '.txt', '.frm', '.xml', '.h', '.c', '.cpp', '.md', '.po', '.cea', '.ini', '.fx'}
LUA_EXT = {'.lua'}
# names earlier versions of this script put in the output folder
LEGACY = {'thvbridge.exe'}
# lists of Cheat Engine's own module names (renamed in the program the same way)
WMAP_FILES = {'commonmodulelist.txt'}


def lua_tokens(text):
    """(kind, text) for Lua: comment, str (the whole quoted string), ident, other."""
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if text.startswith('--', i):
            m = re.match(r'--\[(=*)\[', text[i:])
            if m:
                close = ']' + m.group(1) + ']'
                j = text.find(close, i + len(m.group(0)))
                j = n if j < 0 else j + len(close)
            else:
                j = text.find('\n', i)
                j = n if j < 0 else j
            yield 'comment', text[i:j]
            i = j
        elif c == '[' and re.match(r'\[(=*)\[', text[i:]):
            m = re.match(r'\[(=*)\[', text[i:])
            close = ']' + m.group(1) + ']'
            j = text.find(close, i + len(m.group(0)))
            j = n if j < 0 else j + len(close)
            yield 'str', text[i:j]
            i = j
        elif c in '"\'':
            j = i + 1
            while j < n and text[j] != c and text[j] != '\n':
                j += 2 if text[j] == '\\' else 1
            yield 'str', text[i:j + 1]
            i = j + 1
        elif c.isalpha() or c == '_':
            j = i + 1
            while j < n and (text[j].isalnum() or text[j] == '_'):
                j += 1
            yield 'ident', text[i:j]
            i = j
        else:
            yield 'other', c
            i += 1


def lua_split(name):
    """_G["getChe".."atEngineDir"]: the same global, without the word in the file (Lua does not fold string concats)."""
    cut = WORD_RE.search(name)
    k = cut.start() + max(1, (cut.end() - cut.start()) // 2)
    return '_G["%s".."%s"]' % (name[:k], name[k:])


def lua_rewrite(text, names, report):
    """Comments: renamed.  Strings: the brand renamed.  The program's own Lua functions whose names hold a word
    (getCheatEngineDir, cheatEngineIs64Bit, ...) are called through _G with the name rebuilt at run time."""
    toks = list(lua_tokens(text))
    out = []
    prev = ''

    def next_sig(k):
        for kk in range(k + 1, len(toks)):
            if toks[kk][0] != 'comment' and not toks[kk][1].isspace():
                return toks[kk][1]
        return ''

    for k, (kind, t) in enumerate(toks):
        if kind == 'comment':
            out.append(tmap(rename_text(t)))
        elif kind == 'str':
            body = re.sub(r'^(\[=*\[|["\'])|(\]=*\]|["\'])$', '', t)
            # a string that is one name (a settings key, a class or form name) keeps its value; text is renamed
            out.append(rename_text(t, spaced_only=True) if IDENT_RE.fullmatch(body) else tmap(rename_text(t)))
        elif kind == 'ident' and t in names and prev not in ('.', ':', 'function', 'local') and next_sig(k) == '(':
            out.append(lua_split(t))
        elif kind == 'ident' and WORD_RE.search(t) and t not in names and prev not in ('.', ':'):
            out.append(wmap(t))                 # the script's own name (a local, a parameter, its own function)
        else:
            if kind == 'ident' and WORD_RE.search(t):
                report.add(t)
            out.append(t)
        if kind != 'comment' and not t.isspace():
            prev = t
    return ''.join(out)

# thvbridge.exe is trusted by the hypervisor by its measured CODE pages; its help text lives in .rdata.  Same-length
# replacements keep every code page byte for byte, so the trust still holds (checked with --selftest afterwards).
BRIDGE_TEXT = [(b"Cheat Engine's bridge", b"the explorer's bridge"),
               (b'Cheat Engine starts it', b'the explorer starts it'),
               (b'thvbridge', b'te-broker')]


def pe_scrub(path):
    """Removes the Authenticode signature (its certificate names the signer) and shortens the CodeView PDB path to its
    bare file name.  The code is not touched."""
    with open(path, 'rb') as h:
        b = bytearray(h.read())
    if b[:2] != b'MZ':
        return False
    pe = struct.unpack_from('<I', b, 0x3c)[0]
    if b[pe:pe + 4] != b'PE\0\0':
        return False
    opt = pe + 24
    magic = struct.unpack_from('<H', b, opt)[0]
    dd = opt + (112 if magic == 0x20b else 96)
    nsec = struct.unpack_from('<H', b, pe + 6)[0]
    sopt = struct.unpack_from('<H', b, pe + 20)[0]
    secs = []
    for k in range(nsec):
        s = opt + sopt + 40 * k
        vsz, va, rsz, raw = struct.unpack_from('<IIII', b, s + 8)
        secs.append((va, max(vsz, rsz), raw))

    def rva2off(rva):
        for va, sz, raw in secs:
            if va <= rva < va + sz:
                return rva - va + raw
        return None

    changed = False
    coff, csz = struct.unpack_from('<II', b, dd + 4 * 8)          # the certificate table: a FILE offset
    if coff and csz:
        if coff + csz >= len(b) - 8:
            del b[coff:]
        else:
            b[coff:coff + csz] = bytes(csz)
        struct.pack_into('<II', b, dd + 4 * 8, 0, 0)
        changed = True
    drva, dsz = struct.unpack_from('<II', b, dd + 6 * 8)          # the debug directory
    doff = rva2off(drva) if drva else None
    if doff is not None:
        for k in range(dsz // 28):
            e = doff + 28 * k
            typ, size, _, praw = struct.unpack_from('<IIII', b, e + 12)
            if typ == 2 and b[praw:praw + 4] == b'RSDS':
                p0 = praw + 24
                p1 = b.index(0, p0)
                name = os.path.basename(bytes(b[p0:p1]).decode('latin-1').replace('\\', '/')).encode()
                b[p0:p1] = name + bytes(p1 - p0 - len(name))
                changed = True
    if changed:
        struct.pack_into('<I', b, opt + 64, 0)        # CheckSum (not checked for user-mode DLLs)
        with open(path, 'wb') as h:
            h.write(b)
    return changed


def patch_bridge(path):
    """Same-length text replacements, only inside sections that are not executable (the measured code stays)."""
    with open(path, 'rb') as h:
        b = bytearray(h.read())
    pe = struct.unpack_from('<I', b, 0x3c)[0]
    nsec = struct.unpack_from('<H', b, pe + 6)[0]
    sopt = struct.unpack_from('<H', b, pe + 20)[0]
    n = 0
    for k in range(nsec):
        s = pe + 24 + sopt + 40 * k
        rsz, raw = struct.unpack_from('<II', b, s + 16)
        chars = struct.unpack_from('<I', b, s + 36)[0]
        if chars & 0x20000000:                     # IMAGE_SCN_MEM_EXECUTE
            continue
        part = bytes(b[raw:raw + rsz])
        for old, new in BRIDGE_TEXT:
            assert len(old) == len(new)
            n += part.count(old)
            part = part.replace(old, new)
        b[raw:raw + rsz] = part
    with open(path, 'wb') as h:
        h.write(b)
    return n


def dist(src, stg, out):
    src_bin = os.path.join(os.path.abspath(src), 'bin')
    out = os.path.abspath(out)
    os.makedirs(out, exist_ok=True)
    exe = os.path.join(stg, 'bin', EXE + '.exe')
    if not os.path.isfile(exe):
        raise SystemExit('dist: %s is missing (build the staged project first)' % exe)
    shutil.copy2(exe, os.path.join(out, EXE + '.exe'))
    items = list(DIST_FILES)
    for d in DIST_DIRS:
        for root, dirs, files in os.walk(os.path.join(src_bin, d)):
            for f in files:
                items.append(os.path.relpath(os.path.join(root, f), src_bin))
    items = [r for r in items if not DIST_SKIP.match(r)]
    with open(os.path.join(stg, 'rebrand-names.txt')) as h:
        names = set(h.read().split())
    lua_left = set()
    n = 0
    for rel in items:
        sp = os.path.join(src_bin, rel)
        if not os.path.isfile(sp):
            raise SystemExit('dist: %s is missing' % sp)
        dp = os.path.join(out, rename_text(rel, spaced_only=True))
        os.makedirs(os.path.dirname(dp), exist_ok=True)
        ext = os.path.splitext(rel)[1].lower()
        if ext in TEXT_EXT:
            with open(sp, 'rb') as h:
                t = h.read().decode('latin-1')
            if ext in LUA_EXT:
                t = lua_rewrite(t, names, lua_left)
            elif os.path.basename(rel).lower() in WMAP_FILES:
                t = wmap(rename_text(t))
            elif ext in ('.h', '.c', '.cpp'):
                t = tmap(rename_text(t))      # the C compiler's headers: the "cheatengine" macro, in every header alike
            else:
                t = rename_text(t, spaced_only=True)
            with open(dp, 'wb') as h:
                h.write(t.encode('latin-1'))
        else:
            shutil.copy2(sp, dp)
            if os.path.basename(rel).lower() == 'thvbridge.exe':
                patch_bridge(dp)
            elif ext == '.dll' and os.path.basename(rel).lower() not in ('dbghelp.dll', 'symsrv.dll', 'sqlite3.dll', 'turinghv.dll'):
                pe_scrub(dp)
        n += 1
    # gone from the list since the last run: remove (a left-over script would still run from autorun)
    keep = {os.path.normcase(os.path.join(out, EXE + '.exe'))}
    keep |= {os.path.normcase(os.path.join(out, rename_text(r, spaced_only=True))) for r in items}
    for root, dirs, files in os.walk(out):
        for f in files:
            p = os.path.join(root, f)
            rel = os.path.relpath(p, out)
            if os.path.normcase(p) not in keep and (rel.split(os.sep)[0] in DIST_DIRS or rel.lower() in LEGACY):
                os.remove(p)
    print('dist: %s (%d files)' % (out, n + 1))
    if lua_left:
        print('dist: Lua names with a word left as they are (script-local or fields): %s' % ' '.join(sorted(lua_left)))


# ----------------------------------------------------------------------------------------------------------- scan

SCAN_WORDS = ['cheat engine', 'cheatengine', 'cheat-engine', 'cheat_engine', 'dark byte', 'darkbyte', 'cheat table',
              'runtime modifier'] + [w for w, _ in WORDS if w not in ('cheatengine', 'darkbyte')]


def scan(folder, show=4, words=None):
    folder = os.path.abspath(folder)
    words = words or SCAN_WORDS
    total = 0
    pats = []
    for w in words:
        pats.append((w, re.compile(re.escape(w).encode(), re.I)))
        pats.append((w + ' (utf-16)', re.compile(b'\0'.join(re.escape(ch).encode() for ch in w) + b'\0', re.I)))
    per_word = {}
    for root, dirs, files in os.walk(folder):
        for f in sorted(files):
            p = os.path.join(root, f)
            rel = os.path.relpath(p, folder)
            hits = []
            for w in words:
                if w in rel.lower():
                    hits.append(('file name', rel))
            with open(p, 'rb') as h:
                b = h.read()
            for w, rx in pats:
                for m in rx.finditer(b):
                    wl = w.replace(' (utf-16)', '')
                    step = 2 if '(utf-16)' in w else 1
                    if wl in INNER and m.start() >= step and chr(b[m.start() - step]).isalpha() and chr(b[m.start()]).islower():
                        continue                    # inside another word: ServicePack, oldbkmode
                    ctx = b[max(0, m.start() - 40):m.end() + 40]
                    if '(utf-16)' in w:
                        ctx = ctx.replace(b'\0', b'')
                    ctx = re.sub(rb'[^\x20-\x7e]', b'.', ctx).decode()
                    hits.append((w, ctx))
                    per_word[w.replace(' (utf-16)', '')] = per_word.get(w.replace(' (utf-16)', ''), 0) + 1
            if hits:
                total += len(hits)
                print('%s: %d' % (rel, len(hits)))
                for w, ctx in hits[:show]:
                    print('    [%s] %s' % (w, ctx))
    print('scan: %d hit(s) in %s  %s' % (total, folder, ' '.join('%s=%d' % kv for kv in sorted(per_word.items()))))
    return total


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('cmd', choices=['stage', 'dist', 'scan', 'icon'])
    ap.add_argument('--src')
    ap.add_argument('--stage')
    ap.add_argument('--dist')
    ap.add_argument('--show', type=int, default=4)
    ap.add_argument('--art', choices=ART, default='purple',
                    help='stage: the icon and logos -- Cheat Engine\'s recolored purple, unchanged, or the generated mark')
    a = ap.parse_args()
    if a.cmd == 'stage':
        stage(a.src, a.stage, art=a.art)
    elif a.cmd == 'dist':
        dist(a.src, a.stage, a.dist)
    elif a.cmd == 'icon':
        write_icon(a.dist)
    else:
        sys.exit(1 if scan(a.dist, a.show) else 0)


if __name__ == '__main__':
    main()
