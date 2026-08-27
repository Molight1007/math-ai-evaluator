# -*- coding: utf-8 -*-
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from intern_s1 import _clean_answer, _looks_like_reasoning_fragment, _extract_tail_fallback
print("clean('  : 3.5  ') =", repr(_clean_answer("  : 3.5  ")))
print("clean('1. If we set x=1') =", repr(_clean_answer("1. If we set x=1")))
print("frag('3.5') =", _looks_like_reasoning_fragment("3.5"))
print("frag('If we set x=1') =", _looks_like_reasoning_fragment("If we set x=1"))
print("tail('line1\\nline2\\nanswer = 8') =", repr(_extract_tail_fallback("line1\nline2\nanswer = 8")))
