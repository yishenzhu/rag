import logging
import logging.handlers
from .config import LogConfig, auto_path


def setup_logger(conf: LogConfig):

    root = logging.getLogger()
    root.setLevel(logging.WARN)

    root.handlers.clear()

    handler = logging.handlers.TimedRotatingFileHandler(
        filename=auto_path(conf.path),
        when="midnight",
        interval=1,
        backupCount=conf.backup_count,
        encoding="utf-8",
        delay=False,
    )

    formatter = logging.Formatter("%(asctime)s|%(levelname)-5s|%(message)s")
    handler.setFormatter(formatter)
    root.addHandler(handler)

    logging.getLogger("rag").setLevel(conf.level_int)
