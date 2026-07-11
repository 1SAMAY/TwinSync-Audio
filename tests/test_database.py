import tempfile
import unittest
from pathlib import Path

from twinsync_backend.database import TwinSyncDatabase, default_profile


class DatabaseTests(unittest.TestCase):
    def test_settings_profiles_and_events_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            db = TwinSyncDatabase(Path(temp) / "twinsync.sqlite3")
            db.set_setting("automatic_reconnect", True)
            self.assertTrue(db.get_setting("automatic_reconnect"))

            profile = default_profile()
            profile.name = "Living Room"
            profile_id = db.save_profile(profile)
            self.assertGreater(profile_id, 0)
            self.assertEqual(db.get_profile(profile_id).name, "Living Room")
            self.assertEqual(db.list_profiles()[0]["name"], "Living Room")

            db.log_event("test", "Saved", {"profile_id": profile_id})
            events = db.recent_events()
            self.assertEqual(events[0]["category"], "test")
            self.assertEqual(events[0]["payload"]["profile_id"], profile_id)


if __name__ == "__main__":
    unittest.main()

