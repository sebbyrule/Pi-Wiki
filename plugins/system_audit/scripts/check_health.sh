#!/bin/bash
# A simple health check script that reads container stats
echo "=== HOMELAB HEALTH REPORT ==="
echo "Operating System: $(cat /etc/os-release | grep PRETTY_NAME | cut -d= -f2 | tr -d '\"')"
echo "Architecture: $(uname -m)"
echo "Disk Usage:"
df -h / | awk 'NR==2 {print "Used: " $3 " / " $2 " (" $5 ")"}'
echo "Memory Available:"
free -m | awk 'NR==2 {print $7 " MB"}'
echo "============================="