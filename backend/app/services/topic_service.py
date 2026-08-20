from app.core.errors import DomainError

TECHNICAL_TERMS = {
    "java", "python", "javascript", "typescript", "react", "vue", "taro", "redis",
    "mysql", "postgresql", "sql", "mongodb", "hashmap", "spring", "docker", "kubernetes",
    "tcp", "http", "https", "dns", "网络", "操作系统", "数据库", "算法", "数据结构",
    "线程", "进程", "内存", "索引", "事务", "锁", "缓存", "消息队列", "微服务", "git",
    "linux", "前端", "后端", "编程", "代码", "系统设计", "面试题", "面试",
}
BLOCKED_TERMS = ("实时面试代答", "面试作弊", "替考", "帮我现场回答")


def validate_topic_scope(user_input: str) -> None:
    lowered = user_input.lower()
    if any(term in lowered for term in BLOCKED_TERMS):
        raise DomainError(4001, "EasyOffer 不提供实时面试代答或作弊支持，请改为事后学习。")
    if not any(term in lowered for term in TECHNICAL_TERMS):
        raise DomainError(
            4001,
            "当前只支持程序员技术面试相关知识点",
            400,
            {"supported": False, "examples": ["TCP 三次握手", "Java HashMap", "React useEffect"]},
        )
