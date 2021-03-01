# coding=utf-8
# Released under MIT License
"""Checks a file or directory for unprefixed strings. Meant to be used when
porting to Python 3. Run with a Python 2 interpreter."""
from __future__ import print_function

__author__ = u'Infernio'

import ast
import codecs
import os
import re
import sys
from collections import defaultdict

# This is the worst regex I've ever written. It's basically just hacks to allow
# this script to even parse certain WB files
OTHER_PREFIX_REGEX = re.compile(
    r"\b(b|r)('|\")(?!\)|]|}|,|:| (?:\+|%)| in )(?=.)")
CODING_REGEX = re.compile(u'# ?-\*- coding: ?utf-8 -\*-')
DOCSTRING_REGEX = re.compile(r'^([ ]*)(r?""")(.*)')
DOCSTRING_REGEX_END = re.compile(r'"""([ ]*#.*)?$')
unidoc = u'u"""' # for bolt     htmlHead = u"""...

# The parser discards b'' and r'' prefixes, so add something to the string
# that's almost certainly not going to appear normally
parsing_docstring = in_uni_str = False
def _process(line):
    global parsing_docstring, in_uni_str
    if CODING_REGEX.match(line): return u'# was coding, ignore'
    # Docstrings are an exception, those can contain unquoted strings
    if not parsing_docstring:
        one_line = DOCSTRING_REGEX_END.search(line)
        if in_uni_str and one_line:
            in_uni_str = False
            return line
        elif unidoc in line:
            in_uni_str = True
            return line
        ma_docs = DOCSTRING_REGEX.search(line)
        if ma_docs:
            parsing_docstring = (not one_line) or line.strip() == u'"""'
            line_ = ma_docs.group(1) + ma_docs.group(2) + (
                u'$IGNORE$' if ma_docs.group(3) else u'') + (
                        u'"""' if one_line and not parsing_docstring else u'')
            return line_
    else:
        end = DOCSTRING_REGEX_END.search(line)
        if not end: return u''
        parsing_docstring = False
        return u'"""'
    if u'open(' in line: return line # avoid a ton of false positives
    ma_b = OTHER_PREFIX_REGEX.search(line)
    while ma_b:
        if u"u'b'" in line:
            return line
        line = OTHER_PREFIX_REGEX.sub(u'%s%s$IGNORE$' % (
            ma_b.group(1), ma_b.group(2)), line, count=1)
        # Remember to account for the substitution, 8 == len(u'$IGNORE$')
        ma_b = OTHER_PREFIX_REGEX.search(line, ma_b.end(2) + 8)
    return line

def _check_file(f):
    # all WB files are in UTF-8
    with codecs.open(f, u'r', u'utf8') as ins:
        if f.endswith(u'bolt.py'):
            print(u'gotcha')
        lines = [_process(l) for l in ins.read().splitlines()]
    root = ast.parse(u'\n'.join(lines), filename=f)
    lineno = 0
    col_offset = 0
    unprefixed = defaultdict(list)
    for node in ast.walk(root):
        if hasattr(node, u'lineno'):
            lineno = node.lineno
        if hasattr(node, u'col_offset'):
            col_offset = node.col_offset
        if isinstance(node, ast.Str):
            str_val = node.s
            if str_val.startswith(b'$IGNORE$'): continue # b''-prefixed string
            elif type(str_val) == unicode: continue    # u''-prefixed string
            else:
                try:
                    unprefixed[(lineno, col_offset)].append(u"'%s'" % str_val)
                except UnicodeDecodeError:
                    unprefixed[(lineno, col_offset)].append(
                        u'<failed to encode, should probably be a bytestring>')
    for (lineno, col_offset), msgs in sorted(unprefixed.iteritems()):
        for msg in msgs:
            print(u'Unprefixed string on line %u, character %u: %s' % (
                lineno, col_offset, msg))
    found = sum(len(m) for m in unprefixed.itervalues())
    if found:
        # print(u"==> Checking file '%s'" % f)
        print(u'%s: Found %u unprefixed strings.\n' % (f, found))
        # __ = input(u'> ')
    return found

if __name__ == u'__main__':
    if len(sys.argv) < 2:
        raise RuntimeError(u'Syntax: find_unprefixed <python file or dir>')
    # First, check what we actually have to parse
    file_arg = os.path.abspath(sys.argv[1])
    if os.path.isfile(file_arg):
        if not os.path.splitext(file_arg)[1].lower() == u'.py':
            raise RuntimeError(u"'%s' is not a python file" % file_arg)
        target_files = [file_arg] # Just the specified file
    elif os.path.isdir(file_arg):
        target_files = []
        # The full directory tree, so walk it
        for root_dir, dirs, files in os.walk(file_arg):
            target_files.extend([os.path.join(root_dir, f) for f in files
                                 if os.path.splitext(f)[1] == u'.py'])
    else:
        raise RuntimeError(u"'%s' does not exist." % file_arg)
    print()
    # To count of all found strings
    total = 0
    files_with_unprefixed = {}
    for f in sorted(target_files):
        found = _check_file(f)
        if found:
            total += found
            files_with_unprefixed[f] = found
    print(u'==> Total unprefixed strings found: %u' % total)
    print()
    print(u'==> Unprefixed strings per file:\n')
    for t in sorted(files_with_unprefixed.items(), key=lambda v: v[1],
                    reverse=True):
        print(u'%s: %s' % t)
    print()
