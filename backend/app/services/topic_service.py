import re
from dataclasses import dataclass
from urllib.parse import urlparse

from app.core.errors import DomainError


# These requests are outside the product's learning scope and must never be
# delegated to the model. Technical-topic eligibility is judged by the model.
BLOCKED_TERMS = ("实时面试代答", "面试作弊", "替考", "帮我现场回答")

# User input is often a learning request rather than a topic (for example,
# "我想学习 Redis 持久化机制"). Keep the technical identifiers while removing
# conversational wrappers before routing, searching, and building prompts.
_LEARNING_PREFIXES = (
    r"我想(?:要)?(?:学习|学|了解|掌握|知道)",
    r"我希望(?:学习|了解|掌握)",
    r"请(?:你)?(?:给我)?(?:讲(?:一下)?|介绍(?:一下)?|解释(?:一下)?|说明(?:一下)?)",
    r"给我(?:讲(?:一下)?|介绍(?:一下)?|解释(?:一下)?)",
    r"(?:如何|怎么)(?:去)?学习",
    r"帮我(?:学习|了解|掌握)",
)
_LEARNING_PREFIX_RE = re.compile(r"^(?:" + "|".join(_LEARNING_PREFIXES) + r")[\s:：,，、-]*", re.IGNORECASE)


@dataclass(frozen=True)
class TopicPreparationResult:
    canonical_topic: str
    is_url: bool
    subtopics: tuple[str, ...]
    mode: str = "normal"


def prepare_topic(value: str, mode: str = "normal") -> TopicPreparationResult:
    """Normalize a user topic before scope judgement or retrieval."""
    canonical = normalize_learning_topic(value)
    parsed = urlparse(canonical)
    is_url = parsed.scheme.lower() in {"http", "https"} and bool(parsed.netloc)
    if is_url:
        parts: tuple[str, ...] = ()
    else:
        pieces = [item.strip() for item in re.split(r"[,，、;；\n]+", canonical) if item.strip()]
        parts = tuple(dict.fromkeys(pieces))
    return TopicPreparationResult(canonical, is_url, parts, mode)


def normalize_learning_topic(value: str) -> str:
    """Return the technical subject without conversational request wrappers."""
    topic = " ".join(str(value or "").strip().split())
    # Apply repeatedly to handle inputs such as "请给我讲一下我想学习 Redis".
    previous = None
    while topic and topic != previous:
        previous = topic
        topic = _LEARNING_PREFIX_RE.sub("", topic).strip(" ：:,，、-\t")
    return topic or " ".join(str(value or "").strip().split())


def validate_topic_scope(user_input: str) -> None:
    """Apply only deterministic safety rules before AI topic classification."""
    lowered = user_input.lower()
    if any(term in lowered for term in BLOCKED_TERMS):
        raise DomainError(4001, "EasyOffer 不提供实时面试代答或作弊支持，请改为事后学习。")
