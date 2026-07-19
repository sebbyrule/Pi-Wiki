---
name: check_homelab_health
description: A diagnostic skill to check the server's OS, disk space, and memory. Use this when the user asks about system health.
---

# Homelab Health Playbook

You have successfully unlocked the diagnostic playbook.
To retrieve the system health metrics, you must execute the provided bash script.

**Execution Step:**
Use your `execute_bash` tool to run the following command exactly as written:
`bash /app/plugins/system_audit/scripts/check_health.sh`

**Analysis Step:**
Once you receive the output from the bash script, analyze the disk usage and memory. If disk space is running out, warn the user. Otherwise, summarize the server health cleanly.
