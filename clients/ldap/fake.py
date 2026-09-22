"""In-process directory used to exercise the LDAP plan.

Not a server and not evidence that OpenLDAP accepted a connection.
ACL matches infra/ldap/slapd/acl.conf: the aggregator cannot write, and the
provisioner can write only under ou=People and ou=Groups. A bind that already
succeeded is stored on that connection only. Setting pwdAccountLockedTime does
not clear another connection's bind. The next bind on a locked entry fails.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

try:
    from .client import (
        ADMIN_DN,
        AGGREGATOR_DN,
        BASE_DN,
        GROUPS_DN,
        LOCK_TIME,
        PEOPLE_DN,
        PROVISIONER_DN,
    )
except ImportError:
    from client import (
        ADMIN_DN,
        AGGREGATOR_DN,
        BASE_DN,
        GROUPS_DN,
        LOCK_TIME,
        PEOPLE_DN,
        PROVISIONER_DN,
    )

_SEED_PATH = Path(__file__).resolve().parents[2] / "infra" / "ldap" / "seed.ldif"
_DN_ATTRS = frozenset({"member", "uniquemember", "memberof", "manager", "owner"})
_OPERATIONAL = frozenset(
    {
        "memberof",
        "pwdaccountlockedtime",
        "pwdchangedtime",
        "pwdfailuretime",
        "pwdgraceusetime",
        "pwdhistory",
        "pwdpolicysubentry",
        "pwdreset",
    }
)
_REFINT_ATTRS = ("member", "uniqueMember", "manager", "owner")

Attributes = dict[str, list[str]]
Directory = dict[str, Attributes]


class BindError(Exception):
    """A simple bind was rejected. reason is locked or invalidCredentials."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class LdapError(Exception):
    """A directory operation failed. code is a short LDAP result name."""

    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        super().__init__(f"{code}: {detail}")


def norm_dn(dn: str) -> str:
    parts: list[str] = []
    for rdn in dn.split(","):
        rdn = rdn.strip()
        if rdn == "":
            continue
        attr, sep, value = rdn.partition("=")
        if sep != "=" or attr.strip() == "":
            raise ValueError(f"invalid dn {dn}")
        parts.append(f"{attr.strip().casefold()}={value.strip().casefold()}")
    if not parts:
        raise ValueError("invalid dn")
    return ",".join(parts)


def parent_dn(dn: str) -> str:
    parts = [part.strip() for part in dn.split(",") if part.strip()]
    if len(parts) <= 1:
        return ""
    return ",".join(parts[1:])


def under(dn: str, base: str) -> bool:
    left = norm_dn(dn)
    right = norm_dn(base)
    return left == right or left.endswith("," + right)


def _rdns(dn: str) -> list[str]:
    return [part.strip() for part in dn.split(",") if part.strip()]


def _find_key(attrs: Attributes, name: str) -> str | None:
    folded = name.casefold()
    for key in attrs:
        if key.casefold() == folded:
            return key
    return None


def _values(attrs: Attributes, name: str) -> list[str]:
    key = _find_key(attrs, name)
    if key is None:
        return []
    return attrs[key]


def _equal_value(attr: str, stored: str, wanted: str) -> bool:
    if attr.casefold() == "userpassword":
        return stored == wanted
    if attr.casefold() in _DN_ATTRS:
        try:
            return norm_dn(stored) == norm_dn(wanted)
        except ValueError:
            return False
    return stored.casefold() == wanted.casefold()


def _with_new_suffix(dn: str, old: str, new: str) -> str | None:
    dn_rdns = _rdns(dn)
    old_rdns = _rdns(old)
    count = len(old_rdns)
    if len(dn_rdns) < count:
        return None
    suffix = ",".join(dn_rdns[-count:])
    if norm_dn(suffix) != norm_dn(old):
        return None
    prefix = dn_rdns[:-count]
    return ",".join(prefix + _rdns(new))


def parse_ldif(text: str) -> list[tuple[str, Attributes]]:
    logical: list[str] = []
    current = ""
    started = False
    for raw in text.splitlines():
        if started and (raw.startswith(" ") or raw.startswith("\t")):
            current += raw[1:]
            continue
        if started:
            logical.append(current)
        current = raw
        started = True
    if started:
        logical.append(current)

    entries: list[tuple[str, Attributes]] = []
    dn: str | None = None
    attrs: Attributes = {}

    def finish() -> None:
        nonlocal dn, attrs
        if dn is not None:
            entries.append((dn, attrs))
        dn = None
        attrs = {}

    for line in logical:
        if line == "":
            finish()
            continue
        if line.startswith("#"):
            continue
        if line.lower().startswith("version:"):
            continue
        name, sep, rest = line.partition(":")
        if sep != ":":
            raise ValueError("invalid LDIF line")
        if rest.startswith(":"):
            raise ValueError("base64 LDIF values are not used")
        value = rest[1:] if rest.startswith(" ") else rest
        if name.lower() == "dn":
            if dn is not None:
                finish()
            dn = value.strip()
            attrs = {}
            continue
        if dn is None:
            raise ValueError("LDIF attribute before dn")
        attrs.setdefault(name, []).append(value)
    finish()
    return entries


def load_directory(path: Path | None = None) -> Directory:
    """Load the suffix and infra/ldap/seed.ldif. Each call returns a new dict."""
    seed = path if path is not None else _SEED_PATH
    directory: Directory = {
        BASE_DN: {
            "objectClass": ["top", "dcObject", "organization"],
            "dc": ["iam"],
            "o": ["IAM Playground"],
        }
    }
    for dn, attrs in parse_ldif(seed.read_text(encoding="utf-8")):
        directory[dn] = {name: list(values) for name, values in attrs.items()}
    _recompute_memberof(directory)
    return directory


def _recompute_memberof(directory: Directory) -> None:
    groups_for: dict[str, list[str]] = {}
    for dn, attrs in directory.items():
        for member in _values(attrs, "member"):
            try:
                groups_for.setdefault(norm_dn(member), []).append(dn)
            except ValueError:
                continue
    for dn, attrs in directory.items():
        groups = groups_for.get(norm_dn(dn))
        if groups:
            attrs["memberOf"] = list(groups)
        else:
            attrs.pop("memberOf", None)


def _map_dn(value: str, mapping: dict[str, str]) -> str:
    try:
        return mapping.get(norm_dn(value), value)
    except ValueError:
        return value


def _rewrite_dn_values(directory: Directory, moves: list[tuple[str, str]]) -> None:
    mapping = {norm_dn(old): new for old, new in moves}
    refint = {name.casefold() for name in _REFINT_ATTRS}
    for attrs in directory.values():
        for name in list(attrs):
            if name.casefold() not in refint:
                continue
            attrs[name] = [_map_dn(value, mapping) for value in attrs[name]]


def _remove_dn_refs(directory: Directory, dn: str) -> None:
    target = norm_dn(dn)
    refint = {name.casefold() for name in _REFINT_ATTRS}
    for attrs in directory.values():
        for name in list(attrs):
            if name.casefold() not in refint:
                continue
            kept: list[str] = []
            for value in attrs[name]:
                try:
                    if norm_dn(value) == target:
                        continue
                except ValueError:
                    pass
                kept.append(value)
            if kept:
                attrs[name] = kept
            else:
                del attrs[name]


def _parse_filter(text: str) -> tuple[Any, ...]:
    text = text.strip()
    if len(text) < 2 or text[0] != "(" or text[-1] != ")":
        raise ValueError("filter must be parenthesized")
    return _parse_filter_body(text[1:-1].strip())


def _parse_filter_body(body: str) -> tuple[Any, ...]:
    if body[:1] in {"&", "|", "!"}:
        kind = {"&": "and", "|": "or", "!": "not"}[body[0]]
        rest = body[1:].strip()
        parts: list[tuple[Any, ...]] = []
        while rest:
            if not rest.startswith("("):
                raise ValueError("invalid filter")
            depth = 0
            end: int | None = None
            for index, char in enumerate(rest):
                if char == "(":
                    depth += 1
                elif char == ")":
                    depth -= 1
                    if depth == 0:
                        end = index
                        break
            if end is None:
                raise ValueError("unbalanced filter")
            parts.append(_parse_filter(rest[: end + 1]))
            rest = rest[end + 1 :].strip()
        if kind == "not":
            if len(parts) != 1:
                raise ValueError("not filter takes one item")
            return ("not", parts[0])
        if not parts:
            raise ValueError("empty boolean filter")
        return (kind, parts)
    attr, sep, value = body.partition("=")
    if sep != "=" or attr.strip() == "":
        raise ValueError("invalid filter")
    if value == "*":
        return ("present", attr.strip())
    return ("eq", attr.strip(), value)


def _matches(attrs: Attributes, parsed: tuple[Any, ...]) -> bool:
    kind = parsed[0]
    if kind == "and":
        return all(_matches(attrs, item) for item in parsed[1])
    if kind == "or":
        return any(_matches(attrs, item) for item in parsed[1])
    if kind == "not":
        return not _matches(attrs, parsed[1])
    if kind == "present":
        return bool(_values(attrs, parsed[1]))
    if kind == "eq":
        attr, wanted = parsed[1], parsed[2]
        return any(_equal_value(attr, stored, wanted) for stored in _values(attrs, attr))
    raise ValueError("invalid filter")


def _normalize_attrs(changes: Mapping[str, Any]) -> Attributes:
    if not isinstance(changes, Mapping):
        raise TypeError("attributes must be a mapping")
    attrs: Attributes = {}
    for name, raw in changes.items():
        if not isinstance(name, str) or name == "":
            raise ValueError("attribute name must be a string")
        if isinstance(raw, str):
            values = [raw]
        elif isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)):
            values = []
            for item in raw:
                if not isinstance(item, str):
                    raise TypeError(f"{name} values must be strings")
                values.append(item)
        else:
            raise TypeError(f"{name} values must be a string or a list")
        if values:
            attrs[name] = values
    if _find_key(attrs, "objectClass") is None:
        raise ValueError("objectClass is required")
    return attrs


def _apply_change(attrs: Attributes, change: Mapping[str, Any]) -> None:
    op = change.get("op")
    name = change.get("attr")
    if not isinstance(name, str) or name == "":
        raise ValueError("modify change needs attr")
    raw_values = change.get("values", [])
    if raw_values is None:
        raw_values = []
    if isinstance(raw_values, str) or not isinstance(raw_values, Sequence):
        raise TypeError("modify values must be a list")
    values = [item if isinstance(item, str) else str(item) for item in raw_values]
    key = _find_key(attrs, name)
    current = list(attrs.get(key, [])) if key else []
    if op == "add":
        if not values:
            raise ValueError("add needs values")
        for value in values:
            if any(_equal_value(name, item, value) for item in current):
                raise ValueError("typeOrValueExists")
        attrs[key or name] = current + values
        return
    if op == "delete":
        if key is None:
            raise ValueError("noSuchAttribute")
        if not values:
            del attrs[key]
            return
        remaining = [
            item for item in current if not any(_equal_value(name, item, value) for value in values)
        ]
        if len(remaining) == len(current):
            raise ValueError("noSuchAttribute")
        if remaining:
            attrs[key] = remaining
        else:
            del attrs[key]
        return
    if op == "replace":
        if not values:
            if key is not None:
                del attrs[key]
            return
        if key is not None and key != name:
            del attrs[key]
        attrs[name] = values
        return
    raise ValueError("invalid modify op")


def _replace_rdn(entry: Attributes, old_dn: str, newrdn: str, delete_old: bool) -> None:
    old_attr, _, old_value = _rdns(old_dn)[0].partition("=")
    new_attr, _, new_value = newrdn.partition("=")
    old_attr = old_attr.strip()
    old_value = old_value.strip()
    new_attr = new_attr.strip()
    new_value = new_value.strip()
    if new_attr == "" or new_value == "":
        raise ValueError("rename changes need newrdn")
    if delete_old:
        key = _find_key(entry, old_attr)
        if key is not None:
            remaining = [item for item in entry[key] if item.casefold() != old_value.casefold()]
            if remaining:
                entry[key] = remaining
            else:
                del entry[key]
    key = _find_key(entry, new_attr)
    values = list(entry.get(key, [])) if key else []
    if not any(item.casefold() == new_value.casefold() for item in values):
        values.append(new_value)
    entry[key or new_attr] = values


def _password(changes: Any) -> str:
    if isinstance(changes, str):
        return changes
    if not isinstance(changes, Mapping):
        raise TypeError("bind changes must be a mapping")
    if "password" in changes:
        password = changes["password"]
        if not isinstance(password, str):
            raise TypeError("password must be a string")
        return password
    raw = changes.get("userPassword")
    if isinstance(raw, str):
        return raw
    if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)) and raw:
        first = raw[0]
        if not isinstance(first, str):
            raise TypeError("password must be a string")
        return first
    raise ValueError("bind changes need a password")


def _password_matches(entry: Attributes, password: str) -> bool:
    return any(stored == password for stored in _values(entry, "userPassword"))


def _locked(entry: Attributes) -> bool:
    values = _values(entry, "pwdAccountLockedTime")
    return LOCK_TIME in values or bool(values)


def _in_scope(candidate: str, base: str, scope: str) -> bool:
    if scope in {"base", "baseobject"}:
        return norm_dn(candidate) == norm_dn(base)
    if scope in {"one", "onelevel"}:
        parent = parent_dn(candidate)
        if parent == "":
            return False
        return norm_dn(parent) == norm_dn(base)
    if scope in {"sub", "subtree"}:
        return under(candidate, base)
    raise ValueError("invalid scope")


class FakeConnection:
    """ACL-enforcing directory. Pass directory= to share entries across binds."""

    def __init__(self, directory: Directory | None = None) -> None:
        self.entries: Directory = directory if directory is not None else load_directory()
        self.bound_dn: str | None = None

    def _key(self, dn: str) -> str | None:
        want = norm_dn(dn)
        for existing in self.entries:
            if norm_dn(existing) == want:
                return existing
        return None

    def _actor(self) -> str:
        if self.bound_dn is None:
            raise PermissionError("not bound")
        return self.bound_dn

    def _require_write(self, dn: str) -> None:
        actor = norm_dn(self._actor())
        if actor == norm_dn(AGGREGATOR_DN):
            raise PermissionError("aggregator cannot write")
        if actor == norm_dn(PROVISIONER_DN):
            if not (under(dn, PEOPLE_DN) or under(dn, GROUPS_DN)):
                raise PermissionError("provisioner cannot write outside ou=People and ou=Groups")
            return
        if actor == norm_dn(ADMIN_DN):
            return
        raise PermissionError("write denied")

    def _can_see(self, dn: str) -> bool:
        actor = norm_dn(self._actor())
        if actor in {norm_dn(AGGREGATOR_DN), norm_dn(PROVISIONER_DN), norm_dn(ADMIN_DN)}:
            return True
        return actor == norm_dn(dn)

    def _can_read_password(self, dn: str) -> bool:
        actor = norm_dn(self._actor())
        if actor == norm_dn(ADMIN_DN):
            return True
        if actor == norm_dn(PROVISIONER_DN) and (under(dn, PEOPLE_DN) or under(dn, GROUPS_DN)):
            return True
        return actor == norm_dn(dn) and under(dn, PEOPLE_DN)

    def _selected(self, attrs: Attributes, requested: Sequence[str] | None) -> list[str]:
        if requested is not None and (
            isinstance(requested, (str, bytes)) or not isinstance(requested, Sequence)
        ):
            raise TypeError("attributes must be a list")
        names = list(requested) if requested is not None else ["*", "+"]
        want_user = any(item == "*" for item in names)
        want_operational = any(item == "+" for item in names)
        chosen: list[str] = []
        if want_user:
            chosen.extend(name for name in attrs if name.casefold() not in _OPERATIONAL)
        if want_operational:
            chosen.extend(name for name in attrs if name.casefold() in _OPERATIONAL)
        for item in names:
            if item in {"*", "+"}:
                continue
            key = _find_key(attrs, item)
            if key is not None and key not in chosen:
                chosen.append(key)
        return chosen

    def _public(self, dn: str, attrs: Attributes, requested: Sequence[str] | None) -> Attributes:
        visible: Attributes = {}
        for name in self._selected(attrs, requested):
            if name.casefold() == "userpassword" and not self._can_read_password(dn):
                continue
            if not self._can_see(dn):
                continue
            visible[name] = list(attrs[name])
        return visible

    def bind(self, dn: str, changes: Any = None) -> dict[str, str]:
        password = _password(changes)
        self.bound_dn = None
        key = self._key(dn)
        entry = self.entries.get(key) if key is not None else None
        if key is None or entry is None or not _password_matches(entry, password):
            raise BindError("invalidCredentials")
        if _locked(entry):
            raise BindError("locked")
        self.bound_dn = key
        return {"dn": key, "result": "success"}

    def search(self, dn: str, changes: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
        self._actor()
        if changes is None:
            changes = {}
        if not isinstance(changes, Mapping):
            raise TypeError("search changes must be a mapping")
        if self._key(dn) is None:
            raise LdapError("noSuchObject", dn)
        scope = str(changes.get("scope", "subtree")).lower()
        filt = changes.get("filter", "(objectClass=*)")
        if not isinstance(filt, str):
            raise TypeError("filter must be a string")
        parsed = _parse_filter(filt)
        requested = changes.get("attributes")
        found: list[dict[str, Any]] = []
        for key in sorted(self.entries, key=norm_dn):
            if not _in_scope(key, dn, scope) or not self._can_see(key):
                continue
            attrs = self.entries[key]
            if not _matches(attrs, parsed):
                continue
            found.append({"dn": key, "attributes": self._public(key, attrs, requested)})
        return found

    def add(self, dn: str, changes: Mapping[str, Any] | None = None) -> dict[str, str]:
        self._require_write(dn)
        if changes is None:
            raise ValueError("add changes must be attributes")
        if self._key(dn) is not None:
            raise LdapError("alreadyExists", dn)
        parent = parent_dn(dn)
        if parent == "" or self._key(parent) is None:
            raise LdapError("noSuchObject", parent or dn)
        self.entries[dn] = _normalize_attrs(changes)
        _recompute_memberof(self.entries)
        return {"dn": dn, "result": "success"}

    def modify(self, dn: str, changes: Any = None) -> dict[str, str]:
        self._require_write(dn)
        key = self._key(dn)
        if key is None:
            raise LdapError("noSuchObject", dn)
        if isinstance(changes, (str, bytes)) or not isinstance(changes, Sequence) or not changes:
            raise ValueError("modify changes must be a non-empty list")
        updated = copy.deepcopy(self.entries[key])
        for change in changes:
            if not isinstance(change, Mapping):
                raise TypeError("modify change must be a mapping")
            _apply_change(updated, change)
        self.entries[key] = updated
        _recompute_memberof(self.entries)
        return {"dn": key, "result": "success"}

    def delete(self, dn: str, changes: Any = None) -> dict[str, str]:
        del changes
        self._require_write(dn)
        key = self._key(dn)
        if key is None:
            raise LdapError("noSuchObject", dn)
        base = norm_dn(key)
        if any(
            norm_dn(other) != base and norm_dn(other).endswith("," + base) for other in self.entries
        ):
            raise LdapError("notAllowedOnNonLeaf", dn)
        self.entries.pop(key)
        _remove_dn_refs(self.entries, key)
        _recompute_memberof(self.entries)
        if self.bound_dn is not None and norm_dn(self.bound_dn) == base:
            self.bound_dn = None
        return {"dn": key, "result": "success"}

    def rename(self, dn: str, changes: Mapping[str, Any] | None = None) -> dict[str, str]:
        if not isinstance(changes, Mapping) or not isinstance(changes.get("newrdn"), str):
            raise ValueError("rename changes need newrdn")
        source = self._key(dn)
        self._require_write(dn)
        if source is None:
            raise LdapError("noSuchObject", dn)
        newrdn = str(changes["newrdn"]).strip()
        delete_old = bool(changes.get("deleteoldrdn", True))
        if changes.get("newsuperior"):
            superior_dn = str(changes["newsuperior"])
            superior = self._key(superior_dn)
            if superior is None:
                raise LdapError("noSuchObject", superior_dn)
        else:
            superior = parent_dn(source)
            if superior == "" or self._key(superior) is None:
                raise LdapError("noSuchObject", superior or dn)
        new_dn = f"{newrdn},{superior}"
        self._require_write(new_dn)
        moves: list[tuple[str, str]] = []
        for key in list(self.entries):
            rewritten = _with_new_suffix(key, source, new_dn)
            if rewritten is not None:
                moves.append((key, rewritten))
        old_norms = {norm_dn(old) for old, _ in moves}
        for _, destination in moves:
            existing = self._key(destination)
            if existing is not None and norm_dn(existing) not in old_norms:
                raise LdapError("alreadyExists", destination)
        for old, destination in sorted(moves, key=lambda item: len(_rdns(item[0])), reverse=True):
            entry = self.entries.pop(old)
            if norm_dn(old) == norm_dn(source):
                _replace_rdn(entry, old, newrdn, delete_old)
            self.entries[destination] = entry
        _rewrite_dn_values(self.entries, moves)
        _recompute_memberof(self.entries)
        if self.bound_dn is not None and norm_dn(self.bound_dn) == norm_dn(source):
            stored = self._key(new_dn)
            self.bound_dn = stored if stored is not None else new_dn
        stored_new = self._key(new_dn)
        return {"dn": stored_new or new_dn, "previous": source, "result": "success"}
