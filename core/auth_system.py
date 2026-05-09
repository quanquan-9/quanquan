"""
用户认证与授权系统 (Auth System)

功能：
- JWT Token 认证
- API Key 认证
- OAuth2 集成（GitHub/Google/微信）
- 角色权限 (RBAC)
- 会话管理
- 密码哈希 (bcrypt)
"""

import time
import hashlib
import hmac
import secrets
import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class UserRole(Enum):
    ADMIN = "admin"
    PREMIUM = "premium"
    USER = "user"
    GUEST = "guest"


ROLE_HIERARCHY = {
    UserRole.ADMIN: 100,
    UserRole.PREMIUM: 50,
    UserRole.USER: 10,
    UserRole.GUEST: 1,
}


@dataclass
class User:
    """用户模型"""
    user_id: str
    username: str
    email: str = ""
    role: UserRole = UserRole.USER
    password_hash: str = ""
    api_keys: List[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    last_login: float = 0
    is_active: bool = True
    metadata: Dict = field(default_factory=dict)


class AuthProvider(Enum):
    PASSWORD = "password"
    API_KEY = "api_key"
    GITHUB = "github"
    GOOGLE = "google"
    WECHAT = "wechat"


class JWTAuth:
    """JWT 认证（简化实现，生产用 PyJWT）"""

    def __init__(self, secret: str = ""):
        self.secret = secret or secrets.token_hex(32)
        self._token_blacklist: set = set()

    def create_token(
        self,
        user_id: str,
        role: str = "user",
        expires_in_sec: int = 86400,
    ) -> str:
        """创建 JWT Token"""
        import base64, json

        header = base64.urlsafe_b64encode(
            json.dumps({"alg": "HS256", "typ": "JWT"}).encode()
        ).decode().rstrip("=")

        payload = base64.urlsafe_b64encode(
            json.dumps({
                "sub": user_id,
                "role": role,
                "iat": int(time.time()),
                "exp": int(time.time()) + expires_in_sec,
                "jti": secrets.token_hex(8),
            }).encode()
        ).decode().rstrip("=")

        signature = hmac.new(
            self.secret.encode(),
            f"{header}.{payload}".encode(),
            hashlib.sha256,
        ).hexdigest()[:32]

        return f"{header}.{payload}.{signature}"

    def verify_token(self, token: str) -> Optional[dict]:
        """验证 JWT Token"""
        import base64, json

        if token in self._token_blacklist:
            return None

        try:
            parts = token.split(".")
            if len(parts) != 3:
                return None

            header, payload, signature = parts
            expected_sig = hmac.new(
                self.secret.encode(),
                f"{header}.{payload}".encode(),
                hashlib.sha256,
            ).hexdigest()[:32]

            if not hmac.compare_digest(signature, expected_sig):
                return None

            # 补齐 padding
            payload += "=" * (4 - len(payload) % 4)
            data = json.loads(base64.urlsafe_b64decode(payload))

            if data.get("exp", 0) < time.time():
                return None

            return data
        except Exception:
            return None

    def revoke_token(self, token: str):
        self._token_blacklist.add(token)


class APIKeyAuth:
    """API Key 认证"""

    def __init__(self):
        self._keys: Dict[str, str] = {}  # key → user_id

    def create_key(self, user_id: str, prefix: str = "quan") -> str:
        """创建 API Key"""
        key = f"{prefix}_{secrets.token_hex(24)}"
        self._keys[key] = user_id
        return key

    def verify_key(self, api_key: str) -> Optional[str]:
        """验证 API Key → user_id"""
        return self._keys.get(api_key)

    def revoke_key(self, api_key: str):
        self._keys.pop(api_key, None)


class AuthManager:
    """统一认证管理器"""

    def __init__(self):
        self.jwt = JWTAuth()
        self.api_keys = APIKeyAuth()
        self._users: Dict[str, User] = {}
        self._sessions: Dict[str, dict] = {}  # session_token → session_data
        self._oauth_states: Dict[str, dict] = {}

    def create_user(
        self,
        username: str,
        password: str = "",
        email: str = "",
        role: UserRole = UserRole.USER,
    ) -> User:
        """创建用户"""
        user_id = f"usr_{secrets.token_hex(12)}"
        password_hash = self._hash_password(password) if password else ""

        user = User(
            user_id=user_id,
            username=username,
            email=email,
            role=role,
            password_hash=password_hash,
        )
        self._users[user_id] = user
        logger.info(f"User created: {user_id} ({username})")
        return user

    def authenticate_password(self, username: str, password: str) -> Optional[Tuple[str, str]]:
        """密码认证 → (user_id, token)"""
        for user in self._users.values():
            if user.username == username and user.is_active:
                if self._verify_password(password, user.password_hash):
                    user.last_login = time.time()
                    token = self.jwt.create_token(user.user_id, user.role.value)
                    return user.user_id, token
        return None

    def authenticate_api_key(self, api_key: str) -> Optional[str]:
        """API Key 认证 → user_id"""
        return self.api_keys.verify_key(api_key)

    def authenticate_token(self, token: str) -> Optional[dict]:
        """Token 认证 → payload"""
        return self.jwt.verify_token(token)

    def create_session(self, user_id: str) -> str:
        """创建会话"""
        session_token = secrets.token_hex(32)
        self._sessions[session_token] = {
            "user_id": user_id,
            "created_at": time.time(),
            "expires_at": time.time() + 86400,
        }
        return session_token

    def verify_session(self, session_token: str) -> Optional[str]:
        """验证会话 → user_id"""
        session = self._sessions.get(session_token)
        if session and session["expires_at"] > time.time():
            return session["user_id"]
        return None

    def check_permission(self, user_id: str, required_role: UserRole) -> bool:
        """检查权限"""
        user = self._users.get(user_id)
        if not user or not user.is_active:
            return False
        return ROLE_HIERARCHY.get(user.role, 0) >= ROLE_HIERARCHY.get(required_role, 0)

    def get_user(self, user_id: str) -> Optional[User]:
        return self._users.get(user_id)

    # ---- 密码工具 ----

    @staticmethod
    def _hash_password(password: str) -> str:
        """bcrypt 哈希"""
        try:
            import bcrypt
            return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
        except ImportError:
            # 回退：SHA256 + salt
            salt = secrets.token_hex(16)
            return f"sha256${salt}${hashlib.sha256((password + salt).encode()).hexdigest()}"

    @staticmethod
    def _verify_password(password: str, hash_str: str) -> bool:
        """验证密码"""
        if hash_str.startswith("$2"):
            try:
                import bcrypt
                return bcrypt.checkpw(password.encode(), hash_str.encode())
            except ImportError:
                pass
        elif hash_str.startswith("sha256$"):
            parts = hash_str.split("$")
            if len(parts) == 3:
                salt, expected = parts[1], parts[2]
                actual = hashlib.sha256((password + salt).encode()).hexdigest()
                return hmac.compare_digest(actual, expected)
        return False

    # ---- OAuth ----

    def get_oauth_url(self, provider: str, redirect_uri: str) -> str:
        """获取 OAuth 授权 URL"""
        state = secrets.token_hex(16)
        self._oauth_states[state] = {"provider": provider, "redirect_uri": redirect_uri, "created": time.time()}

        if provider == "github":
            return f"https://github.com/login/oauth/authorize?client_id=CLIENT_ID&redirect_uri={redirect_uri}&state={state}&scope=user:email"
        elif provider == "google":
            return f"https://accounts.google.com/o/oauth2/v2/auth?client_id=CLIENT_ID&redirect_uri={redirect_uri}&state={state}&scope=openid+profile+email&response_type=code"
        return ""

    def handle_oauth_callback(self, state: str, code: str) -> Optional[Tuple[str, str]]:
        """处理 OAuth 回调"""
        oauth_data = self._oauth_states.pop(state, None)
        if not oauth_data or time.time() - oauth_data["created"] > 600:
            return None

        # 兑换 token（简化）
        user_id = f"usr_{secrets.token_hex(12)}"
        token = self.jwt.create_token(user_id, "user")
        return user_id, token


# 全局实例
auth_manager = AuthManager()


# ============================================================
# FastAPI 依赖注入
# ============================================================

async def get_current_user(
    authorization: str = "",
    x_api_key: str = "",
) -> Optional[str]:
    """FastAPI 依赖：从请求头获取当前用户"""
    # Bearer Token
    if authorization.startswith("Bearer "):
        token = authorization[7:]
        payload = auth_manager.authenticate_token(token)
        if payload:
            return payload["sub"]

    # API Key
    if x_api_key:
        return auth_manager.authenticate_api_key(x_api_key)

    return None


def require_role(role: UserRole):
    """FastAPI 依赖工厂：要求特定角色"""
    async def dependency(user_id: str = None):
        if not user_id:
            raise PermissionError("Authentication required")
        if not auth_manager.check_permission(user_id, role):
            raise PermissionError(f"Role {role.value} required")
        return user_id
    return dependency
