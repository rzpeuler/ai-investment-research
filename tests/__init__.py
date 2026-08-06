"""Repository-local test package.

Being an explicit package prevents an unrelated site-packages ``tests`` package
from shadowing ``tests.fixtures`` and ``tests.golden`` during pytest collection.
"""
