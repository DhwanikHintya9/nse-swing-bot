import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from nse_swing_bot.events.stage3c_adapter import (
    migrate_stage3c_files,
    write_stage3c_migration_snapshot,
)
