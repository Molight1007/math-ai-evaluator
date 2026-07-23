"""鉴权路由：注册、登录(JWT)、审批、当前用户、待审列表。"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt

from . import config, users
from .schemas import RegisterRequest, LoginRequest, ApproveRequest, TokenResponse

router = APIRouter(prefix="/api/auth", tags=["auth"])
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


def create_access_token(username: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=config.ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {"sub": username, "exp": expire}
    return jwt.encode(payload, config.SECRET_KEY, algorithm=config.ALGORITHM)


def get_current_user(token: str = Depends(oauth2_scheme)) -> dict:
    cred_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="无效或过期的凭证",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, config.SECRET_KEY, algorithms=[config.ALGORITHM])
        username = payload.get("sub")
        if not username:
            raise cred_exc
    except JWTError:
        raise cred_exc
    user = users.get_user(username)
    if not user:
        raise cred_exc
    return user


def require_admin(user: dict = Depends(get_current_user)) -> dict:
    if not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user


@router.post("/register")
def register(req: RegisterRequest):
    ok, msg = users.register(req.username, req.password)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"message": msg, "status": "approved" if config.ALLOW_PUBLIC else "pending"}


@router.post("/login")
def login(req: LoginRequest):
    if not users.verify_password(req.username, req.password):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    user = users.get_user(req.username)
    if user["status"] != "approved":
        detail = "账户待审批，请联系管理员" if user["status"] == "pending" else "账户已被拒绝"
        raise HTTPException(status_code=403, detail=detail)
    token = create_access_token(req.username)
    return TokenResponse(
        access_token=token,
        username=user["username"],
        status=user["status"],
        is_admin=bool(user["is_admin"]),
    )


@router.get("/me")
def me(user: dict = Depends(get_current_user)):
    return user


@router.get("/pending")
def pending(admin: dict = Depends(require_admin)):
    return [u for u in users.list_users() if u["status"] == "pending"]


@router.get("/users")
def all_users(admin: dict = Depends(require_admin)):
    return users.list_users()


@router.post("/approve")
def approve(req: ApproveRequest, admin: dict = Depends(require_admin)):
    if req.username == admin["username"]:
        raise HTTPException(status_code=400, detail="不能操作自己")
    if not users.set_status(req.username, "approved"):
        raise HTTPException(status_code=404, detail="用户不存在")
    return {"message": f"已通过 {req.username}"}


@router.post("/reject")
def reject(req: ApproveRequest, admin: dict = Depends(require_admin)):
    if req.username == admin["username"]:
        raise HTTPException(status_code=400, detail="不能操作自己")
    if not users.set_status(req.username, "rejected"):
        raise HTTPException(status_code=404, detail="用户不存在")
    return {"message": f"已拒绝 {req.username}"}
