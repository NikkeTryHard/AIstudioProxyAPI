import datetime
import json
import logging
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional

# Try to import pydantic for serialization fallback
try:
    from pydantic import BaseModel

    HAS_PYDANTIC = True
except ImportError:
    HAS_PYDANTIC = False

logger = logging.getLogger(__name__)


def safe_serialize(obj: Any, depth: int = 0, max_depth: int = 2) -> Any:
    """Safely serialize objects to JSON-compatible format."""
    if depth > max_depth:
        return str(obj)

    try:
        if obj is None:
            return None
        if isinstance(obj, (str, int, float, bool)):
            return obj
        if isinstance(obj, (list, tuple, set)):
            # Limit list size to prevent huge output
            items = list(obj)
            if len(items) > 100:
                return [
                    safe_serialize(item, depth + 1, max_depth) for item in items[:100]
                ] + [f"... ({len(items)-100} more)"]
            return [safe_serialize(item, depth + 1, max_depth) for item in items]

        if isinstance(obj, dict):
            # Mask sensitive keys
            masked_keys = {
                "api_key",
                "password",
                "token",
                "secret",
                "authorization",
                "cookie",
                "key",
            }
            result = {}
            items = list(obj.items())
            is_truncated = False

            if len(items) > 100:
                items = items[:100]
                is_truncated = True

            for k, v in items:
                key_str = str(k)
                if any(sensitive in key_str.lower() for sensitive in masked_keys):
                    result[key_str] = "***MASKED***"
                else:
                    result[key_str] = safe_serialize(v, depth + 1, max_depth)

            if is_truncated:
                result["_truncated"] = f"... ({len(obj)-100} more keys)"
            return result

        if isinstance(obj, datetime.datetime):
            return obj.isoformat()
        if HAS_PYDANTIC and isinstance(obj, BaseModel):
            return safe_serialize(obj.model_dump(), depth, max_depth)

        # Handle bytes
        if isinstance(obj, bytes):
            return f"<bytes len={len(obj)}>"

        # Handle specific complex objects if needed
        if hasattr(obj, "__dict__"):
            return safe_serialize(vars(obj), depth + 1, max_depth)

        return str(obj)
    except Exception:
        return f"<Unserializable: {type(obj).__name__}>"


class ContextLogger:
    def __init__(self, log_dir: str = "logs/errors"):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def _safe_serialize(self, obj: Any, depth: int = 0, max_depth: int = 2) -> Any:
        """Deprecated alias for safe_serialize."""
        return safe_serialize(obj, depth, max_depth)

    def _get_locals_from_traceback(self, tb) -> List[Dict[str, Any]]:
        """Extract local variables from each frame in the traceback."""
        frames = []
        curr = tb
        while curr:
            frame = curr.tb_frame
            local_vars = {}
            # Only capture locals for project files to avoid noise from libraries
            filename = frame.f_code.co_filename
            is_project_file = (
                "site-packages" not in filename and "lib/python" not in filename
            )

            if is_project_file:
                for k, v in frame.f_locals.items():
                    # Skip internal python vars
                    if k.startswith("__"):
                        continue
                    local_vars[k] = safe_serialize(v, max_depth=1)

            frames.append(
                {
                    "function": frame.f_code.co_name,
                    "file": filename,
                    "line": frame.f_lineno,
                    "locals": local_vars
                    if is_project_file
                    else {"<external_lib>": "Locals omitted"},
                }
            )
            curr = curr.tb_next
        return frames

    def capture_exception(
        self,
        exc: Exception,
        request_context: Optional[Dict[str, Any]] = None,
        browser_context: Optional[Dict[str, Any]] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Capture exception context and save to JSON.
        Returns the path to the saved file.
        """
        timestamp = datetime.datetime.now()

        # Get traceback info
        exc_type = type(exc).__name__
        exc_msg = str(exc)
        tb = exc.__traceback__

        stack_trace = "".join(traceback.format_exception(type(exc), exc, tb))
        stack_locals = self._get_locals_from_traceback(tb)

        error_data = {
            "timestamp": timestamp.isoformat(),
            "error_type": exc_type,
            "error_message": exc_msg,
            "location": f"{stack_locals[-1]['file']}:{stack_locals[-1]['line']}"
            if stack_locals
            else "unknown",
            "stack_trace": stack_trace,
            "stack_locals": stack_locals,
            "request_context": safe_serialize(request_context),
            "browser_context": safe_serialize(browser_context),
            "extra_context": safe_serialize(extra),
        }

        # Create filename: YYYY-MM-DD_HH-MM-SS_ErrorType.json
        filename = f"{timestamp.strftime('%Y-%m-%d_%H-%M-%S')}_{exc_type}.json"
        # Sanitize filename to be safe
        safe_filename = "".join(
            c for c in filename if c.isalnum() or c in ("-", "_", ".")
        )

        file_path = self.log_dir / safe_filename

        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(error_data, f, indent=2, ensure_ascii=False)
            return str(file_path)
        except Exception as e:
            logger.error(f"Failed to save error context: {e}")
            return ""


# Global instance
context_logger = ContextLogger()
