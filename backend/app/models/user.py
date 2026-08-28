from pydantic import Field, HttpUrl

from app.models.common import StrictModel


class UserLoginRequest(StrictModel):
    code: str = Field(min_length=1, max_length=512)


class UserProfileUpdate(StrictModel):
    nickname: str | None = Field(default=None, min_length=1, max_length=100)
    avatar_url: HttpUrl | None = None


class UserSummary(StrictModel):
    id: int
    nickname: str
    avatar_url: str
    total_xp: int


class UserLoginResponse(StrictModel):
    token: str
    user: UserSummary


class UserProfile(UserSummary):
    quiz_count: int
    correct_count: int
    average_accuracy: float


class QuizHistoryItem(StrictModel):
    quiz_id: str
    title: str
    accuracy: float
    question_count: int
    created_at: str


class QuizHistoryPage(StrictModel):
    items: list[QuizHistoryItem]
    total: int
    page: int
    page_size: int


class QuizHistoryDetail(StrictModel):
    quiz: dict
    answer_records: list[dict]
    report: dict | None
