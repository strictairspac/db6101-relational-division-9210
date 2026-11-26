from typing import Annotated

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from src.config.settings import JWT_SECRET
from src.constants.roles import Role

bearer = HTTPBearer(auto_error=False)


def identity(credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]):
    if credentials is None:
        raise HTTPException(401, "请先登录")
    try:
        claims = jwt.decode(
            credentials.credentials, JWT_SECRET, algorithms=["HS256"], options={"require": ["exp", "sub", "role"]}
        )
        return {"username": claims["sub"], "role": Role(claims["role"])}
    except (jwt.InvalidTokenError, ValueError) as exc:
        raise HTTPException(401, "登录状态失效，请重新登录") from exc


def require_role(role):
    def authorize(user=Depends(identity)):
        if user["role"] != role:
            raise HTTPException(403, "当前账号没有此操作权限")
        return user

    return authorize


def require_any(*roles):
    def authorize(user=Depends(identity)):
        if user["role"] not in roles:
            raise HTTPException(403, "当前账号没有此操作权限")
        return user

    return authorize


def staff(user=Depends(identity)):
    # Outsourced teams practise on drill copies only; they must never reach the
    # original cases, batch numbers or vehicle numbers.
    if user["role"] == Role.OUTSOURCE:
        raise HTTPException(403, "外包账号只能访问演练副本")
    return user


operator = require_role(Role.OPERATOR)
reviewer = require_role(Role.REVIEWER)
# Any signed-in account may read drill data: the copies are anonymised and carry
# no original case, batch or vehicle identity.
drill_reader = identity
# Creating and appending drill copies is a资料操作员 task; outsource accounts may
# only rerun an existing copy.
drill_author = operator
drill_runner = require_any(Role.OPERATOR, Role.OUTSOURCE)
