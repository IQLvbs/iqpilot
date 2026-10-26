import signal, subprocess, sys, unittest
from unittest.mock import patch
from tinygrad.runtime.support.compiler_cpu import ClangCompiler

class TestCompilerSignals(unittest.TestCase):
  def test_mask_covers_spawn_and_restores_existing_mask(self):
    for old_mask in (set(), {signal.SIGUSR2}, {signal.SIGINT}):
      for fails in (False, True):
        with self.subTest(old_mask=old_mask, fails=fails):
          events = []
          def mask(how, value):
            events.append((how, value))
            return old_mask
          def compile_child(*args, **kwargs):
            self.assertEqual(events, [(signal.SIG_BLOCK, {signal.SIGUSR2})])
            self.assertNotIn('preexec_fn', kwargs)
            if fails: raise subprocess.CalledProcessError(1, 'clang')
            return b'object'
          with patch('tinygrad.runtime.support.compiler_cpu.sys.platform', 'linux'), \
               patch('tinygrad.runtime.support.compiler_cpu.signal.pthread_sigmask', side_effect=mask), \
               patch('tinygrad.runtime.support.compiler_cpu.subprocess.check_output', side_effect=compile_child):
            compiler = ClangCompiler(['arm64', 'native'])
            if fails:
              with self.assertRaises(subprocess.CalledProcessError): compiler.compile_to_obj('invalid')
            else: self.assertEqual(compiler.compile_to_obj('int x;'), b'object')
          self.assertEqual(events, [(signal.SIG_BLOCK, {signal.SIGUSR2}), (signal.SIG_SETMASK, old_mask)])

  @unittest.skipUnless(sys.platform == 'linux', 'Linux compiler signal inheritance')
  def test_exec_child_inherits_blocked_signal(self):
    check_output = subprocess.check_output
    old_mask = signal.pthread_sigmask(signal.SIG_BLOCK, set())
    def child(*args, **kwargs):
      self.assertNotIn('preexec_fn', kwargs)
      return check_output([sys.executable, '-c',
                           'import signal; print(int(signal.SIGUSR2 in signal.pthread_sigmask(signal.SIG_BLOCK, set())))'])
    with patch('tinygrad.runtime.support.compiler_cpu.subprocess.check_output', side_effect=child):
      self.assertEqual(ClangCompiler(['arm64', 'native']).compile_to_obj(''), b'1\n')
    self.assertEqual(signal.pthread_sigmask(signal.SIG_BLOCK, set()), old_mask)

  def test_non_linux_does_not_change_signal_mask(self):
    with patch('tinygrad.runtime.support.compiler_cpu.sys.platform', 'darwin'), \
         patch('tinygrad.runtime.support.compiler_cpu.signal.pthread_sigmask') as mask, \
         patch('tinygrad.runtime.support.compiler_cpu.subprocess.check_output', return_value=b'object') as child:
      self.assertEqual(ClangCompiler(['arm64', 'native']).compile_to_obj('int x;'), b'object')
    mask.assert_not_called()
    self.assertNotIn('preexec_fn', child.call_args.kwargs)

if __name__ == '__main__': unittest.main()
