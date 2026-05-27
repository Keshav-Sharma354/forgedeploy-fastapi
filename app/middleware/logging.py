import json
import logging
import time
import uuid
from typing import Callable
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

# Standard setup for application logger
logger = logging.getLogger("app")


class JSONFormatter(logging.Formatter):
    """
    Custom logging formatter that outputs log records as structured single-line JSON.
    Extremely useful for production monitoring aggregators like Loki, ELK, or Datadog.
    """
    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "line": record.lineno,
        }
        
        # Inject standard traceback details if an exception is present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
            
        # Merge custom keys passed inside the extra={} dict
        if hasattr(record, "__dict__"):
            for key, val in record.__dict__.items():
                if key not in {
                    "args", "asctime", "created", "exc_info", "exc_text", "filename",
                    "funcName", "levelname", "levelno", "lineno", "module", "msecs",
                    "msg", "name", "pathname", "process", "processName", "relativeCreated",
                    "stack_info", "thread", "threadName"
                }:
                    log_data[key] = val
                    
        return json.dumps(log_data)


def setup_structured_logging(log_level: int = logging.INFO) -> None:
    """Configures the root logger to output structured JSON using the JSONFormatter."""
    # Obtain root logger
    root_logger = logging.getLogger()
    
    # Remove existing handlers to avoid duplicate output formatting
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
        
    # Configure console stream handler
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(JSONFormatter())
    
    root_logger.addHandler(stream_handler)
    root_logger.setLevel(log_level)
    
    # Configure the FastAPI/Uvicorn loggers to use the same formatter
    for logger_name in ("uvicorn", "uvicorn.access", "uvicorn.error", "app"):
        srv_logger = logging.getLogger(logger_name)
        srv_logger.handlers = []
        srv_logger.propagate = True


class StructuredLoggingMiddleware(BaseHTTPMiddleware):
    """
    FastAPI Middleware to intercept requests and emit a structured JSON log
    containing details on execution time, response status, and request source.
    """
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Check for pre-existing Request ID (e.g. from NGINX header)
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        
        # Track latency using high-resolution monotonic timer
        start_time = time.perf_counter()
        
        # Attach request_id to request state so it can be extracted elsewhere if needed
        request.state.request_id = request_id
        
        # Process the request
        try:
            response = await call_next(request)
        except Exception as exc:
            duration = (time.perf_counter() - start_time) * 1000.0
            logger.error(
                f"Unhandled exception while processing request: {str(exc)}",
                exc_info=True,
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "url": str(request.url.path),
                    "client_ip": request.client.host if request.client else "unknown",
                    "status_code": 500,
                    "duration_ms": round(duration, 2),
                }
            )
            raise exc
            
        duration = (time.perf_counter() - start_time) * 1000.0
        
        # Add the Request ID to the outgoing response headers for debugging trace support
        response.headers["X-Request-ID"] = request_id
        
        # Extract headers with safety fallback defaults
        client_ip = request.headers.get("X-Forwarded-For", request.client.host if request.client else "unknown")
        user_agent = request.headers.get("User-Agent", "unknown")
        
        # Exclude high-frequency healthchecks from verbose logging to keep logs clean
        if "/health" not in request.url.path:
            logger.info(
                f"HTTP {request.method} {request.url.path} finished - {response.status_code}",
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "url": str(request.url.path),
                    "query_params": str(request.query_params),
                    "client_ip": client_ip.split(",")[0].strip(), # Get real client if proxy list
                    "status_code": response.status_code,
                    "duration_ms": round(duration, 2),
                    "user_agent": user_agent,
                }
            )
            
        return response
