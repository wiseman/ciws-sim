"""Count the voice code's lines in a copy of index.html: the tables, the AudioController voice
methods and the game glue that calls them.

Usage: python3 docs/voice/count_lines.py [index.html]
Tables: after LAUNCH_ALARM up to the DSP toolkit. Methods: buildCIC up to playVLSLaunch. Glue:
lines elsewhere that name the voice API. Counted without blank lines, and (raw) with them.
"""
import re
import sys

lines = open(sys.argv[1] if len(sys.argv) > 1 else "index.html").read().split("\n")


def span(start, end):
    a = next(i for i, l in enumerate(lines) if re.search(start, l))
    b = next(i for i, l in enumerate(lines) if i > a and re.search(end, l))
    return a, b


tables = span(r"const LAUNCH_ALARM", r"// Small offline DSP toolkit")
tables = (tables[0] + 1, tables[1])
methods = span(r"// Inside the ship: the alarms", r"// `at` delays the launch itself")
GLUE = re.compile(r"AudioController\.(announce\w+|noteThreat|warnVLSLaunch|play|prepare)\b|loadCallouts|"
                  r"\bcic\b|paQueue|killCallout|bucketState|calloutBytes|busyUntil|lazyCallouts|holdRadio")
inside = set(range(*tables)) | set(range(*methods))
count = lambda r: sum(1 for i in r if lines[i].strip())
glue = sum(1 for i, l in enumerate(lines) if i not in inside and l.strip() and GLUE.search(l))
t, m = count(range(*tables)), count(range(*methods))
raw = tables[1] - tables[0] + methods[1] - methods[0] + glue
print(f"tables {t}  methods {m}  glue {glue}  total {t + m + glue}  (raw {raw}; file {len(lines)} lines)")
