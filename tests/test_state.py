import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from rizzler.state import LiveSession,Phase

class StateTests(unittest.TestCase):
    def test_session_lifecycle(self):
        s=LiveSession();g=s.start_speech()
        self.assertTrue(s.current(g))
        s.transition(Phase.TRANSCRIBING);s.transition(Phase.THINKING);s.transition(Phase.SPEAKING)
        s.transition(Phase.LISTENING);self.assertEqual(s.phase,Phase.LISTENING)
        s.close();self.assertEqual(s.phase,Phase.CLOSED)
    def test_stale_generation_rejected(self):
        s=LiveSession();g=s.start_speech();s.transition(Phase.TRANSCRIBING)
        s.interrupt();self.assertFalse(s.current(g))
    def test_cannot_resume_closed_session(self):
        s=LiveSession();s.close()
        with self.assertRaises(ValueError):s.start_speech()
    def test_bad_phase_transition_fails(self):
        s=LiveSession()
        with self.assertRaises(ValueError):s.transition(Phase.SPEAKING)
