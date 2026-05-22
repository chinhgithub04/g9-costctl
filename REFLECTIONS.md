# Reflections — costctl (XBrain W6 Side Challenge)

---

## 1. Multi-Account: Running `costctl` against 100 AWS accounts

If we needed to run `costctl` across 100 accounts instead of just one, the main changes would be:

- **Cross-account IAM roles**: Each target account would have a standardized role (e.g., `CostctlReadRole`) that our central account can assume via `sts:AssumeRole`. We would deploy this role consistently using CloudFormation StackSets.
- **Profile or role loop**: The CLI would iterate over a list of account IDs, assume the role for each one, create a new boto3 session with temporary credentials, and run the same command logic.
- **Aggregated output**: Instead of printing to stdout, we would write results to a per-account CSV or JSON file, then merge them into a single report grouped by Account ID. This makes it easier to compare costs and resource counts across the organization.
- **Parallelism**: Running sequentially across 100 accounts would be slow. We would use `concurrent.futures.ThreadPoolExecutor` or run each account as a separate Lambda invocation to speed things up.

---

## 2. `idle` vs Trusted Advisor

Our `idle` command checks a 24-hour CPU window. Trusted Advisor uses 14 days. Each has its place:

- **I would trust `idle` more** for short-lived development or test environments. If someone spins up an EC2 instance for a demo and forgets about it, waiting 14 days for Trusted Advisor to flag it wastes money. A 24-hour check catches it quickly. The configurable `--threshold` and `--hours` flags also let us tune it for different situations (e.g., a 4-hour check during a hackathon).
- **I would trust Trusted Advisor more** for production or periodic workloads. For example, EC2 workers or batch-processing instances may look completely idle in a 24-hour window but still run important weekly or monthly jobs. Trusted Advisor's 14-day window captures those sparse usage patterns and avoids dangerous false positives.

In practice, I think the best approach is to use both: `idle` for quick daily sweeps of dev/staging environments, and Trusted Advisor for steady-state production monitoring.

---

## 3. `clean --apply` blast radius

If someone accidentally ran `clean --tag Environment=dev --apply` in a shared account, the damage could be serious. Things I would want in place beforehand:

- **Multi-tag filtering**: Require at least two tag conditions (e.g., `Team=our-team` AND `Environment=dev`) so you cannot accidentally wipe out another team's dev resources with a single broad tag.
- **IAM permission boundaries**: The executing role should only be allowed to terminate resources that match specific tag conditions. AWS supports tag-based IAM conditions for `ec2:TerminateInstances` and similar actions.
- **Service Control Policies (SCPs)**: At the organization level, SCPs can block termination of resources tagged as critical (e.g., `Protected=true`), regardless of what the local IAM policy allows.
- **Backups**: EBS volumes should have snapshot lifecycle policies (DLM). RDS databases should use automated backups. S3 buckets should have versioning enabled where appropriate. This does not prevent the mistake, but it makes recovery possible.
- **Count threshold warning**: If the clean plan targets more than N resources (say 5), the CLI should print a warning and require extra confirmation, even with `--apply`.

---

## 4. AI assistance

I used AI tools as a pair-programming assistant to speed up writing boilerplate code and looking up specific boto3 API syntax (which can be repetitive and inconsistent across services). The AI was helpful for generating quick first drafts of the stubs.

However, I remained the primary driver and made all key decisions, actively modifying and debugging several critical areas:

- **Output formatting alignment**: The CLI required highly precise output layout. I manually adjusted and padded the string formats (such as column alignment and the 7-space separation in `list_cmd`) to guarantee the printed outputs matched the test expectations and example templates.
- **Safety and edge-case handling**: I carefully reviewed how destructive APIs were handled. For S3 tagging in `tag_cmd.py`, I ensured the logic additive-merged tags instead of performing a complete overwrite. In `clean_cmd.py`, I reinforced filtering to guarantee only non-terminal instances and available volumes are targeted.
- **TDD loop driver**: I managed the test-driven development loop, running `pytest` incrementally and resolving exceptions (such as catching `ClientError` for S3 buckets without active tagging configurations) to make sure every single test successfully passed.

---

## 5. W7 carry-over

Moving into W7 (production-style multi-account), I would keep some commands and restrict others:

- **Keep**:
  - `list` and `cost` — these are read-only and essential for visibility and cost tracking. They would be the first things I run in any new account.
  - `idle` — useful as a scheduled check (cron or Lambda) to generate weekly waste reports. I would pipe the output to Slack or email.
  - `migrate-gp3` — I would keep it with dry-run as default. gp2→gp3 migration is generally safe and saves money, but in production I would still apply it gradually (one volume at a time with `--volume-id`) and monitor the volume modification status before moving to the next one.

- **Drop or heavily restrict**:
  - `terminate` and `clean` — running direct termination commands from a local CLI script is too risky in a shared production environment. I would replace these with a workflow that requires approval (e.g., a Slack bot or a pull-request-based pipeline) so there is an audit trail and a second pair of eyes before anything gets deleted.
