# backend/core/services/password_service.py
import bcrypt


class PasswordService:
    @staticmethod
    def hash_password(plain_password: str) -> str:
        """将明文密码转变成哈希值
        Args:
            plain_password: str => 明文密码

        Returns:
            str                 => 哈希后的密码
        """
        salt = bcrypt.gensalt()
        hashed = bcrypt.hashpw(plain_password.encode("utf-8"), salt)
        return hashed.decode("utf-8")

    @staticmethod
    def verify_password(plain_password: str, hashed_password: str) -> bool:
        """验证密码是不是正确的
        Args:
            plain_password: str  => 用户输入进来的明文密码
            hashed_password: str => 哈希过后的密码

        Returns:
            bool                 => 密码是否一致
        """
        return bcrypt.checkpw(
            plain_password.encode("utf-8"), hashed_password.encode("utf-8")
        )
