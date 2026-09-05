"""Create an EC2 host for the text-file-only names demo; keep it running by default."""
import base64
import argparse
import json
import subprocess
import urllib.request
import uuid
from pathlib import Path

from .common import BASE

PROFILE = "hackathon"
REGION = "eu-west-2"
ACCOUNT = "731246410726"
STATE = BASE / "local_state"
USER_DATA = """#!/bin/bash
set -eu
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y docker.io
systemctl enable --now docker
usermod -aG docker ubuntu
docker pull python:3.12-slim@sha256:2c941e860699f878900b0edc2403613c234d4b32eda3cc9fa7036991a2a63c4a
touch /var/tmp/names-smoke-ready
"""

def aws(*args):
    out = subprocess.check_output(["/opt/homebrew/bin/aws", "--profile", PROFILE,
                                   "--region", REGION, "--no-cli-pager", *args,
                                   "--output", "json"], text=True)
    return json.loads(out) if out.strip() else {}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--replace-terminated", action="store_true")
    parser.add_argument("--auto-terminate-minutes", type=int, choices=range(0,1441), default=0,
                        help="Optional shutdown timer; 0 (default) keeps the VM running")
    args = parser.parse_args()
    STATE.mkdir(exist_ok=True)
    path = STATE / "deployment.json"
    assert aws("sts", "get-caller-identity")["Account"] == ACCOUNT
    if path.exists():
        previous = json.loads(path.read_text())
        if not args.replace_terminated or previous.get("status") != "terminated" or not previous.get("security_group_deleted"):
            raise RuntimeError("A deployment exists; only --replace-terminated can replace a fully cleaned-up demo")
        assert previous["account"] == ACCOUNT
        instance = aws("ec2", "describe-instances", "--instance-ids", previous["instance_id"])["Reservations"][0]["Instances"][0]
        if instance["State"]["Name"] != "terminated":
            raise RuntimeError("Previous VM is not terminated")
        archive = STATE / "archive" / previous["instance_id"]
        archive.mkdir(parents=True, exist_ok=True)
        for filename in ("deployment.json", "launch.json", "user-data.sh"):
            item = STATE / filename
            if item.exists():
                item.rename(archive / filename)
    with urllib.request.urlopen("https://checkip.amazonaws.com", timeout=15) as response:
        ip = response.read().decode().strip()
    import ipaddress
    ipaddress.IPv4Address(ip)
    token = uuid.uuid4().hex
    name = "collaboration-names-" + token[:8]
    user_data = USER_DATA
    if args.auto_terminate_minutes:
        user_data = user_data.replace("set -eu\n", f"set -eu\nshutdown -h +{args.auto_terminate_minutes}\n", 1)
    record = {"account": ACCOUNT, "region": REGION, "name": name, "purpose": "text-file-only names smoke",
              "instance_type": "t3.small", "compute_price_usd_per_hour": .0236,
              "root_gib": 20, "auto_terminate_minutes": args.auto_terminate_minutes,
              "keep_running_after_eval": not bool(args.auto_terminate_minutes), "ssh_cidr": ip + "/32",
              "status": "creating", "client_token": token}
    path.write_text(json.dumps(record, indent=2))
    group = aws("ec2", "create-security-group", "--group-name", name,
                "--description", "Temporary names demo SSH from one client only",
                "--vpc-id", "vpc-0c8bdd6242467be0d")["GroupId"]
    record["security_group_id"] = group
    path.write_text(json.dumps(record, indent=2))
    try:
        aws("ec2", "authorize-security-group-ingress", "--group-id", group,
            "--protocol", "tcp", "--port", "22", "--cidr", ip + "/32")
        request = {
            "ImageId": "ami-0224ce6f9504665ee", "InstanceType": "t3.small", "MinCount": 1, "MaxCount": 1,
            "ClientToken": token, "KeyName": "exploitbench-smoke-20260829",
            "NetworkInterfaces": [{"DeviceIndex": 0, "SubnetId": "subnet-0b5d40e5b2eea1a88",
                                   "Groups": [group], "AssociatePublicIpAddress": True,
                                   "DeleteOnTermination": True}],
            "BlockDeviceMappings": [{"DeviceName": "/dev/sda1", "Ebs": {
                "VolumeSize": 20, "VolumeType": "gp3", "Encrypted": True, "DeleteOnTermination": True}}],
            "InstanceInitiatedShutdownBehavior": "terminate" if args.auto_terminate_minutes else "stop",
            "MetadataOptions": {"HttpTokens": "required", "HttpPutResponseHopLimit": 1},
            "CreditSpecification": {"CpuCredits": "standard"},
            "UserData": base64.b64encode(user_data.encode()).decode(),
            "TagSpecifications": [{"ResourceType": "instance", "Tags": [
                {"Key": "Name", "Value": name}, {"Key": "Purpose", "Value": "names-smoke"},
                {"Key": "AutoTerminateMinutes", "Value": str(args.auto_terminate_minutes)}]}],
        }
        (STATE / "launch.json").write_text(json.dumps(request, indent=2))
        (STATE / "user-data.sh").write_text(user_data)
        result = aws("ec2", "run-instances", "--cli-input-json", "file://" + str(STATE / "launch.json"))
        record.update(instance_id=result["Instances"][0]["InstanceId"], status="pending")
    except Exception as exc:
        # Preserve request + idempotency token so uncertain launches can be checked.
        record.update(status="launch_error", error=repr(exc))
        raise
    finally:
        path.write_text(json.dumps(record, indent=2))
    print(json.dumps(record, indent=2))

if __name__ == "__main__":
    main()
