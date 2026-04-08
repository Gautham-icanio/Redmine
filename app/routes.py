from fastapi import APIRouter
from app.models import UserCreate, UserResponse

router = APIRouter()

@router.get('/health')
def health_check():
    return {"status": "ok", "version": "1.0.0"}

@router.post('/users', response_model=UserResponse)
def create_user(user: UserCreate):
    return {"id": 1, "username": user.username, "email": user.email}

@router.get('/users/{user_id}', response_model=UserResponse)
def get_user(user_id: int):
    return {"id": user_id, "username": "sample_user", "email": "sample@eva.com"}
