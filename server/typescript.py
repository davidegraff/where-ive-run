"""Write web/api-types.ts from the models in models.py, so the page is type-checked against the API.

    uv run python -m server.typescript           # regenerate web/api-types.ts
    uv run python -m server.typescript --check   # fail if it's out of date (npm run typecheck runs this)

Pydantic describes each model as JSON Schema; this turns those schemas into TypeScript. It handles the
parts of JSON Schema the models use (objects, strings, numbers, literals, unions, lists, tuples) and
fails loudly on anything else, rather than guessing.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter

from server.models import TYPESCRIPT_EXPORTS

OUT = Path(__file__).resolve().parent.parent / "web" / "api-types.ts"
HEADER = """\
// Generated from server/models.py by `npm run gen:api` (python -m server.typescript). Don't edit by hand.
"""

Schema = dict[str, Any]


def generate() -> str:
    named: dict[str, Schema] = {}  # every type that gets its own declaration, in output order
    for name, obj in TYPESCRIPT_EXPORTS.items():
        schema = TypeAdapter(obj).json_schema(mode="serialization", ref_template="{model}")
        for def_name, def_schema in schema.pop("$defs", {}).items():
            named.setdefault(def_name, def_schema)
        named[name] = schema

    # Exports first, in the order models.py lists them; then the models they refer to.
    order = list(TYPESCRIPT_EXPORTS) + [n for n in named if n not in TYPESCRIPT_EXPORTS]
    return HEADER + "".join("\n" + declaration(n, named[n]) for n in order)


def declaration(name: str, schema: Schema) -> str:
    doc = comment(schema.get("description"), "")
    if schema.get("type") == "object" and "properties" in schema:
        required = set(schema.get("required", []))
        lines = [f"{doc}export interface {name} {{"]
        for prop, prop_schema in schema["properties"].items():
            optional = "" if prop in required else "?"
            lines.append(f"{comment(prop_schema.get('description'), '  ')}  {prop}{optional}: {ts_type(prop_schema)};")
        return "\n".join(lines) + "\n}\n"
    return f"{doc}export type {name} = {ts_type(schema)};\n"


def ts_type(s: Schema) -> str:
    if "$ref" in s:
        return str(s["$ref"])
    if "const" in s:
        return json.dumps(s["const"])
    if "enum" in s:
        return " | ".join(json.dumps(v) for v in s["enum"])
    for key in ("anyOf", "oneOf"):
        if key in s:
            return " | ".join(ts_type(option) for option in s[key])
    t = s.get("type")
    if t == "string":
        return "string"
    if t in ("number", "integer"):
        return "number"
    if t == "boolean":
        return "boolean"
    if t == "null":
        return "null"
    if t == "array" and "prefixItems" in s:
        return "[" + ", ".join(ts_type(item) for item in s["prefixItems"]) + "]"
    if t == "array":
        item = ts_type(s["items"])
        return f"({item})[]" if "|" in item else f"{item}[]"
    raise ValueError(f"Don't know how to write this schema as TypeScript: {s}")


def comment(text: str | None, indent: str) -> str:
    if not text:
        return ""
    lines = text.strip().splitlines()
    if len(lines) == 1:
        return f"{indent}/** {lines[0]} */\n"
    return f"{indent}/**\n" + "".join(f"{indent} * {line}\n" for line in lines) + f"{indent} */\n"


def main() -> None:
    code = generate()
    if "--check" in sys.argv[1:]:
        if not OUT.exists() or OUT.read_text() != code:
            sys.exit(f"{OUT.name} is out of date with server/models.py: run `npm run gen:api`.")
        return
    OUT.write_text(code)
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
