"""Static check: every call to a scripts/ function imported from another scripts/
module must match that function's signature.

Why: many call sites sit inside `try: ... except Exception: pass`, so a wrong
call (e.g. calculate_net_worth(profile) when it takes no arguments) fails
silently forever instead of raising in a test.
"""
import ast
import pathlib

SCRIPTS = pathlib.Path(__file__).resolve().parent.parent / "scripts"


def _signatures():
    sigs = {}
    for path in SCRIPTS.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, ast.FunctionDef):
                a = node.args
                pos = [x.arg for x in a.posonlyargs + a.args]
                required = len(pos) - len(a.defaults)
                sigs[(path.stem, node.name)] = {
                    "pos": pos,
                    "required": required,
                    "kwonly": [x.arg for x in a.kwonlyargs],
                    "kwonly_required": [x.arg for x, d in zip(a.kwonlyargs, a.kw_defaults) if d is None],
                    "varargs": a.vararg is not None,
                    "varkw": a.kwarg is not None,
                }
    return sigs


def _problem(call, sig):
    n_pos = len(call.args)
    if any(isinstance(x, ast.Starred) for x in call.args) or any(k.arg is None for k in call.keywords):
        return None  # *args/**kwargs at the call site: can't judge statically
    kw = [k.arg for k in call.keywords]
    if n_pos > len(sig["pos"]) and not sig["varargs"]:
        return f"{n_pos} positional args, accepts {len(sig['pos'])}"
    for k in kw:
        if k not in sig["pos"] and k not in sig["kwonly"] and not sig["varkw"]:
            return f"unknown keyword {k!r}"
    supplied = set(sig["pos"][:n_pos]) | set(kw)
    missing = [p for p in sig["pos"][: sig["required"]] if p not in supplied]
    missing += [p for p in sig["kwonly_required"] if p not in supplied]
    if missing:
        return f"missing required {missing}"
    return None


def _aliases(nodes, sigs):
    out = {}
    for node in nodes:
        if isinstance(node, ast.ImportFrom) and node.module:
            mod = node.module.split(".")[-1]
            for n in node.names:
                if (mod, n.name) in sigs:
                    out[n.asname or n.name] = (mod, n.name)
    return out


def test_cross_module_calls_match_signatures():
    sigs = _signatures()
    problems = []
    for path in sorted(SCRIPTS.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        local_defs = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
        module_alias = _aliases(tree.body, sigs)
        mod_alias = {(n.asname or n.name): n.name for node in ast.walk(tree)
                     if isinstance(node, ast.Import) for n in node.names
                     if (SCRIPTS / f"{n.name}.py").exists()}
        scopes = [(tree, module_alias)]
        for fn in (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)):
            scopes.append((fn, {**module_alias, **_aliases(ast.walk(fn), sigs)}))
        seen = set()
        for scope, alias in scopes:
            for node in ast.walk(scope):
                if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                        and isinstance(node.func.value, ast.Name)):
                    mod = mod_alias.get(node.func.value.id)
                    if mod and (mod, node.func.attr) in sigs and (node.lineno, node.func.attr) not in seen:
                        msg = _problem(node, sigs[(mod, node.func.attr)])
                        if msg:
                            seen.add((node.lineno, node.func.attr))
                            problems.append(f"{path.name}:{node.lineno} {mod}.{node.func.attr}(): {msg}")
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                    name = node.func.id
                    if name in alias and name not in local_defs and (node.lineno, name) not in seen:
                        msg = _problem(node, sigs[alias[name]])
                        if msg:
                            seen.add((node.lineno, name))
                            problems.append(f"{path.name}:{node.lineno} {alias[name][0]}.{alias[name][1]}(): {msg}")
    assert not problems, "\n" + "\n".join(problems)
