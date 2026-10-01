"""Pydantic input schemas."""
import re
from typing import Optional

from pydantic import BaseModel, Field, field_validator

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,30}$")


class RegisterUser(BaseModel):
    username: str
    email: str
    password: str
    full_name: Optional[str] = Field(None, max_length=80)

    @field_validator("username")
    @classmethod
    def _username(cls, v: str) -> str:
        v = v.strip()
        if not USERNAME_RE.match(v):
            raise ValueError("Username must be 3-30 characters: letters, numbers, _ . -")
        return v

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        v = v.strip()
        if not EMAIL_RE.match(v):
            raise ValueError("Enter a valid email address")
        return v

    @field_validator("password")
    @classmethod
    def _password(cls, v: str) -> str:
        if len(v) < 6 or len(v) > 64:
            raise ValueError("Password must be 6-64 characters")
        return v


class HomeBudgetInput(BaseModel):
    total_budget: float = Field(..., gt=0, le=1_000_000_000)
    num_lights: int = Field(0, ge=0, le=500)
    num_fans: int = Field(0, ge=0, le=200)
    num_furniture: int = Field(0, ge=0, le=500)
    num_dining_tables: int = Field(0, ge=0, le=50)
    has_living_room: bool = True
    has_kitchen: bool = False
    has_bedroom: bool = False
    additional_requirements: Optional[str] = Field(None, max_length=1000)


class PartyBudgetInput(BaseModel):
    total_budget: float = Field(..., gt=0, le=1_000_000_000)
    num_guests: int = Field(..., ge=1, le=5000)
    party_type: str = Field("Birthday", min_length=2, max_length=50)
    venue_type: Optional[str] = Field("Home", max_length=80)
    needs_catering: bool = True
    needs_decoration: bool = True
    needs_entertainment: bool = False
    additional_requirements: Optional[str] = Field(None, max_length=1000)


class JewelryBudgetInput(BaseModel):
    total_budget: float = Field(..., gt=0, le=1_000_000_000)
    occasion: str = Field("Casual", min_length=2, max_length=80)
    preferences: Optional[str] = Field(None, max_length=1000)
