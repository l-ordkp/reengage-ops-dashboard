"""
Standalone script for daily assignment.
Can be run as:
  - Cloud Run Job (triggered by Cloud Scheduler)
  - Direct CLI: python cron_assignment.py
"""

import json
import sys

from backend.managers.assignment_manager import run_assignment


def main():
    result = run_assignment()
    print(json.dumps(result, indent=2, default=str))

    if "error" in result:
        sys.exit(1)

    print(f"\nAssignment complete: {result.get('assigned', 0)} reviews assigned")
    return result


if __name__ == "__main__":
    main()
