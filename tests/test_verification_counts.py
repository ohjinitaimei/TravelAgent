"""TEST ONLY summaries: exit zero cannot turn skipped work into successful checks."""
from pathlib import Path
import sys,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from verification_counts import python_passed,client_passed


class VerificationCountTests(unittest.TestCase):
    def test_python_requires_a_complete_plain_success(self):
        valid='TEST ONLY output\nRan 12 tests in 0.01s\n\nOK\n'
        self.assertEqual(python_passed(valid),12)
        for text in ('OK (skipped=1)','OK (expected failures=1)','FAILED (failures=1)','OK (unexpected successes=1)'):
            with self.subTest(text=text),self.assertRaises(ValueError):python_passed(valid.replace('OK',text))
        for text in ('',valid.replace('12 tests','0 tests'),valid.replace('Ran 12 tests','TEST ONLY 12')):
            with self.assertRaises(ValueError):python_passed(text)

    def test_node_spec_and_tap_require_all_pass_and_no_skips_todos_or_cancellation(self):
        valid='\n'.join('ℹ '+field+' '+str(value) for field,value in [('tests',12),('pass',12),('fail',0),('cancelled',0),('skipped',0),('todo',0)])
        self.assertEqual(client_passed(valid),12);self.assertEqual(client_passed(valid.replace('ℹ','#')),12)
        for field in ('fail','cancelled','skipped','todo'):
            with self.subTest(field=field),self.assertRaises(ValueError):client_passed(valid.replace(field+' 0',field+' 1'))
        for text in (valid.replace('pass 12','pass 11'),valid.replace('ℹ todo 0',''),valid+'\nℹ tests 12',''):
            with self.assertRaises(ValueError):client_passed(text)


if __name__=='__main__':unittest.main()
