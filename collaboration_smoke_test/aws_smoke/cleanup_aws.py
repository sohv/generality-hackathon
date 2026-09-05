"""Terminate only this demo's disposable EC2 instance and remove its security group."""
import json
import subprocess
from datetime import datetime, timezone

from .provision import ACCOUNT, PROFILE, REGION, STATE, aws

def main():
    path = STATE / "deployment.json"
    record = json.loads(path.read_text())
    assert aws("sts", "get-caller-identity")["Account"] == ACCOUNT == record["account"]
    iid = record["instance_id"]
    instance = aws("ec2", "describe-instances", "--instance-ids", iid)["Reservations"][0]["Instances"][0]
    tags = {x["Key"]:x["Value"] for x in instance.get("Tags", [])}
    if instance["State"]["Name"] != "terminated":
        if tags.get("Purpose") != "names-smoke" or tags.get("Name") != record["name"]:
            raise RuntimeError("Refusing to terminate an instance without this demo's exact tags")
        record["termination_request"] = aws("ec2", "terminate-instances", "--instance-ids", iid)
        record["status"] = "shutting-down"
        path.write_text(json.dumps(record, indent=2))
        subprocess.run(["/opt/homebrew/bin/aws", "--profile", PROFILE, "--region", REGION,
                        "ec2", "wait", "instance-terminated", "--instance-ids", iid], check=True)
    record.update(status="terminated", terminated_at=datetime.now(timezone.utc).isoformat())
    try:
        aws("ec2", "delete-security-group", "--group-id", record["security_group_id"])
        record["security_group_deleted"] = True
    except Exception as exc:
        record["security_group_cleanup_error"] = repr(exc)
    path.write_text(json.dumps(record, indent=2))
    print(json.dumps({k:record[k] for k in ("instance_id", "status", "terminated_at")}, indent=2))

if __name__ == "__main__":
    main()
