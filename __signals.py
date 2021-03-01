"""signals"""


signals_available = False  # pylint: disable=invalid-name
try:
    from blinker import Namespace
    signals_available = True  # pylint: disable=invalid-name
except ImportError:
    class Namespace(object):
        """Namespace"""

        def signal(self, name, doc=None):
            """signal"""
            return _FakeSignal(name, doc)

    class _FakeSignal(object):
        """If blinker is unavailable, create a fake class with the same
        interface that allows sending of signals but will fail with an
        error on anything else.  Instead of doing anything on send, it
        will just ignore the arguments and do nothing instead.
        """

        def __init__(self, name, doc=None):
            self.name = name
            self.__doc__ = doc

        def _fail(self, *args, **kwargs):
            raise RuntimeError('signalling support is unavailable '
                               'because the blinker library is '
                               'not installed.')
        send = lambda *a, **kw: None
        connect = disconnect = has_receivers_for = receivers_for = \
            temporarily_connected_to = connected_to = _fail
        del _fail

# The namespace for code signals.  If you are not Flask code, do
# not put signals in here.  Create your own namespace instead.
_signals = Namespace()

# Core signals.  For usage examples grep the source code or consult
# the API documentation in docs/api.rst as well as docs/signals.rst
request_started = _signals.signal('request-started')
request_finished = _signals.signal('request-finished')
appcontext_pushed = _signals.signal('appcontext-pushed')
request_tearing_down = _signals.signal('request-tearing-down')
appcontext_tearing_down = _signals.signal('appcontext-tearing-down')
appcontext_popped = _signals.signal('appcontext-popped')
got_request_exception = _signals.signal('got-request-exception')
