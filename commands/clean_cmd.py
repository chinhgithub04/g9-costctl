"""clean — (stretch) bulk terminate resources matching a tag.

WARNING — DESIGN-FOR-SAFETY
---------------------------
This is the most dangerous command in the CLI. Get the contract right:

  1. DEFAULT IS DRY-RUN. Without --apply the command MUST NOT touch resources.
     It only lists what WOULD be deleted.
  2. Even with --apply, you should consider printing a summary count first
     ("about to terminate N EC2 + M volumes — proceed?"), though for this
     starter a hard `--apply` flag is enough.
  3. Never use this with a tag you don't fully own. Reflection prompt in
     README covers the blast-radius scenario.

WHAT YOU MUST BUILD
-------------------
1. `_find_targets(tag_key, tag_val)` — return a dict like:
     {"ec2": [<instance ids in non-terminal state>],
      "volume": [<volume ids in 'available' state only>]}
   Skip terminated/shutting-down instances (already gone).
   Skip in-use volumes (can't delete while attached — would error anyway).

2. `run(args)` — call _find_targets, print the plan, then either:
     - bail with "(dry-run — pass --apply to ...)"  (default)
     - or actually terminate (when --apply)

HELPERS YOU CAN USE
-------------------
From commands._common:
  parse_kv(s) -> (k, v)

AWS APIS YOU'LL NEED
--------------------
- ec2.describe_instances() + describe_volumes() — same as list_cmd
- ec2.terminate_instances(InstanceIds=[...])
- ec2.delete_volume(VolumeId=...)  (per volume, no bulk API)

VERIFY
------
    pytest tests/test_clean.py -v
"""
import boto3

from commands._common import parse_kv, tags_to_dict


def _find_targets(tag_key, tag_val):
    """Return {"ec2": [...], "volume": [...]} matching tag in non-terminal state."""
    ec2 = boto3.client("ec2")
    
    # Find EC2 instances
    ec2_targets = []
    inst_paginator = ec2.get_paginator("describe_instances")
    for page in inst_paginator.paginate():
        for reservation in page.get("Reservations", []):
            for instance in reservation.get("Instances", []):
                state = instance["State"]["Name"]
                if state in ("shutting-down", "terminated"):
                    continue
                tags = tags_to_dict(instance.get("Tags", []))
                if tags.get(tag_key) == tag_val:
                    ec2_targets.append(instance["InstanceId"])
                    
    # Find EBS volumes
    vol_targets = []
    vol_paginator = ec2.get_paginator("describe_volumes")
    for page in vol_paginator.paginate():
        for vol in page.get("Volumes", []):
            state = vol["State"]
            if state != "available":
                continue
            tags = tags_to_dict(vol.get("Tags", []))
            if tags.get(tag_key) == tag_val:
                vol_targets.append(vol["VolumeId"])
                
    return {"ec2": ec2_targets, "volume": vol_targets}


def run(args):
    """Entry point.

    Args set by argparse:
        args.tag    — "key=value" string (REQUIRED)
        args.apply  — bool, must be True to actually delete (default False = dry-run)
    """
    from botocore.exceptions import ClientError
    tag_key, tag_val = parse_kv(args.tag)
    
    try:
        targets = _find_targets(tag_key, tag_val)
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "Unknown")
        msg = e.response.get("Error", {}).get("Message", str(e))
        print(f"AWS error [{code}]: {msg}")
        return

    if not targets["ec2"] and not targets["volume"]:
        print("Nothing to clean.")
        return
        
    if targets["ec2"]:
        print(f"EC2 instances to terminate: {', '.join(targets['ec2'])}")
    if targets["volume"]:
        print(f"EBS volumes to delete: {', '.join(targets['volume'])}")
        
    if not args.apply:
        print(f"Plan summary: {len(targets['ec2'])} EC2 instance(s), {len(targets['volume'])} volume(s) to clean.")
        print("This is a dry-run. Pass --apply to actually delete.")
        return
        
    ec2 = boto3.client("ec2")
    try:
        if targets["ec2"]:
            ec2.terminate_instances(InstanceIds=targets["ec2"])
            print(f"Terminated EC2 instances: {', '.join(targets['ec2'])}")
            
        if targets["volume"]:
            for vol_id in targets["volume"]:
                ec2.delete_volume(VolumeId=vol_id)
            print(f"Deleted EBS volumes: {', '.join(targets['volume'])}")
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "Unknown")
        msg = e.response.get("Error", {}).get("Message", str(e))
        print(f"AWS error [{code}]: {msg}")
