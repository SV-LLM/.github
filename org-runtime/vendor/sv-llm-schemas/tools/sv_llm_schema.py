"""SV-LLM native JSON Schema evaluator (standard library only).

The SV-LLM contracts are published as JSON Schema 2020-12 documents: that is
their interoperable format. This module is the authoritative evaluator for them
inside StegVerse; no third-party validator decides admission. It implements
exactly the keyword subset the SV-LLM contracts use and fails closed on any
other keyword (check_schema raises UnsupportedKeyword), so a schema can never
silently rely on behavior this evaluator does not have.

Semantics follow JSON Schema 2020-12 for the supported keywords:
  - JSON equality for const/enum/uniqueItems (booleans are not numbers,
    1 == 1.0, objects and arrays compare structurally);
  - "integer" admits a number with a zero fractional part (1.0); the canonical
    JSON parser, not the schema, is the lexical guard;
  - "pattern" is an unanchored regular-expression search;
  - "$ref" resolves against the enclosing resource's "$id" through a Registry
    of supplied documents; nothing is fetched.

API (the subset SV-LLM callers use):
  Registry(schemas)                       documents keyed by their "$id"
  Validator(schema, registry=None)        .iter_errors(instance) / .is_valid(instance)
  check_schema(schema)                    raises UnsupportedKeyword / SchemaError
Each error has .message, .absolute_path (list) and .schema_path (list).
"""
from __future__ import annotations

import re
from typing import Any, Iterator
from urllib.parse import unquote, urldefrag, urljoin

DIALECT = "https://json-schema.org/draft/2020-12/schema"

ANNOTATIONS = frozenset({"$schema", "$id", "$defs", "$comment", "title", "description", "default", "examples"})
APPLICATORS = frozenset({
    "type", "const", "enum", "required", "properties", "additionalProperties", "minProperties",
    "maxProperties", "items", "minItems", "maxItems", "uniqueItems", "contains", "minLength",
    "maxLength", "pattern", "minimum", "maximum", "allOf", "anyOf", "oneOf", "not", "if", "then",
    "else", "$ref",
})
SUPPORTED = ANNOTATIONS | APPLICATORS
TYPES = frozenset({"null", "boolean", "object", "array", "number", "string", "integer"})


class SchemaError(Exception):
    """The schema document itself is malformed."""


class UnsupportedKeyword(SchemaError):
    """The schema uses a keyword this evaluator does not implement (fail closed)."""


class ValidationError:
    __slots__ = ("message", "absolute_path", "schema_path")

    def __init__(self, message: str, absolute_path: list, schema_path: list):
        self.message, self.absolute_path, self.schema_path = message, absolute_path, schema_path

    def __repr__(self) -> str:
        return f"<ValidationError {self.message!r} at {self.absolute_path}>"


class Registry:
    """Schema documents addressable by their "$id"."""

    def __init__(self, schemas=()):
        self._docs: dict[str, Any] = {}
        for schema in schemas:
            self.add(schema)

    def add(self, schema: Any) -> "Registry":
        if not isinstance(schema, dict) or not isinstance(schema.get("$id"), str):
            raise SchemaError("a registered schema must be an object with a string $id")
        uri = urldefrag(schema["$id"])[0]
        if self._docs.get(uri, schema) is not schema and self._docs[uri] != schema:
            raise SchemaError(f"conflicting documents for $id {uri}")
        self._docs[uri] = schema
        return self

    def resolve(self, uri: str) -> Any:
        try:
            return self._docs[uri]
        except KeyError:
            raise SchemaError(f"unresolvable $ref target {uri!r}") from None


def _pointer(doc: Any, fragment: str) -> Any:
    if fragment in ("", "/"):
        return doc if fragment == "" else doc[""]
    if not fragment.startswith("/"):
        raise SchemaError(f"unsupported $ref fragment {fragment!r} (JSON Pointer only)")
    node = doc
    for raw in fragment[1:].split("/"):
        token = unquote(raw).replace("~1", "/").replace("~0", "~")
        if isinstance(node, list):
            node = node[int(token)]
        elif isinstance(node, dict) and token in node:
            node = node[token]
        else:
            raise SchemaError(f"$ref pointer {fragment!r} does not resolve")
    return node


def json_equal(a: Any, b: Any) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return a == b
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(json_equal(x, y) for x, y in zip(a, b))
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(json_equal(a[k], b[k]) for k in a)
    return type(a) is type(b) and a == b


def _is_type(value: Any, name: str) -> bool:
    if name == "null":
        return value is None
    if name == "boolean":
        return isinstance(value, bool)
    if name == "object":
        return isinstance(value, dict)
    if name == "array":
        return isinstance(value, list)
    if name == "string":
        return isinstance(value, str)
    if isinstance(value, bool):
        return False
    if name == "number":
        return isinstance(value, (int, float))
    if name == "integer":
        return isinstance(value, int) or (isinstance(value, float) and value.is_integer())
    raise SchemaError(f"unknown type {name!r}")


def check_schema(schema: Any, _path: tuple = ()) -> None:
    """Raise unless every (sub)schema uses only supported keywords with well-formed values."""
    if isinstance(schema, bool):
        return
    if not isinstance(schema, dict):
        raise SchemaError(f"schema at {list(_path)} is not an object or boolean")
    unknown = set(schema) - SUPPORTED
    if unknown:
        raise UnsupportedKeyword(f"unsupported keyword(s) {sorted(unknown)} at {list(_path)}")
    if "$schema" in schema and schema["$schema"] != DIALECT:
        raise SchemaError(f"unsupported dialect {schema['$schema']!r}")
    if "type" in schema:
        names = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not names or any(n not in TYPES for n in names):
            raise SchemaError(f"bad type at {list(_path)}")
    for key in ("required",):
        if key in schema and not (isinstance(schema[key], list) and all(isinstance(x, str) for x in schema[key])):
            raise SchemaError(f"bad {key} at {list(_path)}")
    if "enum" in schema and not isinstance(schema["enum"], list):
        raise SchemaError(f"bad enum at {list(_path)}")
    for key in ("minProperties", "maxProperties", "minItems", "maxItems", "minLength", "maxLength"):
        if key in schema and not (isinstance(schema[key], int) and not isinstance(schema[key], bool) and schema[key] >= 0):
            raise SchemaError(f"bad {key} at {list(_path)}")
    for key in ("minimum", "maximum"):
        if key in schema and (isinstance(schema[key], bool) or not isinstance(schema[key], (int, float))):
            raise SchemaError(f"bad {key} at {list(_path)}")
    if "uniqueItems" in schema and not isinstance(schema["uniqueItems"], bool):
        raise SchemaError(f"bad uniqueItems at {list(_path)}")
    if "pattern" in schema:
        try:
            re.compile(schema["pattern"])
        except (re.error, TypeError) as exc:
            raise SchemaError(f"bad pattern at {list(_path)}: {exc}") from None
    if "$ref" in schema and not isinstance(schema["$ref"], str):
        raise SchemaError(f"bad $ref at {list(_path)}")
    for key in ("properties", "$defs"):
        if key in schema:
            if not isinstance(schema[key], dict):
                raise SchemaError(f"bad {key} at {list(_path)}")
            for name, sub in schema[key].items():
                check_schema(sub, _path + (key, name))
    for key in ("additionalProperties", "items", "contains", "not", "if", "then", "else"):
        if key in schema:
            check_schema(schema[key], _path + (key,))
    for key in ("allOf", "anyOf", "oneOf"):
        if key in schema:
            if not (isinstance(schema[key], list) and schema[key]):
                raise SchemaError(f"bad {key} at {list(_path)}")
            for i, sub in enumerate(schema[key]):
                check_schema(sub, _path + (key, i))


class Validator:
    def __init__(self, schema: Any, registry: Registry | None = None):
        self.schema = schema
        self.registry = registry or Registry()
        self._base = urldefrag(schema["$id"])[0] if isinstance(schema, dict) and isinstance(schema.get("$id"), str) else ""
        if self._base:
            self.registry = Registry(list(self.registry._docs.values()))
            self.registry._docs.setdefault(self._base, schema)

    def is_valid(self, instance: Any) -> bool:
        return next(self.iter_errors(instance), None) is None

    def iter_errors(self, instance: Any) -> Iterator[ValidationError]:
        root = self.schema if not self._base else self.registry.resolve(self._base)
        yield from self._eval(self.schema, instance, self._base, root, [], [])

    # -- evaluation ---------------------------------------------------------------
    def _ref(self, ref: str, base: str, root: Any):
        uri, fragment = urldefrag(urljoin(base, ref) if base else ref)
        if uri:
            doc = self.registry.resolve(uri)
            return _pointer(doc, fragment), uri, doc
        return _pointer(root, fragment), base, root

    def _eval(self, schema, inst, base, root, path, spath) -> Iterator[ValidationError]:
        if schema is True:
            return
        if schema is False:
            yield ValidationError("False schema does not allow %r" % (inst,), list(path), list(spath))
            return
        if isinstance(schema.get("$id"), str):
            base = urljoin(base, schema["$id"]) if base else urldefrag(schema["$id"])[0]
            root = schema
        err = lambda msg, key: ValidationError(msg, list(path), list(spath) + [key])  # noqa: E731

        if "$ref" in schema:
            target, tbase, troot = self._ref(schema["$ref"], base, root)
            yield from self._eval(target, inst, tbase, troot, path, spath + ["$ref"])
        if "type" in schema:
            names = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
            if not any(_is_type(inst, n) for n in names):
                yield err(f"{inst!r} is not of type {', '.join(map(repr, names))}", "type")
        if "const" in schema and not json_equal(inst, schema["const"]):
            yield err(f"{schema['const']!r} was expected", "const")
        if "enum" in schema and not any(json_equal(inst, v) for v in schema["enum"]):
            yield err(f"{inst!r} is not one of {schema['enum']!r}", "enum")

        if isinstance(inst, dict):
            for name in schema.get("required", ()):
                if name not in inst:
                    yield err(f"{name!r} is a required property", "required")
            if "minProperties" in schema and len(inst) < schema["minProperties"]:
                yield err(f"{inst!r} does not have enough properties", "minProperties")
            if "maxProperties" in schema and len(inst) > schema["maxProperties"]:
                yield err(f"{inst!r} has too many properties", "maxProperties")
            props = schema.get("properties", {})
            for name, sub in props.items():
                if name in inst:
                    yield from self._eval(sub, inst[name], base, root, path + [name], spath + ["properties", name])
            if "additionalProperties" in schema:
                extra = [k for k in inst if k not in props]
                ap = schema["additionalProperties"]
                if ap is False and extra:
                    yield err(f"Additional properties are not allowed ({', '.join(map(repr, extra))} unexpected)",
                              "additionalProperties")
                elif ap is not True and ap is not False:
                    for k in extra:
                        yield from self._eval(ap, inst[k], base, root, path + [k], spath + ["additionalProperties"])

        if isinstance(inst, list):
            if "minItems" in schema and len(inst) < schema["minItems"]:
                yield err(f"{inst!r} should be non-empty" if schema["minItems"] == 1 else f"{inst!r} is too short",
                          "minItems")
            if "maxItems" in schema and len(inst) > schema["maxItems"]:
                yield err(f"{inst!r} is too long", "maxItems")
            if schema.get("uniqueItems"):
                for i in range(len(inst)):
                    if any(json_equal(inst[i], inst[j]) for j in range(i)):
                        yield err(f"{inst!r} has non-unique elements", "uniqueItems")
                        break
            if "items" in schema:
                for i, item in enumerate(inst):
                    yield from self._eval(schema["items"], item, base, root, path + [i], spath + ["items"])
            if "contains" in schema and not any(
                    self._ok(schema["contains"], item, base, root) for item in inst):
                yield err(f"{inst!r} does not contain items matching the given schema", "contains")

        if isinstance(inst, str):
            if "minLength" in schema and len(inst) < schema["minLength"]:
                yield err(f"{inst!r} is too short", "minLength")
            if "maxLength" in schema and len(inst) > schema["maxLength"]:
                yield err(f"{inst!r} is too long", "maxLength")
            if "pattern" in schema and re.search(schema["pattern"], inst) is None:
                yield err(f"{inst!r} does not match {schema['pattern']!r}", "pattern")

        if _is_type(inst, "number"):
            if "minimum" in schema and inst < schema["minimum"]:
                yield err(f"{inst!r} is less than the minimum of {schema['minimum']!r}", "minimum")
            if "maximum" in schema and inst > schema["maximum"]:
                yield err(f"{inst!r} is greater than the maximum of {schema['maximum']!r}", "maximum")

        for i, sub in enumerate(schema.get("allOf", ())):
            yield from self._eval(sub, inst, base, root, path, spath + ["allOf", i])
        if "anyOf" in schema and not any(self._ok(sub, inst, base, root) for sub in schema["anyOf"]):
            yield err(f"{inst!r} is not valid under any of the given schemas", "anyOf")
        if "oneOf" in schema:
            matched = sum(1 for sub in schema["oneOf"] if self._ok(sub, inst, base, root))
            if matched == 0:
                yield err(f"{inst!r} is not valid under any of the given schemas", "oneOf")
            elif matched > 1:
                yield err(f"{inst!r} is valid under each of more than one of the given schemas", "oneOf")
        if "not" in schema and self._ok(schema["not"], inst, base, root):
            yield err(f"{inst!r} should not be valid under {schema['not']!r}", "not")
        if "if" in schema:
            if self._ok(schema["if"], inst, base, root):
                if "then" in schema:
                    yield from self._eval(schema["then"], inst, base, root, path, spath + ["then"])
            elif "else" in schema:
                yield from self._eval(schema["else"], inst, base, root, path, spath + ["else"])

    def _ok(self, schema, inst, base, root) -> bool:
        return next(self._eval(schema, inst, base, root, [], []), None) is None
