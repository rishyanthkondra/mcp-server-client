from typing import Optional
from pydantic import BaseModel

class User(BaseModel):
    user_id: int
    fullname: Optional[str] = None
    group_id: Optional[str] = None
    location: str
