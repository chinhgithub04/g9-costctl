"""list — list AWS resources by type, filter by tag / missing-tag.

WHAT YOU MUST BUILD
-------------------
Support 4 resource types: ec2, rds, s3, volume.
Each takes:
- `want` — list of (key, value) tag pairs the resource MUST have
- `missing` — list of tag keys the resource MUST NOT have

Print a formatted table to stdout. Test cases are in tests/test_list.py.

HELPERS YOU CAN USE
-------------------
From commands._common:
  parse_kv(s) -> (k, v)            # "Owner=alice" -> ("Owner", "alice")
  tags_to_dict(items) -> dict       # boto3 [{"Key","Value"}] -> {k: v}
  tags_match(tags, want, missing) -> bool

AWS APIS YOU'LL NEED
--------------------
- EC2: ec2.describe_instances() with get_paginator
- RDS: rds.describe_db_instances(), then list_tags_for_resource(ResourceName=arn)
- S3:  s3.list_buckets(), then get_bucket_tagging(Bucket=name)
       (catch ClientError when bucket has no tagging config — treat as {})
- EBS: ec2.describe_volumes() with get_paginator

EXPECTED OUTPUT FORMAT (when run from CLI)
------------------------------------------
    EC2 Environment=dev — 1 found:
    ------------------------------------------------------------------------------
      i-0abc123def456789a       t3.micro       running       Environment=dev

VERIFY
------
    pytest tests/test_list.py -v
"""
import boto3

from commands._common import parse_kv, tags_to_dict, tags_match


def _list_ec2(want, missing):
    """List EC2 instances matching tag filters.

    Args:
        want: list of (key, value) tag pairs that must all match
        missing: list of tag keys that must NOT be present

    Returns:
        list of (instance_id, instance_type, state, tags_dict) tuples
    """
    ec2 = boto3.client("ec2")
    paginator = ec2.get_paginator("describe_instances")
    results = []
    for page in paginator.paginate():
        for reservation in page.get("Reservations", []):
            for instance in reservation.get("Instances", []):
                tags_dict = tags_to_dict(instance.get("Tags", []))
                if tags_match(tags_dict, want, missing):
                    results.append((
                        instance["InstanceId"],
                        instance["InstanceType"],
                        instance["State"]["Name"],
                        tags_dict
                    ))
    return results


def _list_rds(want, missing):
    """Same shape as _list_ec2 but for RDS DB instances.

    Note: RDS tags require a separate API call per DB:
        rds.list_tags_for_resource(ResourceName=db['DBInstanceArn'])

    Returns:
        list of (db_id, db_class, db_status, tags_dict) tuples
    """
    rds = boto3.client("rds")
    paginator = rds.get_paginator("describe_db_instances")
    results = []
    for page in paginator.paginate():
        for db in page.get("DBInstances", []):
            arn = db["DBInstanceArn"]
            tag_resp = rds.list_tags_for_resource(ResourceName=arn)
            tags_dict = tags_to_dict(tag_resp.get("TagList", []))
            if tags_match(tags_dict, want, missing):
                results.append((
                    db["DBInstanceIdentifier"],
                    db["DBInstanceClass"],
                    db["DBInstanceStatus"],
                    tags_dict
                ))
    return results


def _list_s3(want, missing):
    """List S3 buckets matching tag filters.

    Note: get_bucket_tagging raises ClientError if no tagging config exists
    for that bucket. Treat that as an empty tags dict, not an error.

    Returns:
        list of (bucket_name, "bucket", "active", tags_dict) tuples
    """
    from botocore.exceptions import ClientError
    s3 = boto3.client("s3")
    results = []
    resp = s3.list_buckets()
    for bucket in resp.get("Buckets", []):
        name = bucket["Name"]
        tags_dict = {}
        try:
            tagging = s3.get_bucket_tagging(Bucket=name)
            tags_dict = tags_to_dict(tagging.get("TagSet", []))
        except ClientError:
            tags_dict = {}
        
        if tags_match(tags_dict, want, missing):
            results.append((
                name,
                "bucket",
                "active",
                tags_dict
            ))
    return results


def _list_volume(want, missing):
    """List EBS volumes matching tag filters.

    Returns:
        list of (volume_id, "<type>-<size>GB", state, tags_dict) tuples
        e.g. ("vol-0abc", "gp2-100GB", "in-use", {"purpose": "practice"})
    """
    ec2 = boto3.client("ec2")
    paginator = ec2.get_paginator("describe_volumes")
    results = []
    for page in paginator.paginate():
        for vol in page.get("Volumes", []):
            tags_dict = tags_to_dict(vol.get("Tags", []))
            if tags_match(tags_dict, want, missing):
                type_size = f"{vol.get('VolumeType', '')}-{vol.get('Size', '')}GB"
                results.append((
                    vol["VolumeId"],
                    type_size,
                    vol["State"],
                    tags_dict
                ))
    return results


DISPATCH = {
    "ec2": _list_ec2,
    "rds": _list_rds,
    "s3": _list_s3,
    "volume": _list_volume,
}


def run(args):
    """Entry point called by costctl.py.

    Steps you should perform:
      1. Convert args.tag (list of "k=v" strings) → want pairs via parse_kv
      2. Use args.missing_tag (list of keys) as-is
      3. Call DISPATCH[args.type](want, missing) → rows
      4. Print a header line, separator, then one row per resource

    Args set by argparse:
        args.type         — one of "ec2", "rds", "s3", "volume"
        args.tag          — list[str], each "key=value"
        args.missing_tag  — list[str], each "key"
    """
    want = [parse_kv(t) for t in args.tag]
    missing = args.missing_tag or []

    rows = DISPATCH[args.type](want, missing)

    filters = []
    for t in args.tag:
        filters.append(t)
    for m in args.missing_tag:
        filters.append(f"missing:{m}")

    filter_desc = " ".join(filters) if filters else "(no filter)"
    
    print(f"{args.type.upper()} {filter_desc} — {len(rows)} found:")
    print("-" * 78)

    for r in rows:
        tags_dict = r[3]
        if tags_dict:
            tags_str = " ".join(f"{k}={v}" for k, v in sorted(tags_dict.items()))
        else:
            tags_str = "(no tags)"
        print(f"  {r[0]}       {r[1]}       {r[2]}       {tags_str}")
