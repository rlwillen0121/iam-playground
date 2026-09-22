"""SCIM operations. Each call is one transaction, including multi-operation PATCH."""

from __future__ import annotations

import uuid
from collections.abc import Callable

from sqlalchemy.exc import IntegrityError

from iam_playground.errors import DependencyFailure, ScimError
from iam_playground.records import GroupRecord, UserRecord
from iam_playground.scim_codec import (
    apply_user_operation,
    canonical_uuid,
    group_change,
    group_resource,
    list_body,
    parse_group_create,
    parse_user_create,
    patch_operations,
    user_resource,
)
from iam_playground.scim_filter import GROUP_FILTERS, USER_FILTERS, parse_equality_filter


def scim_tx(store: object, work: Callable) -> object:
    try:
        with store.transaction() as unit:
            return work(unit)
    except ScimError:
        raise
    except Exception as exc:
        raise DependencyFailure("database") from exc


def create_user(store: object, app_id: str, actor: str, body: object) -> dict:
    incoming = parse_user_create(body)

    def work(unit: object) -> dict:
        generation = unit.require_generation()
        if unit.username_taken(app_id, incoming.user_name):
            raise ScimError(409, "userName is already in use", "uniqueness")
        user = UserRecord(
            id=str(uuid.uuid4()),
            app_id=app_id,
            external_id=incoming.external_id,
            user_name=incoming.user_name,
            active=incoming.active,
            given_name=incoming.given_name,
            family_name=incoming.family_name,
            email=incoming.email,
            employee_number=incoming.employee_number,
            department=incoming.department,
        )
        try:
            unit.insert_user(user)
        except IntegrityError as exc:
            raise ScimError(409, "userName is already in use", "uniqueness") from exc
        unit.journal(generation, app_id, actor, "create", user.id)
        return user_resource(user)

    return scim_tx(store, work)


def get_user(store: object, app_id: str, user_id: str) -> dict:
    canonical = _existing_id(user_id, "user not found")

    def work(unit: object) -> dict:
        unit.require_generation()
        user = unit.get_user(app_id, canonical)
        if user is None:
            raise ScimError(404, "user not found")
        return user_resource(user)

    return scim_tx(store, work)


def list_users(
    store: object,
    app_id: str,
    filter_text: str | None,
    start_index: int,
    count: int,
) -> dict:
    filt = parse_equality_filter(filter_text, USER_FILTERS)

    def work(unit: object) -> dict:
        unit.require_generation()
        rows, total = unit.list_users(app_id, filt, start_index, count)
        return list_body([user_resource(row) for row in rows], total, start_index)

    return scim_tx(store, work)


def patch_user(store: object, app_id: str, actor: str, user_id: str, body: object) -> dict:
    operations = patch_operations(body)
    canonical = _existing_id(user_id, "user not found")

    def work(unit: object) -> dict:
        generation = unit.require_generation()
        user = unit.get_user(app_id, canonical)
        if user is None:
            raise ScimError(404, "user not found")
        for operation in operations:
            apply_user_operation(user, operation)
        unit.save_user(user)
        unit.journal(generation, app_id, actor, "replace", user.id)
        return user_resource(user)

    return scim_tx(store, work)


def delete_user(store: object, app_id: str, actor: str, user_id: str) -> None:
    canonical = _existing_id(user_id, "user not found")

    def work(unit: object) -> None:
        generation = unit.require_generation()
        removed = unit.delete_user(app_id, canonical)
        if removed is None:
            raise ScimError(404, "user not found")
        for group_id in removed:
            unit.journal(generation, app_id, actor, "member.remove", f"{group_id}:{canonical}")
        unit.journal(generation, app_id, actor, "delete", canonical)

    scim_tx(store, work)


def create_group(store: object, app_id: str, actor: str, body: object) -> dict:
    display_name, external_id, member_ids = parse_group_create(body)

    def work(unit: object) -> dict:
        generation = unit.require_generation()
        if unit.display_name_taken(app_id, display_name):
            raise ScimError(409, "displayName is already in use", "uniqueness")
        group = GroupRecord(
            id=str(uuid.uuid4()),
            app_id=app_id,
            display_name=display_name,
            external_id=external_id,
        )
        try:
            unit.insert_group(group)
        except IntegrityError as exc:
            raise ScimError(409, "displayName is already in use", "uniqueness") from exc
        unit.journal(generation, app_id, actor, "create", group.id)
        for user_id in member_ids:
            if unit.add_member(app_id, group.id, user_id):
                unit.journal(generation, app_id, actor, "member.add", f"{group.id}:{user_id}")
        return group_resource(group, unit.member_ids(app_id, group.id))

    return scim_tx(store, work)


def get_group(store: object, app_id: str, group_id: str) -> dict:
    canonical = _existing_id(group_id, "group not found")

    def work(unit: object) -> dict:
        unit.require_generation()
        group = unit.get_group(app_id, canonical)
        if group is None:
            raise ScimError(404, "group not found")
        return group_resource(group, unit.member_ids(app_id, group.id))

    return scim_tx(store, work)


def list_groups(
    store: object,
    app_id: str,
    filter_text: str | None,
    start_index: int,
    count: int,
) -> dict:
    filt = parse_equality_filter(filter_text, GROUP_FILTERS)

    def work(unit: object) -> dict:
        unit.require_generation()
        rows, total = unit.list_groups(app_id, filt, start_index, count)
        resources = [group_resource(group, members) for group, members in rows]
        return list_body(resources, total, start_index)

    return scim_tx(store, work)


def patch_group(store: object, app_id: str, actor: str, group_id: str, body: object) -> dict:
    operations = patch_operations(body)
    canonical = _existing_id(group_id, "group not found")

    def work(unit: object) -> dict:
        generation = unit.require_generation()
        group = unit.get_group(app_id, canonical)
        if group is None:
            raise ScimError(404, "group not found")
        for operation in operations:
            kind, user_ids = group_change(operation)
            for user_id in user_ids:
                if kind == "add":
                    if unit.add_member(app_id, group.id, user_id):
                        unit.journal(generation, app_id, actor, "member.add", f"{group.id}:{user_id}")
                elif unit.remove_member(app_id, group.id, user_id):
                    unit.journal(generation, app_id, actor, "member.remove", f"{group.id}:{user_id}")
        return group_resource(group, unit.member_ids(app_id, group.id))

    return scim_tx(store, work)


def delete_group(store: object, app_id: str, actor: str, group_id: str) -> None:
    canonical = _existing_id(group_id, "group not found")

    def work(unit: object) -> None:
        generation = unit.require_generation()
        removed = unit.delete_group(app_id, canonical)
        if removed is None:
            raise ScimError(404, "group not found")
        for user_id in removed:
            unit.journal(generation, app_id, actor, "member.remove", f"{canonical}:{user_id}")
        unit.journal(generation, app_id, actor, "delete", canonical)

    scim_tx(store, work)


def _existing_id(value: str, missing: str) -> str:
    canonical = canonical_uuid(value)
    if canonical is None:
        raise ScimError(404, missing)
    return canonical
