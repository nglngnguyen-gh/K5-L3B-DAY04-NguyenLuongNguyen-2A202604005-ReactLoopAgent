"""Tests offline cho các guard bổ sung (retry 429, context, nguồn theo provider)."""
import json
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent import run_agent, SYSTEM_PROMPT, MAX_RATE_LIMITED_ATTEMPTS
from bonus.tools import BonusTools
from status_tools import StatusTools
from test_lab import FakeProvider, tool_call, final


class RetryGuardTests(unittest.TestCase):
    def test_persistent_429_is_capped_and_blocked(self):
        calls = [tool_call(f'c{i}', 'get_vercel_status', '{}') for i in range(6)]
        fake = FakeProvider(calls + [final('Vercel: chưa kiểm tra được do 429.')])
        result = run_agent('x', fake, BonusTools(scenario='rate_limit_always'), max_steps=10)
        self.assertEqual(result['status'], 'completed')
        tools = [t for t in result['trace'] if t['event'] == 'tool' and t['name'] == 'get_vercel_status']
        self.assertEqual(len(tools), MAX_RATE_LIMITED_ATTEMPTS)
        self.assertTrue(any(t['event'] == 'retry_blocked' for t in result['trace']))
        blocked = json.loads(fake.histories[MAX_RATE_LIMITED_ATTEMPTS + 1][-1]['content'])
        self.assertEqual(blocked['error'], 'RETRY_BUDGET_EXHAUSTED')

    def test_429_note_tells_model_attempts_left(self):
        fake = FakeProvider([tool_call('a', 'get_vercel_status', '{}'), tool_call('b', 'get_vercel_status', '{}'), final()])
        run_agent('x', fake, BonusTools(scenario='rate_limit_once'), max_steps=5)
        first = json.loads(fake.histories[1][-1]['content'])
        self.assertIn('agent_note', first)
        self.assertEqual(json.loads(fake.histories[2][-1]['content'])['provider'], 'vercel')


class ContextTests(unittest.TestCase):
    def test_long_noise_list_is_compacted_for_model_only(self):
        fake = FakeProvider([tool_call('a', 'get_vercel_status', '{}'), final()])
        result = run_agent('x', fake, BonusTools(scenario='noisy'), max_steps=3)
        sent = json.loads(fake.histories[1][-1]['content'])
        self.assertLess(len(sent['distractors']), 160)
        self.assertIn('agent_context_note', sent)
        traced = next(t for t in result['trace'] if t['event'] == 'tool')['result']
        self.assertEqual(len(traced['distractors']), 160)

    def test_main_tools_keep_main_prompt(self):
        fake = FakeProvider([final()])
        run_agent('x', fake, StatusTools())
        self.assertEqual(fake.histories[0][0]['content'], SYSTEM_PROMPT)


class PerProviderSourceTests(unittest.TestCase):
    def test_each_provider_needs_its_own_url(self):
        t = BonusTools()
        vercel = t.execute('get_incident_details', {'provider': 'vercel', 'incident_id': 'w661l7k3kf4p'})
        npm = t.execute('get_incident_details', {'provider': 'npm', 'incident_id': 'cc0t2r4403sy'})
        fake = FakeProvider([
            tool_call('a', 'get_incident_details', '{"provider":"vercel","incident_id":"w661l7k3kf4p"}'),
            tool_call('b', 'get_incident_details', '{"provider":"npm","incident_id":"cc0t2r4403sy"}'),
            final('Chỉ có Vercel ' + vercel['url']),
            final('Vercel ' + vercel['url'] + ' và npm ' + npm['url'])])
        result = run_agent('x', fake, BonusTools(), max_steps=6)
        self.assertEqual(result['status'], 'completed')
        event = next(t for t in result['trace'] if t['event'] == 'validation_missing_source')
        self.assertEqual(event['missing_providers'], ['npm'])


if __name__ == '__main__':
    unittest.main()
