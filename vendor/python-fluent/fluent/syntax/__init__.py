# MsgBranch packaging shim: exports only the upstream parser and AST.
# Serializer/visitor modules are not bundled. All evaluator/parser bodies are unmodified.
from .parser import FluentParser
from . import ast
