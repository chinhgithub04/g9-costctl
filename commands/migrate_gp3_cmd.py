"""migrate-gp3 — (stretch) plan or apply gp2 → gp3 EBS migration.

WHY THIS MATTERS
----------------
gp3 is cheaper than gp2 ($0.08 vs $0.10 per GB-month) AND faster
(3000 IOPS baseline vs 3 IOPS/GB scaling). Most gp2 volumes should migrate.
EBS supports live modification — no downtime, no detach.

WHAT YOU MUST BUILD
-------------------
1. Dry-run mode (default):
   - List all gp2 volumes in the account
   - Show size, attached instance, and projected monthly savings per volume
   - Print total savings if all migrated

2. Apply mode (--apply):
   - With --volume-id: migrate just that one
   - Without --volume-id: migrate ALL gp2 volumes
   - Use ec2.modify_volume(...) — the modification runs in the background

AWS APIS YOU'LL NEED
--------------------
ec2.describe_volumes(Filters=[{"Name": "volume-type", "Values": ["gp2"]}])
ec2.modify_volume(
    VolumeId=vid,
    VolumeType="gp3",
    Iops=3000,        # baseline included free
    Throughput=125,   # baseline included free
)

After calling modify_volume, the volume goes through state transitions:
    in-use → modifying → optimizing → in-use (now gp3)
The app stays online throughout. Optimization takes ~30 min for a 100GB
volume; longer for larger volumes.

EXPECTED OUTPUT FORMAT (dry-run)
--------------------------------
    gp2 volumes (price delta $0.020/GB-month):
    ------------------------------------------------------------------------------
      vol-0abc123def456789a    100GB  attached=i-0aaa            $2.00/mo savings
      vol-0bbb456ef789012345     50GB  attached=(none)            $1.00/mo savings
    ------------------------------------------------------------------------------

    (dry-run — pass --apply --volume-id <id> to migrate one, or --apply to migrate ALL)

EXPECTED OUTPUT FORMAT (apply)
------------------------------
      → modify_volume issued for vol-0abc123def456789a (gp3, 3000 IOPS, 125 MiB/s)

    Volume(s) entering 'modifying' → 'optimizing' state. App stays online.
    Use `costctl list volume` after ~30 minutes to confirm 'in-use' + gp3.

VERIFY MANUALLY (no test file for this command)
-----------------------------------------------
    ./costctl.py migrate-gp3                           # dry-run, no side effects
    ./costctl.py migrate-gp3 --apply --volume-id vol-xxx  # migrate ONE

Pick a small volume first. Confirm via:
    ./costctl.py list volume --tag <something>
or AWS Console → EC2 → Volumes.

PRICING NOTE
------------
Constants below assume us-east-1 on-demand pricing. If your account is in
a different region, the dollar figure displayed is rough — but the migration
itself works the same anywhere.
"""
import boto3

# us-east-1 on-demand pricing per GB-month. Override if you care about exact $.
GP2_PRICE = 0.10
GP3_PRICE = 0.08


def run(args):
    """Entry point.

    Args set by argparse:
        args.apply       — bool, default False (dry-run)
        args.volume_id   — optional str, only migrate this volume when --apply
    """
    from botocore.exceptions import ClientError
    
    ec2 = boto3.client("ec2")
    
    try:
        # Find all gp2 volumes for either dry-run reporting or bulk-migration gathering
        paginator = ec2.get_paginator("describe_volumes")
        gp2_volumes = []
        for page in paginator.paginate(Filters=[{"Name": "volume-type", "Values": ["gp2"]}]):
            gp2_volumes.extend(page.get("Volumes", []))
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "Unknown")
        msg = e.response.get("Error", {}).get("Message", str(e))
        print(f"AWS error [{code}]: {msg}")
        return

    if not args.apply:
        # Dry-run mode
        if not gp2_volumes:
            print("No gp2 volumes found in the account.")
            return

        print("gp2 volumes (price delta $0.020/GB-month):")
        print("-" * 78)
        
        total_savings = 0.0
        for vol in gp2_volumes:
            vid = vol["VolumeId"]
            size = vol["Size"]
            attachments = vol.get("Attachments", [])
            attached = attachments[0]["InstanceId"] if attachments else "(none)"
            
            savings = size * (GP2_PRICE - GP3_PRICE)
            total_savings += savings
            
            size_str = f"{size}GB"
            attached_str = f"attached={attached}"
            savings_str = f"${savings:.2f}/mo savings"
            
            print(f"  {vid:<22}{size_str:>8}  {attached_str:<25}{savings_str}")
            
        print("-" * 78)
        print(f"Total projected monthly savings if all migrated: ${total_savings:.2f}")
        print()
        print("(dry-run — pass --apply --volume-id <id> to migrate one, or --apply to migrate ALL)")
        return

    # Apply mode
    vids_to_migrate = []
    if args.volume_id:
        vids_to_migrate = [args.volume_id]
    else:
        vids_to_migrate = [vol["VolumeId"] for vol in gp2_volumes]

    if not vids_to_migrate:
        print("No gp2 volumes found to migrate.")
        return

    # Perform modification
    success_count = 0
    for vid in vids_to_migrate:
        try:
            ec2.modify_volume(
                VolumeId=vid,
                VolumeType="gp3",
                Iops=3000,
                Throughput=125,
            )
            print(f"  → modify_volume issued for {vid} (gp3, 3000 IOPS, 125 MiB/s)")
            success_count += 1
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "Unknown")
            msg = e.response.get("Error", {}).get("Message", str(e))
            print(f"Failed to modify volume {vid}: AWS error [{code}]: {msg}")

    if success_count > 0:
        print()
        print("Volume(s) entering 'modifying' → 'optimizing' state. App stays online.")
        print("Use `costctl list volume` after ~30 minutes to confirm 'in-use' + gp3.")
