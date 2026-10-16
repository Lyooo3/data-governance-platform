import json
import sys
from .engine import execute

if __name__ == "__main__":
    try:
        result = execute(json.loads(sys.stdin.buffer.read().decode("utf-8")))
        sys.stdout.buffer.write(
            json.dumps(
                {"success": True, "data": result}, ensure_ascii=False, allow_nan=False
            ).encode("utf-8")
        )
    except Exception as error:
        sys.stdout.buffer.write(
            json.dumps(
                {"success": False, "message": str(error)}, ensure_ascii=False
            ).encode("utf-8")
        )
