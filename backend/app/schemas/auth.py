from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

PASSWORD_MIN_LENGTH = 10
PASSWORD_MAX_LENGTH = 128


class RegisterRequest(BaseModel):
    email: EmailStr = Field(max_length=320)
    password: str = Field(min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH)

    @model_validator(mode="after")
    def _password_policy(self) -> RegisterRequest:
        if not self.password.strip():
            raise ValueError("Password cannot be only whitespace.")
        if self.password.strip().lower() == self.email.lower():
            raise ValueError("Password cannot be the same as your email address.")
        return self


class LoginRequest(BaseModel):
    email: EmailStr = Field(max_length=320)
    # No minimum here: the policy applies at registration, and a different message for
    # "too short" would leak nothing useful but adds a second code path.
    password: str = Field(min_length=1, max_length=PASSWORD_MAX_LENGTH)


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    created_at: datetime
