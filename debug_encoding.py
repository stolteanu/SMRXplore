import ast
import sys
import traceback
from importlib.machinery import SourceFileLoader

path = "src/viz/render_dashboard.py"
print("Python:", sys.version)

loader = SourceFileLoader("src.viz.render_dashboard", path)
try:
    src = loader.get_source("render_dashboard")
    print("get_source: OK,", len(src), "chars")
except Exception as e:
    print("get_source FAILED:", type(e).__name__, e)
    traceback.print_exc()

with open(path, "rb") as f:
    raw = f.read()
print("raw bytes:", len(raw))
try:
    raw.decode("utf-8", errors="strict")
    print("strict utf-8 decode: OK")
except Exception as e:
    print("strict utf-8 decode FAILED:", e)

try:
    co = compile(raw, path, "exec", ast.PyCF_ONLY_AST, True)
    print("compile(raw bytes): OK")
except Exception as e:
    print("compile(raw bytes) FAILED:", type(e).__name__, e)
    traceback.print_exc()
