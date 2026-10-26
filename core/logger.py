import logging
import logging.handlers

from opentelemetry import trace

from .config import LogConfig, auto_path


class TraceContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        span_context = trace.get_current_span().get_span_context()
        record.trace_id = (
            format(span_context.trace_id, "032x") if span_context.is_valid else "-"
        )
        return True


def setup_logger(conf: LogConfig):

    root = logging.getLogger()
    root.setLevel(logging.WARNING)

    root.handlers.clear()

    handler = logging.handlers.TimedRotatingFileHandler(
        filename=auto_path(conf.path),
        when="midnight",
        interval=1,
        backupCount=conf.backup_count,
        encoding="utf-8",
        delay=False,
    )

    formatter = logging.Formatter(
        "%(asctime)s|%(levelname)-5s|%(trace_id)s|%(message)s"
    )
    handler.setFormatter(formatter)
    handler.addFilter(TraceContextFilter())
    root.addHandler(handler)

    logging.getLogger("rag").setLevel(conf.level_int)
