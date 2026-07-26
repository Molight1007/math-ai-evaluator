"""Pydantic 数据模型。"""
from pydantic import BaseModel


class RegisterRequest(BaseModel):
    username: str
    password: str


class LoginRequest(BaseModel):
    username: str
    password: str


class BankCreateRequest(BaseModel):
    name: str


class ApproveRequest(BaseModel):
    username: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str
    status: str
    is_admin: bool
