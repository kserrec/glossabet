"""Names for the JSON value space every persisted Glossabet document lives in.

Persisted documents stay ordinary dictionaries, lists, and JSON primitives;
these aliases only let a signature say "a JSON value" precisely instead of
``object`` or an unparameterized ``dict``. A document read from disk is still
``object`` until it has been validated and narrowed.
"""

from __future__ import annotations

from typing import TypeAlias

JSONScalar: TypeAlias = "str | int | float | bool | None"
JSONValue: TypeAlias = "JSONScalar | list[JSONValue] | dict[str, JSONValue]"
JSONArray: TypeAlias = "list[JSONValue]"
JSONObject: TypeAlias = "dict[str, JSONValue]"
