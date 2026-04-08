from pydantic import BaseModel
from typing import Union

class UserCreate(BaseModel):
    username: str
    password: Union[str, int]
    email: str

class UserResponse(BaseModel):
    id: int
    username: str
    email: str
# fix
