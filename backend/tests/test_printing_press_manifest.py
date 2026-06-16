"""Unit tests for manifest → tool-def/executor translation (pure, hermetic)."""

from integrations.printing_press import manifest as pp


_MANIFEST = {
    "api_name": "Demo",
    "base_url": "https://api.demo.test",
    "auth": {"type": "api_key", "env_vars": ["DEMO_API_KEY"]},
    "tools": [
        {
            "name": "authors_list",
            "description": "List authors.",
            "method": "GET",
            "params": [
                {"name": "search", "type": "string", "location": "query",
                 "description": "Full-text search"},
                {"name": "per_page", "type": "integer", "location": "query"},
            ],
        },
        {
            "name": "authors_create",
            "description": "Create an author.",
            "method": "POST",
            "params": [
                {"name": "name", "type": "string", "location": "body", "required": True},
            ],
        },
        {
            "name": "authors_get",
            "description": "Get one author.",
            "method": "GET",
            "params": [
                {"name": "id", "type": "string", "location": "path", "required": True},
            ],
        },
    ],
}


def test_build_produces_def_and_executor_per_tool():
    defs, execs = pp.build("openalex", _MANIFEST)
    assert len(defs) == 3 and len(execs) == 3
    names = {d["name"] for d in defs}
    assert names == {"openalex__authors_list", "openalex__authors_create", "openalex__authors_get"}
    assert set(execs) == names


def test_def_shape_and_kind_integration():
    defs, _ = pp.build("openalex", _MANIFEST)
    d = next(d for d in defs if d["name"] == "openalex__authors_list")
    assert d["kind"] == "printed_cli"
    assert d["integration"] == "pp:openalex"
    assert d["description"].startswith("[Demo]")
    assert d["input_schema"]["type"] == "object"
    assert d["input_schema"]["properties"]["search"]["type"] == "string"
    assert d["input_schema"]["properties"]["per_page"]["type"] == "integer"


def test_writes_derived_from_http_method():
    defs, _ = pp.build("openalex", _MANIFEST)
    by_name = {d["name"]: d for d in defs}
    assert by_name["openalex__authors_list"]["writes"] is False   # GET
    assert by_name["openalex__authors_get"]["writes"] is False    # GET
    assert by_name["openalex__authors_create"]["writes"] is True  # POST


def test_required_params_in_schema():
    defs, _ = pp.build("openalex", _MANIFEST)
    create = next(d for d in defs if d["name"] == "openalex__authors_create")
    assert create["input_schema"]["required"] == ["name"]
    get = next(d for d in defs if d["name"] == "openalex__authors_get")
    assert get["input_schema"]["required"] == ["id"]


def test_command_path_split():
    assert pp.command_path("authors_list") == ["authors", "list"]
    assert pp.command_path("institution-types_list") == ["institution-types", "list"]


def test_tool_name_caps_at_64_and_stays_unique():
    long_cmd = "a_very_" + "x" * 80
    n1 = pp.tool_name("someslug", long_cmd)
    n2 = pp.tool_name("someslug", long_cmd + "_more")
    assert len(n1) <= 64 and len(n2) <= 64
    assert n1 != n2  # digest suffix preserves uniqueness


def test_executor_invokes_runner(monkeypatch):
    captured = {}

    def fake_run_cli(slug, command, args, *, param_specs=None, **kw):
        captured.update(slug=slug, command=command, args=args, param_specs=param_specs)
        return {"meta": {}, "results": []}

    monkeypatch.setattr(pp.runner, "run_cli", fake_run_cli)
    _, execs = pp.build("openalex", _MANIFEST)
    out = execs["openalex__authors_list"](search="ml", per_page=2)
    assert out == {"meta": {}, "results": []}
    assert captured["slug"] == "openalex"
    assert captured["command"] == ["authors", "list"]
    assert captured["args"] == {"search": "ml", "per_page": 2}
    # param specs are threaded so the runner can serialize path vs query correctly
    assert any(p["name"] == "per_page" for p in captured["param_specs"])
