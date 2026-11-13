import ast,hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]


def canonical_ast(node):
    if isinstance(node, ast.AST):
        return {'node':type(node).__name__, 'fields':{name:canonical_ast(value) for name,value in ast.iter_fields(node) if value is not None}}
    if isinstance(node,list):return [canonical_ast(value) for value in node]
    return node


def ast_hash(node):
    return hashlib.sha256(json.dumps(canonical_ast(node),sort_keys=True).encode()).hexdigest()



def test_only_approved_v943_baseline_files_changed():
    baseline=json.loads((ROOT/'reports/v943_packaging_freeze_manifest.json').read_text())['source_sha256']
    changed={n for n,h in baseline.items() if hashlib.sha256((ROOT/n).read_bytes()).hexdigest()!=h}
    assert changed=={'src/live_runner.py','configs/v9-canonical-production.json','pyproject.toml','tests/test_v92_upgrades.py','tests/test_v9_greenfield_suite.py'}


def test_only_reporting_and_run_status_methods_changed():
    old=json.loads((ROOT/'reports/v944/v943_runner_method_ast_hashes.json').read_text())
    cls=next(x for x in ast.parse((ROOT/'src/live_runner.py').read_text()).body if isinstance(x,ast.ClassDef) and x.name=='DualVenueLiveRunner')
    new={n.name:ast_hash(n) for n in cls.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))}
    assert set(old)==set(new)
    assert {n for n,h in old.items() if new[n]!=h}=={'run','build_state_payload'}
