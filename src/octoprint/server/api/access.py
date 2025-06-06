__author__ = "Marc Hannappel <salandora@gmail.com>"
__license__ = "GNU Affero General Public License http://www.gnu.org/licenses/agpl.html"
__copyright__ = "Copyright (C) 2017 The OctoPrint Project - Released under terms of the AGPLv3 License"

from flask import abort, jsonify, request
from flask_login import current_user

import octoprint.access.groups as groups
import octoprint.access.users as users
from octoprint.access.permissions import Permissions
from octoprint.server import SUCCESS, groupManager, userManager
from octoprint.server.api import api, valid_boolean_trues
from octoprint.server.util.flask import (
    credentials_checked_recently,
    ensure_credentials_checked_recently,
    no_firstrun_access,
    require_credentials_checked_recently,
)

# ~~ permission api


@api.route("/access/permissions", methods=["GET"])
def get_permissions():
    return jsonify(permissions=[permission.as_dict() for permission in Permissions.all()])


# ~~ group api


@api.route("/access/groups", methods=["GET"])
@no_firstrun_access
@Permissions.ADMIN.require(403)
def get_groups():
    return jsonify(groups=[g.as_dict() for g in groupManager.groups])


@api.route("/access/groups", methods=["POST"])
@no_firstrun_access
@require_credentials_checked_recently
@Permissions.ADMIN.require(403)
def add_group():
    data = request.get_json()

    if "key" not in data:
        abort(400, description="key is missing")
    if "name" not in data:
        abort(400, description="name is missing")
    if "permissions" not in data:
        abort(400, description="permissions are missing")

    key = data["key"]
    name = data["name"]
    description = data.get("description", "")
    permissions = data["permissions"]
    subgroups = data["subgroups"]
    default = data.get("default", False)

    try:
        groupManager.add_group(
            key,
            name,
            description=description,
            permissions=permissions,
            subgroups=subgroups,
            default=default,
        )
    except groups.GroupAlreadyExists:
        abort(409)
    return get_groups()


@api.route("/access/groups/<key>", methods=["GET"])
@no_firstrun_access
@Permissions.ADMIN.require(403)
def get_group(key):
    group = groupManager.find_group(key)
    if group is not None:
        return jsonify(group)
    else:
        abort(404)


@api.route("/access/groups/<key>", methods=["PUT"])
@no_firstrun_access
@require_credentials_checked_recently
@Permissions.ADMIN.require(403)
def update_group(key):
    data = request.get_json()

    try:
        kwargs = {}

        if "permissions" in data:
            kwargs["permissions"] = data["permissions"]

        if "subgroups" in data:
            kwargs["subgroups"] = data["subgroups"]

        if "default" in data:
            kwargs["default"] = data["default"] in valid_boolean_trues

        if "description" in data:
            kwargs["description"] = data["description"]

        groupManager.update_group(key, **kwargs)

        return get_groups()
    except groups.GroupCantBeChanged:
        abort(403)
    except groups.UnknownGroup:
        abort(404)


@api.route("/access/groups/<key>", methods=["DELETE"])
@no_firstrun_access
@require_credentials_checked_recently
@Permissions.ADMIN.require(403)
def remove_group(key):
    try:
        groupManager.remove_group(key)
        return get_groups()
    except groups.UnknownGroup:
        abort(404)
    except groups.GroupUnremovable:
        abort(403)


# ~~ user api


@api.route("/access/users", methods=["GET"])
@no_firstrun_access
@Permissions.ADMIN.require(403)
def get_users():
    users = [u.as_dict() for u in userManager.get_all_users()]
    if not credentials_checked_recently():
        for u in users:
            u["apikey"] = None
    return jsonify(users=users)


@api.route("/access/users", methods=["POST"])
@no_firstrun_access
@require_credentials_checked_recently
@Permissions.ADMIN.require(403)
def add_user():
    data = request.get_json()

    if "name" not in data:
        abort(400, description="name is missing")
    if "password" not in data:
        abort(400, description="password is missing")
    if "active" not in data:
        abort(400, description="active is missing")

    name = data["name"]
    password = data["password"]
    active = data["active"] in valid_boolean_trues

    groups = data.get("groups", None)
    permissions = data.get("permissions", None)

    try:
        userManager.add_user(name, password, active, permissions, groups)
    except users.UserAlreadyExists:
        abort(409)
    except users.InvalidUsername:
        abort(400, "Username invalid")
    return get_users()


@api.route("/access/users/<username>", methods=["GET"])
@no_firstrun_access
def get_user(username):
    if (
        current_user is not None
        and not current_user.is_anonymous
        and (
            current_user.get_name() == username
            or current_user.has_permission(Permissions.ADMIN)
        )
    ):
        user = userManager.find_user(username)
        if user is not None:
            user_dict = user.as_dict()
            if not credentials_checked_recently():
                user_dict["apikey"] = None
            return jsonify(user_dict)
        else:
            abort(404)
    else:
        abort(403)


@api.route("/access/users/<username>", methods=["PUT"])
@no_firstrun_access
@require_credentials_checked_recently
@Permissions.ADMIN.require(403)
def update_user(username):
    user = userManager.find_user(username)
    if user is not None:
        data = request.get_json()

        # change groups
        if "groups" in data:
            groups = data["groups"]
            userManager.change_user_groups(username, groups)

        # change permissions
        if "permissions" in data:
            permissions = data["permissions"]
            userManager.change_user_permissions(username, permissions)

        # change activation
        if "active" in data:
            userManager.change_user_activation(
                username, data["active"] in valid_boolean_trues
            )

        return get_users()
    else:
        abort(404)


@api.route("/access/users/<username>", methods=["DELETE"])
@no_firstrun_access
@require_credentials_checked_recently
@Permissions.ADMIN.require(403)
def remove_user(username):
    if not userManager.enabled:
        return jsonify(SUCCESS)

    if current_user.get_name() == username:
        abort(400, description="You cannot delete yourself")

    try:
        userManager.remove_user(username)
        return get_users()
    except users.UnknownUser:
        abort(404)


@api.route("/access/users/<username>/password", methods=["PUT"])
@no_firstrun_access
def change_password_for_user(username):
    if not userManager.enabled:
        return jsonify(SUCCESS)

    if (
        current_user is not None
        and not current_user.is_anonymous
        and (
            current_user.get_name() == username
            or current_user.has_permission(Permissions.ADMIN)
        )
    ):
        data = request.get_json()

        if "password" not in data or not data["password"]:
            abort(400, description="new password is missing")

        if current_user.get_name() == username:
            if "current" not in data or not data["current"]:
                abort(400, description="current password is missing")

            if not userManager.check_password(username, data["current"]):
                abort(403, description="Invalid current password")

        elif current_user.has_permission(Permissions.ADMIN):
            ensure_credentials_checked_recently()

        else:
            # this should never happen
            abort(403, description="You are not allowed to change this user's password")

        try:
            userManager.change_user_password(username, data["password"])
        except users.UnknownUser:
            abort(404)

        return jsonify(SUCCESS)
    else:
        abort(403)


@api.route("/access/users/<username>/settings", methods=["GET"])
@no_firstrun_access
def get_settings_for_user(username):
    if (
        current_user is None
        or current_user.is_anonymous
        or (
            current_user.get_name() != username
            and not current_user.has_permission(Permissions.ADMIN)
        )
    ):
        abort(403)

    try:
        return jsonify(userManager.get_all_user_settings(username))
    except users.UnknownUser:
        abort(404)


@api.route("/access/users/<username>/settings", methods=["PATCH"])
@no_firstrun_access
def change_settings_for_user(username):
    if (
        current_user is None
        or current_user.is_anonymous
        or (
            current_user.get_name() != username
            and not current_user.has_permission(Permissions.ADMIN)
        )
    ):
        abort(403)

    if current_user.get_name() != username:
        # this must be an admin, so we need to ensure credentials were checked
        ensure_credentials_checked_recently()

    data = request.get_json()

    try:
        userManager.change_user_settings(username, data)
        return jsonify(SUCCESS)
    except users.UnknownUser:
        abort(404)


@api.route("/access/users/<username>/apikey", methods=["DELETE"])
@no_firstrun_access
@require_credentials_checked_recently
def delete_apikey_for_user(username):
    if (
        current_user is not None
        and not current_user.is_anonymous
        and (
            current_user.get_name() == username
            or current_user.has_permission(Permissions.ADMIN)
        )
    ):
        if current_user.get_name() != username:
            # this must be an admin, so we need to ensure credentials were checked
            ensure_credentials_checked_recently()

        try:
            userManager.delete_api_key(username)
        except users.UnknownUser:
            abort(404)
        return jsonify(SUCCESS)
    else:
        abort(403)


@api.route("/access/users/<username>/apikey", methods=["POST"])
@no_firstrun_access
@require_credentials_checked_recently
def generate_apikey_for_user(username):
    if not userManager.enabled:
        return jsonify(SUCCESS)

    if (
        current_user is not None
        and not current_user.is_anonymous
        and (
            current_user.get_name() == username
            or current_user.has_permission(Permissions.ADMIN)
        )
    ):
        if current_user.get_name() != username:
            # this must be an admin, so we need to ensure credentials were checked
            ensure_credentials_checked_recently()

        try:
            apikey = userManager.generate_api_key(username)
        except users.UnknownUser:
            abort(404)
        return jsonify({"apikey": apikey})
    else:
        abort(403)


def _to_external_permissions(*permissions):
    return [p.get_name() for p in permissions]


def _to_external_groups(*groups):
    return [g.get_name() for g in groups]
