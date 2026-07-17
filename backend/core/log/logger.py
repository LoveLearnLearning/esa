import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


def setup_logging() -> None:
    log_dir = Path("logs")
    log_dir.mkdir(parents=True, exist_ok=True)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    # 防止重复添加 Handler
    if root_logger.handlers:
        return

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # 终端日志
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)

    # 文件日志
    file_handler = RotatingFileHandler(
        filename=log_dir / "backend.log",
        maxBytes=20 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)

    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)
