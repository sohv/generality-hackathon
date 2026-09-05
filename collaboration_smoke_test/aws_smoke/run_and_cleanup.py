"""Legacy entry point: honor the recorded VM's current keep-running policy."""
import json
import traceback
from .cleanup_aws import main as cleanup
from .provision import STATE
from .run_names import main as run


if __name__ == "__main__":
    try:
        run()
    except Exception:
        traceback.print_exc()
        raise
    finally:
        record = json.loads((STATE / "deployment.json").read_text())
        if record.get("keep_running_after_eval"):
            print(f"Leaving AWS VM {record['instance_id']} running as requested.", flush=True)
        else:
            cleanup()
