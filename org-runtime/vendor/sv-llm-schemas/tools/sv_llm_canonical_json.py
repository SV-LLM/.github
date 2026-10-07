"""Reference implementation of SV_LLM_CANONICAL_JSON_V1 and the Step-1 runtime invariants.

Not normative: docs/SV_LLM_CANONICAL_JSON_V1.md is. This module exists so the
schemas can be tested mechanically and so implementers have a known-good
comparison. It never makes a governance disposition; a failed check raises
CanonicalError naming the failed predicate.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from typing import Any

MAX_SAFE = 9007199254740991
_INT = re.compile(r"-?(0|[1-9][0-9]*)\Z")
_JSON_MEDIA = re.compile(r"application/(?:[a-z0-9!#$&^_.+-]+\+)?json\Z")
_BASE64 = re.compile(r"(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?\Z")
_SHORT = {'"': '\\"', "\\": "\\\\", "\b": "\\b", "\f": "\\f", "\n": "\\n", "\r": "\\r", "\t": "\\t"}
NON_SUCCESS = ("REFUSED", "UNAVAILABLE", "FAILED")


class CanonicalError(ValueError):
    def __init__(self, failed_predicate: str, detail: str = ""):
        super().__init__(failed_predicate + (": " + detail if detail else ""))
        self.failed_predicate = failed_predicate


# --- E1 / E2: parser input -------------------------------------------------

def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise CanonicalError("DUPLICATE_MEMBER_NAME", repr(key))
        out[key] = value
    return out


def _int(literal: str) -> int:
    if not _INT.match(literal) or literal == "-0":
        raise CanonicalError("NON_CANONICAL_INTEGER_LITERAL", literal)
    value = int(literal)
    if not -MAX_SAFE <= value <= MAX_SAFE:
        raise CanonicalError("INTEGER_OUT_OF_RANGE", literal)
    return value


def _float(literal: str) -> Any:
    raise CanonicalError("NON_INTEGER_NUMBER", literal)


def _constant(literal: str) -> Any:
    raise CanonicalError("NON_FINITE_NUMBER", literal)


def _check_string(s: str) -> None:
    for ch in s:
        if 0xD800 <= ord(ch) <= 0xDFFF:
            raise CanonicalError("LONE_SURROGATE", "U+%04X" % ord(ch))


def check_value(value: Any) -> None:
    """Value-domain check for an already-constructed value (C2, E1 surrogates)."""
    if value is None or isinstance(value, bool):
        return
    if isinstance(value, int):
        if not -MAX_SAFE <= value <= MAX_SAFE:
            raise CanonicalError("INTEGER_OUT_OF_RANGE", str(value))
    elif isinstance(value, float):
        raise CanonicalError("NON_INTEGER_NUMBER", repr(value))
    elif isinstance(value, str):
        _check_string(value)
    elif isinstance(value, list):
        for item in value:
            check_value(item)
    elif isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise CanonicalError("NON_STRING_MEMBER_NAME", repr(key))
            _check_string(key)
            check_value(item)
    else:
        raise CanonicalError("NOT_A_JSON_VALUE", type(value).__name__)


def parse(text: str | bytes) -> Any:
    """Parse JSON text under E1 and E2. Bytes must be UTF-8 without a BOM."""
    if isinstance(text, bytes):
        if text.startswith(b"\xef\xbb\xbf"):
            raise CanonicalError("BYTE_ORDER_MARK")
        try:
            text = text.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise CanonicalError("INVALID_UTF8", str(exc)) from None
    try:
        value = json.loads(text, object_pairs_hook=_pairs, parse_int=_int,
                           parse_float=_float, parse_constant=_constant)
    except json.JSONDecodeError as exc:
        raise CanonicalError("INVALID_JSON", str(exc)) from None
    check_value(value)
    return value


# --- C1 / C2: serialization ------------------------------------------------

def _string(s: str) -> str:
    out = ['"']
    for ch in s:
        if ch in _SHORT:
            out.append(_SHORT[ch])
        elif ord(ch) < 0x20:
            out.append("\\u%04x" % ord(ch))
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def _serialize(value: Any) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return _string(value)
    if isinstance(value, list):
        return "[" + ",".join(_serialize(v) for v in value) + "]"
    # Python str ordering is Unicode code point sequence order.
    return "{" + ",".join(_string(k) + ":" + _serialize(value[k]) for k in sorted(value)) + "}"


def canonical(value: Any) -> bytes:
    check_value(value)
    return _serialize(value).encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def digest(value: Any) -> str:
    return sha256_bytes(canonical(value))


# --- E5 / F3 / F5: content --------------------------------------------------

def is_json_media_type(media_type: str) -> bool:
    branch_key = media_type.split(";", 1)[0].strip(" \t").lower()
    return bool(_JSON_MEDIA.match(branch_key))


def decode_base64(text: str) -> bytes:
    if not isinstance(text, str) or not _BASE64.match(text):
        raise CanonicalError("NON_CANONICAL_BASE64", "alphabet, padding or whitespace")
    try:
        data = base64.b64decode(text, validate=True)
    except binascii.Error as exc:
        raise CanonicalError("NON_CANONICAL_BASE64", str(exc)) from None
    if base64.b64encode(data).decode("ascii") != text:
        raise CanonicalError("NON_CANONICAL_BASE64", "non-zero padding bits")
    return data


def content_digest(media_type: str, content: Any) -> str:
    """Digest of inline contributed content (E3)."""
    if is_json_media_type(media_type):
        return digest(content)
    return sha256_bytes(decode_base64(content))


def retained_content_digest(media_type: str, retained: bytes) -> str:
    """Digest of content recovered through artifact_refs (F5)."""
    if is_json_media_type(media_type):
        return digest(parse(retained))
    return sha256_bytes(retained)


# --- Runtime invariants ------------------------------------------------------

def verify_contribution(contribution: dict[str, Any], *, work: dict[str, Any] | None = None,
                        declaration: dict[str, Any] | None = None,
                        retained: bytes | None = None) -> None:
    """Invariants JSON Schema cannot prove. Call after schema validation."""
    check_value(contribution)
    status = contribution["status"]
    if status in NON_SUCCESS:
        record = contribution["non_success_status_record"]
        for field in ("status", "evidence_refs", "provenance", "uncertainty"):
            if record[field] != contribution[field]:
                raise CanonicalError("STATUS_RECORD_FIELD_MISMATCH", field)
        expected = digest(record)
    elif "content" in contribution:
        expected = content_digest(contribution["content_media_type"], contribution["content"])
    elif retained is not None:
        expected = retained_content_digest(contribution["content_media_type"], retained)
    else:
        expected = None  # artifact_refs not resolved by the caller; digest not checked here
    if expected is not None and expected != contribution["content_digest"]:
        raise CanonicalError("CONTENT_DIGEST_MISMATCH", expected)
    capability = contribution["capability"]
    if work is not None:
        if contribution["work_id"] != work["work_id"]:
            raise CanonicalError("WORK_ID_MISMATCH")
        if capability not in work["permitted_capabilities"]:
            raise CanonicalError("CAPABILITY_NOT_PERMITTED_BY_WORK", capability)
    if declaration is not None:
        if contribution["entity"] != declaration["entity"]:
            raise CanonicalError("ENTITY_MISMATCH")
        if capability not in declaration["capabilities"]:
            raise CanonicalError("CAPABILITY_NOT_DECLARED_BY_ENTITY", capability)


def verify_capability_assignment(evidence: dict[str, Any]) -> None:
    """CAPABILITY_ASSIGNMENT evidence invariants (C4, F6)."""
    declaration = evidence["declaration"]
    ref = evidence["capability_declaration_ref"]
    if digest(declaration) != ref["declaration_sha256"]:
        raise CanonicalError("DECLARATION_DIGEST_MISMATCH")
    if ref["repository"] != declaration["repository"]:
        raise CanonicalError("DECLARATION_REPOSITORY_MISMATCH")
    if evidence["capability"] not in declaration["capabilities"]:
        raise CanonicalError("CAPABILITY_NOT_DECLARED_BY_ENTITY", evidence["capability"])
