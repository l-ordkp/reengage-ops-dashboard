"""
Standalone script for daily assignment.
Can be run as:
  - Cloud Run Job (triggered by Cloud Scheduler)
  - Direct CLI: python cron_assignment.py
"""

import json
import sys

from backend.config import FOCUSED_ASSIGNMENT_MODE
from backend.managers.assignment_manager import run_assignment
from backend.managers.focused_assignment_manager import run_focused_assignment
from backend.managers.throughput_notifier import send_yesterday_throughput


def main():
    # Honor the same dispatch as /api/system/run-assignment so this entrypoint
    # can never silently run a different algorithm than the HTTP path
    # (PR #36 review). NOTE: the live Cloud Scheduler POSTs the HTTP endpoint;
    # this script is a standby entrypoint.
    if FOCUSED_ASSIGNMENT_MODE:
        result = run_focused_assignment()
    else:
        result = run_assignment()
    print(json.dumps(result, indent=2, default=str))

    if "error" in result:
        sys.exit(1)

    print(f"\nAssignment complete: {result.get('assigned', 0)} reviews assigned")

    send_yesterday_throughput()

    return result


if __name__ == "__main__":
    main()
