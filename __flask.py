"""flask"""  # pylint:disable=

import os
import sys
from datetime import timedelta
from functools import update_wrapper
from itertools import chain
from threading import Lock

from werkzeug.datastructures import Headers, ImmutableDict
from werkzeug.exceptions import (BadRequest, BadRequestKeyError, HTTPException,
                                 MethodNotAllowed, default_exceptions, InternalServerError)
from werkzeug.routing import Map, RequestRedirect, Rule

import __cli as cli
import __json
from __compat import integer_types, reraise, string_types, text_type
from __config import Config, ConfigAttribute
from __ctx import AppContext, RequestContext, _AppCtxGlobals
from __globals import _request_ctx_stack, g, request, session
from __helpers import (_endpoint_from_view_func, _PackageBoundObject,
                       find_package, get_debug_flag, get_env,
                       get_flashed_messages, get_load_dotenv,
                       locked_cached_property, url_for)
from __logging import create_logger
from __sessions import SecureCookieSessionInterface
from __signals import (appcontext_tearing_down, request_finished,
                       request_started, request_tearing_down, got_request_exception)
from __templating import (DispatchingJinjaLoader, Environment,
                          _default_template_ctx_processor)
from __wrappers import Request, Response

# a singleton sentinel value for parameter defaults
_sentinel = object()


def setupmethod(f):  # pylint: disable=invalid-name
    """Wraps a method so that it performs a check in debug mode if the
    first request was already handled.
    """

    def wrapper_func(self, *args, **kwargs):
        if self.debug and self._got_first_request:  # pylint: disable=protected-access
            raise AssertionError('A setup function was called after the '
                                 'first request was handled.  This usually indicates a bug '
                                 'in the application where a module was not imported '
                                 'and decorators or other functionality was called too late.\n'
                                 'To fix this make sure to import all your view modules, '
                                 'database models and everything related at a central place '
                                 'before the application starts serving requests.')
        return f(self, *args, **kwargs)
    return update_wrapper(wrapper_func, f)


class Flask(_PackageBoundObject):
    """Flask"""

    response_class = Response

    session_interface = SecureCookieSessionInterface()

    request_class = Request

    app_ctx_globals_class = _AppCtxGlobals

    secret_key = ConfigAttribute('SECRET_KEY')

    testing = ConfigAttribute('TESTING')

    def __init__(
        self,
        import_name,
        static_url_path=None,
        static_folder='static',
        static_host=None,
        host_matching=False,
        subdomain_matching=False,
        template_folder='templates',
        instance_path=None,
        instance_relative_config=False,
        root_path=None
    ):
        _PackageBoundObject.__init__(
            self,
            import_name,
            template_folder=template_folder,
            root_path=root_path
        )

        if static_url_path is not None:
            self.static_url_path = static_url_path

        if static_folder is not None:
            self.static_folder = static_folder

        if instance_path is None:
            instance_path = self.auto_find_instance_path()
        elif not os.path.isabs(instance_path):
            raise ValueError(
                'If an instance path is provided it must be absolute.'
                ' A relative path was given instead.'
            )

        self.instance_path = instance_path

        self.config = self.make_config(instance_relative_config)

        self.view_functions = {}

        self.error_handler_spec = {}

        self.url_build_error_handlers = []

        self.before_request_funcs = {}

        self.before_first_request_funcs = []

        self.after_request_funcs = {}

        self.teardown_request_funcs = {}

        self.teardown_appcontext_funcs = []

        self.url_value_preprocessors = {}

        self.url_default_functions = {}

        self.template_context_processors = {
            None: [_default_template_ctx_processor]
        }

        self.shell_context_processors = []

        self.blueprints = {}
        self._blueprint_order = []

        self.extensions = {}

        self.url_map = Map()

        self.url_map.host_matching = host_matching
        self.subdomain_matching = subdomain_matching

        self._got_first_request = False
        self._before_request_lock = Lock()

        if self.has_static_folder:
            assert bool(
                static_host) == host_matching, 'Invalid static_host/host_matching combination'
            self.add_url_rule(
                self.static_url_path + '/<path:filename>',
                endpoint='static',
                host=static_host,
                view_func=self.send_static_file
            )

        self.cli = cli.AppGroup(self.name)

    default_config = ImmutableDict({
        'ENV': None,
        'DEBUG': None,
        'TESTING': False,
        'PROPAGATE_EXCEPTIONS': None,
        'PRESERVE_CONTEXT_ON_EXCEPTION': None,
        'SECRET_KEY': None,
        'PERMANENT_SESSION_LIFETIME': timedelta(days=31),
        'USE_X_SENDFILE': False,
        'SERVER_NAME': None,
        'APPLICATION_ROOT': '/',
        'SESSION_COOKIE_NAME': 'session',
        'SESSION_COOKIE_DOMAIN': None,
        'SESSION_COOKIE_PATH': None,
        'SESSION_COOKIE_HTTPONLY': True,
        'SESSION_COOKIE_SECURE': False,
        'SESSION_COOKIE_SAMESITE': None,
        'SESSION_REFRESH_EACH_REQUEST': True,
        'MAX_CONTENT_LENGTH': None,
        'SEND_FILE_MAX_AGE_DEFAULT': timedelta(hours=12),
        'TRAP_BAD_REQUEST_ERRORS': None,
        'TRAP_HTTP_EXCEPTIONS': False,
        'EXPLAIN_TEMPLATE_LOADING': False,
        'PREFERRED_URL_SCHEME': 'http',
        'JSON_AS_ASCII': True,
        'JSON_SORT_KEYS': True,
        'JSONIFY_PRETTYPRINT_REGULAR': False,
        'JSONIFY_MIMETYPE': 'application/json',
        'TEMPLATES_AUTO_RELOAD': None,
        'MAX_COOKIE_SIZE': 4093,
    })

    url_rule_class = Rule

    env = ConfigAttribute('ENV')

    jinja_environment = Environment

    config_class = Config

    jinja_options = ImmutableDict(
        extensions=['jinja2.ext.autoescape', 'jinja2.ext.with_']
    )

    def _get_templates_auto_reload(self):
        """Reload templates when they are changed.
        """
        rv = self.config['TEMPLATES_AUTO_RELOAD']  # pylint: disable=invalid-name
        return rv if rv is not None else self.debug

    def _set_templates_auto_reload(self, value):
        self.config['TEMPLATES_AUTO_RELOAD'] = value

    templates_auto_reload = property(
        _get_templates_auto_reload, _set_templates_auto_reload
    )
    del _get_templates_auto_reload, _set_templates_auto_reload

    def _get_debug(self):
        return self.config['DEBUG']

    def _set_debug(self, value):
        self.config['DEBUG'] = value
        self.jinja_env.auto_reload = self.templates_auto_reload

    debug = property(_get_debug, _set_debug)
    del _get_debug, _set_debug

    def auto_find_instance_path(self):
        """Tries to locate the instance path if it was not provided to the
        constructor of the application class.  It will basically calculate
        the path to a folder named ``instance`` next to your main file or
        the package.
        """
        prefix, package_path = find_package(self.import_name)
        if prefix is None:
            return os.path.join(package_path, 'instance')
        return os.path.join(prefix, 'var', self.name + '-instance')

    def make_config(self, instance_relative=False):
        """Used to create the config attribute by the Flask constructor.
        The `instance_relative` parameter is passed in from the constructor
        of Flask (there named `instance_relative_config`) and indicates if
        the config should be relative to the instance path or the root path
        of the application.
        """
        root_path = self.root_path
        if instance_relative:
            root_path = self.instance_path
        defaults = dict(self.default_config)
        defaults['ENV'] = get_env()
        defaults['DEBUG'] = get_debug_flag()
        return self.config_class(root_path, defaults)

    @setupmethod
    def add_url_rule(self, rule, endpoint=None, view_func=None,
                     provide_automatic_options=None, **options):
        """Connects a URL rule.  Works exactly like the :meth:`route`
        decorator.  If a view_func is provided it will be registered with the
        endpoint.
        """
        if endpoint is None:
            endpoint = _endpoint_from_view_func(view_func)
        options['endpoint'] = endpoint
        methods = options.pop('methods', None)

        if methods is None:
            methods = getattr(view_func, 'methods', None) or ('GET',)
        if isinstance(methods, string_types):
            raise TypeError('Allowed methods have to be iterables of strings, '
                            'for example: @app.route(..., methods=["POST"])')
        methods = set(item.upper() for item in methods)

        # Methods that should always be added
        required_methods = set(getattr(view_func, 'required_methods', ()))

        # starting with Flask 0.8 the view_func object can disable and
        # force-enable the automatic options handling.
        if provide_automatic_options is None:
            provide_automatic_options = getattr(view_func,
                                                'provide_automatic_options', None)

        if provide_automatic_options is None:
            if 'OPTIONS' not in methods:
                provide_automatic_options = True
                required_methods.add('OPTIONS')
            else:
                provide_automatic_options = False

        # Add the required methods now.
        methods |= required_methods

        rule = self.url_rule_class(rule, methods=methods, **options)
        rule.provide_automatic_options = provide_automatic_options

        self.url_map.add(rule)
        if view_func is not None:
            old_func = self.view_functions.get(endpoint)
            if old_func is not None and old_func != view_func:
                raise AssertionError('View function mapping is overwriting an '
                                     'existing endpoint function: %s' % endpoint)
            self.view_functions[endpoint] = view_func

    @locked_cached_property
    def name(self):
        """The name of the application.  This is usually the import name
        with the difference that it's guessed from the run file if the
        import name is main.  This name is used as a display name when
        Flask needs the name of the application.  It can be set and overridden
        to change the value.
        """
        if self.import_name == '__main__':
            # pylint: disable=invalid-name
            fn = getattr(sys.modules['__main__'], '__file__', None)
            if fn is None:
                return '__main__'
            return os.path.splitext(os.path.basename(fn))[0]
        return self.import_name

    def route(self, rule, **options):
        """A decorator that is used to register a view function for a
        given URL rule.  This does the same thing as :meth:`add_url_rule`
        but is intended for decorator usage::
        """
        def decorator(f):  # pylint: disable=invalid-name
            endpoint = options.pop('endpoint', None)
            self.add_url_rule(rule, endpoint, f, **options)
            return f
        return decorator

    # (__name__, self, host, port, debug, load_dotenv, options) ->
    # < __flask.Flask object at 0x7f8b5d941048 > None 8080 None True {}

    def run(self, host=None, port=None, debug=None,
            load_dotenv=True, **options):
        """Runs the application on a local development server.

        Do not use ``run()`` in a production setting. It is not intended to
        meet security and performance requirements for a production server.
        Instead, see :ref:`deployment` for WSGI server recommendations.

        If the :attr:`debug` flag is set the server will automatically reload
        for code changes and show a debugger in case an exception happened.

        If you want to run the application in debug mode, but disable the
        code execution on the interactive debugger, you can pass
        ``use_evalex=False`` as parameter.  This will keep the debugger's
        traceback screen active, but disable code execution.

        It is not recommended to use this function for development with
        automatic reloading as this is badly supported.  Instead you should
        be using the :command:`flask` command line script's ``run`` support.

        .. admonition:: Keep in Mind

           Flask will suppress any server error with a generic error page
           unless it is in debug mode.  As such to enable just the
           interactive debugger without the code reloading, you have to
           invoke :meth:`run` with ``debug=True`` and ``use_reloader=False``.
           Setting ``use_debugger`` to ``True`` without being in debug mode
           won't catch any exceptions because there won't be any to
           catch.

        :param host: the hostname to listen on. Set this to ``'0.0.0.0'`` to
            have the server available externally as well. Defaults to
            ``'127.0.0.1'`` or the host in the ``SERVER_NAME`` config variable
            if present.
        :param port: the port of the webserver. Defaults to ``5000`` or the
            port defined in the ``SERVER_NAME`` config variable if present.
        :param debug: if given, enable or disable debug mode. See
            :attr:`debug`.
        :param load_dotenv: Load the nearest :file:`.env` and :file:`.flaskenv`
            files to set environment variables. Will also change the working
            directory to the directory containing the first file found.
        :param options: the options to be forwarded to the underlying Werkzeug
            server. See :func:`werkzeug.serving.run_simple` for more
            information.
        """
        # Change this into a no-op if the server is invoked from the
        # command line. Have a look at cli.py for more information.
        # os.environ.get('FLASK_RUN_FROM_CLI') -> None
        if os.environ.get('FLASK_RUN_FROM_CLI') == 'true':
            from __debughelpers import \
                explain_ignored_app_run  # pylint: disable=import-outside-toplevel,relative-beyond-top-level
            explain_ignored_app_run()
            return

        if get_load_dotenv(load_dotenv):  # FLASK_ENV and FLASK_DEBUG is None here
            cli.load_dotenv()

            # if set, let env vars override previous values
            if 'FLASK_ENV' in os.environ:
                self.env = get_env()  # pylint: disable=attribute-defined-outside-init
                self.debug = get_debug_flag()
            elif 'FLASK_DEBUG' in os.environ:
                self.debug = get_debug_flag()

        # debug passed to method overrides all other sources
        if debug is not None:
            self.debug = bool(debug)

        _host = '127.0.0.1'
        _port = 5000
        server_name = self.config.get('SERVER_NAME')
        sn_host, sn_port = None, None

        if server_name:
            sn_host, _, sn_port = server_name.partition(':')

        host = host or sn_host or _host
        port = int(port or sn_port or _port)

        options.setdefault('use_reloader', self.debug)
        options.setdefault('use_debugger', self.debug)
        options.setdefault('threaded', True)

        cli.show_server_banner(self.env, self.debug, self.name, False)

        from werkzeug.serving import \
            run_simple  # pylint: disable=import-outside-toplevel

        try:
            run_simple(host, port, self, **options)
        finally:
            # reset the first request information if the development server
            # reset normally.  This makes it possible to restart the server
            # without reloader and that stuff from an interactive shell.
            self._got_first_request = False

    @locked_cached_property
    def jinja_env(self):
        """The Jinja2 environment used to load templates."""
        return self.create_jinja_environment()

    def create_jinja_environment(self):
        """Creates the Jinja2 environment based on :attr:`jinja_options`
        and :meth:`select_jinja_autoescape`.  Since 0.7 this also adds
        the Jinja2 globals and filters after initialization.  Override
        this function to customize the behavior.
        """
        options = dict(
            self.jinja_options)  # __flask {'extensions': ['jinja2.ext.autoescape', 'jinja2.ext.with_']} # pylint: disable=line-too-long

        if 'autoescape' not in options:
            # __flask {
            #   'extensions': ['jinja2.ext.autoescape', 'jinja2.ext.with_'],
            #   'autoescape': <bound method Flask.select_jinja_autoescape of <__flask.Flask object at 0x7f678c254048>> # pylint: disable=line-too-long
            # }
            options['autoescape'] = self.select_jinja_autoescape

        if 'auto_reload' not in options:
            # __flask {
            #   'extensions': ['jinja2.ext.autoescape', 'jinja2.ext.with_'],
            #   'autoescape': <bound method Flask.select_jinja_autoescape of <__flask.Flask object at 0x7ff85ac0f080>>, # pylint: disable=line-too-long
            #   'auto_reload': True
            # }
            options['auto_reload'] = self.templates_auto_reload
        # __flask <__templating.Environment object at 0x7f08a39b7320>
        # pylint: disable=invalid-name
        rv = self.jinja_environment(self, **options)
        # __flask rv.globals {
        #   'range': <class 'range'>,
        #   'dict': <class 'dict'>,
        #   'lipsum': <function generate_lorem_ipsum at 0x7f425f9bb400>,
        #   'cycler': <class 'jinja2.utils.Cycler'>,
        #   'joiner': <class 'jinja2.utils.Joiner'>,
        #   'namespace': <class 'jinja2.utils.Namespace'>
        # }
        rv.globals.update(
            url_for=url_for,
            get_flashed_messages=get_flashed_messages,
            config=self.config,
            # request, session and g are normally added with the
            # context processor for efficiency reasons but for imported
            # templates we also want the proxies in there.
            request=request,
            session=session,
            g=g
        )
        # __flask {
        #   'range': <class 'range'>,
        #   'dict': <class 'dict'>,
        #   'lipsum': <function generate_lorem_ipsum at 0x7f6f75211400>,
        #   'cycler': <class 'jinja2.utils.Cycler'>,
        #   'joiner': <class 'jinja2.utils.Joiner'>,
        #   'namespace': <class 'jinja2.utils.Namespace'>,
        #   'url_for': <function url_for at 0x7f6f75006048>,
        #   'get_flashed_messages': <function get_flashed_messages at 0x7f6f75003f28>,
        #   'config': <Config {
        #       'ENV': 'production',
        #       'DEBUG': True,
        #       'TESTING': False,
        #       'PROPAGATE_EXCEPTIONS': None,
        #       'PRESERVE_CONTEXT_ON_EXCEPTION': None,
        #       'SECRET_KEY': None,
        #       'PERMANENT_SESSION_LIFETIME': datetime.timedelta(31),
        #       'USE_X_SENDFILE': False,
        #       'SERVER_NAME': None,
        #       'APPLICATION_ROOT': '/',
        #       'SESSION_COOKIE_NAME': 'session',
        #       'SESSION_COOKIE_DOMAIN': None,
        #       'SESSION_COOKIE_PATH': None,
        #       'SESSION_COOKIE_HTTPONLY': True,
        #       'SESSION_COOKIE_SECURE': False,
        #       'SESSION_COOKIE_SAMESITE': None,
        #       'SESSION_REFRESH_EACH_REQUEST': True,
        #       'MAX_CONTENT_LENGTH': None,
        #       'SEND_FILE_MAX_AGE_DEFAULT': datetime.timedelta(0, 43200),
        #       'TRAP_BAD_REQUEST_ERRORS': None,
        #       'TRAP_HTTP_EXCEPTIONS': False,
        #       'EXPLAIN_TEMPLATE_LOADING': False,
        #       'PREFERRED_URL_SCHEME': 'http',
        #       'JSON_AS_ASCII': True,
        #       'JSON_SORT_KEYS': True,
        #       'JSONIFY_PRETTYPRINT_REGULAR': False,
        #       'JSONIFY_MIMETYPE': 'application/json',
        #       'TEMPLATES_AUTO_RELOAD': None,
        #       'MAX_COOKIE_SIZE': 4093
        #   }>,
        #   'request': <LocalProxy unbound>,
        #   'session': <LocalProxy unbound>,
        #   'g': <LocalProxy unbound>
        # }
        rv.filters['tojson'] = __json.tojson_filter  # HACK
        return rv

    def select_jinja_autoescape(self, filename):
        """Returns ``True`` if autoescaping should be active for the given
        template name. If no template name is given, returns `True`.

        .. versionadded:: 0.5
        """
        if filename is None:
            return True
        return filename.endswith(('.html', '.htm', '.xml', '.xhtml'))

    def create_global_jinja_loader(self):
        """Creates the loader for the Jinja2 environment.  Can be used to
        override just the loader and keeping the rest unchanged.  It's
        discouraged to override this function.  Instead one should override
        the :meth:`jinja_loader` function instead.

        The global loader dispatches between the loaders of the application
        and the individual blueprints.

        .. versionadded:: 0.7
        """
        return DispatchingJinjaLoader(self)

    def request_context(self, environ):
        """Create a :class:`~flask.ctx.RequestContext` representing a
        WSGI environment. Use a ``with`` block to push the context,
        which will make :data:`request` point at this request.

        See :doc:`/reqcontext`.

        Typically you should not call this from your own code. A request
        context is automatically pushed by the :meth:`wsgi_app` when
        handling a request. Use :meth:`test_request_context` to create
        an environment and context instead of this method.

        :param environ: a WSGI environment
        """
        return RequestContext(self, environ)

    def try_trigger_before_first_request_functions(self):
        """Called before each request and will ensure that it triggers
        the :attr:`before_first_request_funcs` and only exactly once per
        application instance (which means process usually).

        :internal:
        """
        if self._got_first_request:
            return
        with self._before_request_lock:
            if self._got_first_request:
                return
            for func in self.before_first_request_funcs:
                func()
            self._got_first_request = True

    def preprocess_request(self):
        """Called before the request is dispatched. Calls
        :attr:`url_value_preprocessors` registered with the app and the
        current blueprint (if any). Then calls :attr:`before_request_funcs`
        registered with the app and the blueprint.

        If any :meth:`before_request` handler returns a non-None value, the
        value is handled as if it was the return value from the view, and
        further request handling is stopped.
        """

        bp = _request_ctx_stack.top.request.blueprint  # pylint: disable=invalid-name

        funcs = self.url_value_preprocessors.get(None, ())
        if bp is not None and bp in self.url_value_preprocessors:
            funcs = chain(funcs, self.url_value_preprocessors[bp])
        for func in funcs:
            func(request.endpoint, request.view_args)

        funcs = self.before_request_funcs.get(None, ())
        if bp is not None and bp in self.before_request_funcs:
            funcs = chain(funcs, self.before_request_funcs[bp])
        for func in funcs:
            rv = func()  # pylint: disable=invalid-name
            if rv is not None:
                return rv

    def raise_routing_exception(self, request):  # pylint: disable=redefined-outer-name
        """Exceptions that are recording during routing are reraised with
        this method.  During debug we are not reraising redirect requests
        for non ``GET``, ``HEAD``, or ``OPTIONS`` requests and we're raising
        a different error instead to help debug situations.

        :internal:
        """
        if not self.debug \
           or not isinstance(request.routing_exception, RequestRedirect) \
           or request.method in ('GET', 'HEAD', 'OPTIONS'):
            raise request.routing_exception

        from __debughelpers import \
            FormDataRoutingRedirect  # pylint: disable=import-outside-toplevel
        raise FormDataRoutingRedirect(request)

    def make_default_options_response(self):
        """This method is called to create the default ``OPTIONS`` response.
        This can be changed through subclassing to change the default
        behavior of ``OPTIONS`` responses.

        .. versionadded:: 0.7
        """
        adapter = _request_ctx_stack.top.url_adapter
        if hasattr(adapter, 'allowed_methods'):
            methods = adapter.allowed_methods()
        else:
            # fallback for Werkzeug < 0.7
            methods = []
            try:
                adapter.match(method='--')
            except MethodNotAllowed as e:  # pylint: disable=invalid-name
                methods = e.valid_methods
            except HTTPException as e:  # pylint: disable=invalid-name
                pass
        rv = self.response_class()  # pylint: disable=invalid-name
        rv.allow.update(methods)
        return rv

    def dispatch_request(self):
        """Does the request dispatching.  Matches the URL and returns the
        return value of the view or error handler.  This does not have to
        be a response object.  In order to convert the return value to a
        proper response object, call :func:`make_response`.

        .. versionchanged:: 0.7
           This no longer does the exception handling, this code was
           moved to the new :meth:`full_dispatch_request`.
        """
        req = _request_ctx_stack.top.request
        if req.routing_exception is not None:
            self.raise_routing_exception(req)
        rule = req.url_rule
        # if we provide automatic options for this URL and the
        # request came with the OPTIONS method, reply automatically
        if getattr(rule, 'provide_automatic_options', False) \
           and req.method == 'OPTIONS':
            return self.make_default_options_response()
        # otherwise dispatch to the handler for that endpoint
        return self.view_functions[rule.endpoint](**req.view_args)

    def make_response(self, rv):  # pylint: disable=invalid-name
        """Convert the return value from a view function to an instance of
        :attr:`response_class`.

        :param rv: the return value from the view function. The view function
            must return a response. Returning ``None``, or the view ending
            without returning, is not allowed. The following types are allowed
            for ``view_rv``:

            ``str`` (``unicode`` in Python 2)
                A response object is created with the string encoded to UTF-8
                as the body.

            ``bytes`` (``str`` in Python 2)
                A response object is created with the bytes as the body.

            ``tuple``
                Either ``(body, status, headers)``, ``(body, status)``, or
                ``(body, headers)``, where ``body`` is any of the other types
                allowed here, ``status`` is a string or an integer, and
                ``headers`` is a dictionary or a list of ``(key, value)``
                tuples. If ``body`` is a :attr:`response_class` instance,
                ``status`` overwrites the exiting value and ``headers`` are
                extended.

            :attr:`response_class`
                The object is returned unchanged.

            other :class:`~werkzeug.wrappers.Response` class
                The object is coerced to :attr:`response_class`.

            :func:`callable`
                The function is called as a WSGI application. The result is
                used to create a response object.

        .. versionchanged:: 0.9
           Previously a tuple was interpreted as the arguments for the
           response object.
        """

        status = headers = None

        # unpack tuple returns
        if isinstance(rv, tuple):
            len_rv = len(rv)

            # a 3-tuple is unpacked directly
            if len_rv == 3:
                rv, status, headers = rv
            # decide if a 2-tuple has status or headers
            elif len_rv == 2:
                if isinstance(rv[1], (Headers, dict, tuple, list)):
                    rv, headers = rv
                else:
                    rv, status = rv
            # other sized tuples are not allowed
            else:
                raise TypeError(
                    'The view function did not return a valid response tuple.'
                    ' The tuple must have the form (body, status, headers),'
                    ' (body, status), or (body, headers).'
                )

        # the body must not be None
        if rv is None:
            raise TypeError(
                'The view function did not return a valid response. The'
                ' function either returned None or ended without a return'
                ' statement.'
            )

        # make sure the body is an instance of the response class
        if not isinstance(rv, self.response_class):
            if isinstance(rv, (text_type, bytes, bytearray)):
                # let the response class set the status and headers instead of
                # waiting to do it manually, so that the class can handle any
                # special logic
                rv = self.response_class(rv, status=status, headers=headers)
                status = headers = None
            else:
                # evaluate a WSGI callable, or coerce a different response
                # class to the correct type
                try:
                    rv = self.response_class.force_type(rv, request.environ)
                except TypeError as e:  # pylint: disable=invalid-name
                    new_error = TypeError(
                        '{e}\nThe view function did not return a valid'
                        ' response. The return type must be a string, tuple,'
                        ' Response instance, or WSGI callable, but it was a'
                        ' {rv.__class__.__name__}.'.format(e=e, rv=rv)
                    )
                    reraise(TypeError, new_error, sys.exc_info()[2])

        # prefer the status if it was provided
        if status is not None:
            if isinstance(status, (text_type, bytes, bytearray)):
                rv.status = status
            else:
                rv.status_code = status

        # extend existing headers with provided headers
        if headers:
            rv.headers.extend(headers)

        return rv

    def process_response(self, response):
        """Can be overridden in order to modify the response object
        before it's sent to the WSGI server.  By default this will
        call all the :meth:`after_request` decorated functions.

        .. versionchanged:: 0.5
           As of Flask 0.5 the functions registered for after request
           execution are called in reverse order of registration.

        :param response: a :attr:`response_class` object.
        :return: a new response object or the same, has to be an
                 instance of :attr:`response_class`.
        """
        ctx = _request_ctx_stack.top
        bp = ctx.request.blueprint  # pylint: disable=invalid-name
        funcs = ctx._after_request_functions  # pylint: disable=protected-access
        if bp is not None and bp in self.after_request_funcs:
            funcs = chain(funcs, reversed(self.after_request_funcs[bp]))
        if None in self.after_request_funcs:
            funcs = chain(funcs, reversed(self.after_request_funcs[None]))
        for handler in funcs:
            response = handler(response)
        if not self.session_interface.is_null_session(ctx.session):
            self.session_interface.save_session(self, ctx.session, response)
        return response

    @locked_cached_property
    def logger(self):
        """The ``'flask.app'`` logger, a standard Python
        :class:`~logging.Logger`.

        In debug mode, the logger's :attr:`~logging.Logger.level` will be set
        to :data:`~logging.DEBUG`.

        If there are no handlers configured, a default handler will be added.
        See :ref:`logging` for more information.

        .. versionchanged:: 1.0
            Behavior was simplified. The logger is always named
            ``flask.app``. The level is only set during configuration, it
            doesn't check ``app.debug`` each time. Only one format is used,
            not different ones depending on ``app.debug``. No handlers are
            removed, and a handler is only added if no handlers are already
            configured.

        .. versionadded:: 0.3
        """
        return create_logger(self)

    def log_exception(self, exc_info):
        """Logs an exception.  This is called by :meth:`handle_exception`
        if debugging is disabled and right before the handler is called.
        The default implementation logs the exception as error on the
        :attr:`logger`.

        .. versionadded:: 0.8
        """
        self.logger.error('Exception on %s [%s]' % (  # pylint: disable=no-member
            request.path,
            request.method
        ), exc_info=exc_info)

    def finalize_request(self, rv, from_error_handler=False):  # pylint: disable=invalid-name
        """Given the return value from a view function this finalizes
        the request by converting it into a response and invoking the
        postprocessing functions.  This is invoked for both normal
        request dispatching as well as error handlers.

        Because this means that it might be called as a result of a
        failure a special safe mode is available which can be enabled
        with the `from_error_handler` flag.  If enabled, failures in
        response processing will be logged and otherwise ignored.

        :internal:
        """
        response = self.make_response(rv)
        try:
            response = self.process_response(response)
            request_finished.send(self, response=response)
        except Exception:  # pylint: disable=broad-except
            if not from_error_handler:
                raise
            self.logger.exception('Request finalizing failed with an '  # pylint: disable=no-member
                                  'error while handling an error')
        return response

    def full_dispatch_request(self):
        """Dispatches the request and on top of that performs request
        pre and postprocessing as well as HTTP exception catching and
        error handling.

        .. versionadded:: 0.7
        """
        self.try_trigger_before_first_request_functions()
        try:
            request_started.send(self)
            rv = self.preprocess_request()  # pylint: disable=invalid-name
            if rv is None:
                rv = self.dispatch_request()  # pylint: disable=invalid-name
        except Exception as e:  # pylint: disable=broad-except,invalid-name
            rv = self.handle_user_exception(e)  # pylint: disable=invalid-name
        return self.finalize_request(rv)

    def should_ignore_error(self, error):  # pylint: disable=unused-argument
        """This is called to figure out if an error should be ignored
        or not as far as the teardown system is concerned.  If this
        function returns ``True`` then the teardown handlers will not be
        passed the error.

        .. versionadded:: 0.10
        """
        return False

    @property
    def preserve_context_on_exception(self):
        """Returns the value of the ``PRESERVE_CONTEXT_ON_EXCEPTION``
        configuration value in case it's set, otherwise a sensible default
        is returned.

        .. versionadded:: 0.7
        """
        rv = self.config['PRESERVE_CONTEXT_ON_EXCEPTION']  # pylint: disable=invalid-name
        if rv is not None:
            return rv
        return self.debug

    def create_url_adapter(self, request):  # pylint: disable=redefined-outer-name
        """Creates a URL adapter for the given request. The URL adapter
        is created at a point where the request context is not yet set
        up so the request is passed explicitly.

        .. versionadded:: 0.6

        .. versionchanged:: 0.9
           This can now also be called without a request object when the
           URL adapter is created for the application context.

        .. versionchanged:: 1.0
            :data:`SERVER_NAME` no longer implicitly enables subdomain
            matching. Use :attr:`subdomain_matching` instead.
        """
        if request is not None:
            # If subdomain matching is disabled (the default), use the
            # default subdomain in all cases. This should be the default
            # in Werkzeug but it currently does not have that feature.
            subdomain = ((self.url_map.default_subdomain or None)
                         if not self.subdomain_matching else None)
            return self.url_map.bind_to_environ(
                request.environ,
                server_name=self.config['SERVER_NAME'],
                subdomain=subdomain)
        # We need at the very least the server name to be set for this
        # to work.
        if self.config['SERVER_NAME'] is not None:
            return self.url_map.bind(
                self.config['SERVER_NAME'],
                script_name=self.config['APPLICATION_ROOT'],
                url_scheme=self.config['PREFERRED_URL_SCHEME'])

    @staticmethod
    def _get_exc_class_and_code(exc_class_or_code):
        """Ensure that we register only exceptions as handler keys"""
        if isinstance(exc_class_or_code, integer_types):
            exc_class = default_exceptions[exc_class_or_code]
        else:
            exc_class = exc_class_or_code

        assert issubclass(exc_class, Exception)

        if issubclass(exc_class, HTTPException):
            return exc_class, exc_class.code
        else:
            return exc_class, None

    def _find_error_handler(self, e):  # pylint: disable=invalid-name
        """Return a registered error handler for an exception in this order:
        blueprint handler for a specific code, app handler for a specific code,
        blueprint handler for an exception class, app handler for an exception
        class, or ``None`` if a suitable handler is not found.
        """
        exc_class, code = self._get_exc_class_and_code(type(e))

        for name, c in (  # pylint: disable=invalid-name
            (request.blueprint, code), (None, code),
            (request.blueprint, None), (None, None)
        ):
            handler_map = self.error_handler_spec.setdefault(name, {}).get(c)

            if not handler_map:
                continue

            for cls in exc_class.__mro__:
                handler = handler_map.get(cls)

                if handler is not None:
                    return handler

    def handle_http_exception(self, e):  # pylint: disable=invalid-name
        """Handles an HTTP exception.  By default this will invoke the
        registered error handlers and fall back to returning the
        exception as response.

        .. versionadded:: 0.3
        """
        # Proxy exceptions don't have error codes.  We want to always return
        # those unchanged as errors
        if e.code is None:
            return e

        handler = self._find_error_handler(e)
        if handler is None:
            return e
        return handler(e)

    def trap_http_exception(self, e):  # pylint: disable=invalid-name
        """Checks if an HTTP exception should be trapped or not.  By default
        this will return ``False`` for all exceptions except for a bad request
        key error if ``TRAP_BAD_REQUEST_ERRORS`` is set to ``True``.  It
        also returns ``True`` if ``TRAP_HTTP_EXCEPTIONS`` is set to ``True``.

        This is called for all HTTP exceptions raised by a view function.
        If it returns ``True`` for any exception the error handler for this
        exception is not called and it shows up as regular exception in the
        traceback.  This is helpful for debugging implicitly raised HTTP
        exceptions.

        .. versionchanged:: 1.0
            Bad request errors are not trapped by default in debug mode.

        .. versionadded:: 0.8
        """
        if self.config['TRAP_HTTP_EXCEPTIONS']:
            return True

        trap_bad_request = self.config['TRAP_BAD_REQUEST_ERRORS']

        # if unset, trap key errors in debug mode
        if (
            trap_bad_request is None and self.debug
            and isinstance(e, BadRequestKeyError)
        ):
            return True

        if trap_bad_request:
            return isinstance(e, BadRequest)

        return False

    def handle_user_exception(self, e):  # pylint: disable=invalid-name
        """This method is called whenever an exception occurs that should be
        handled.  A special case are
        :class:`~werkzeug.exception.HTTPException` which are forwarded by
        this function to the :meth:`handle_http_exception` method.  This
        function will either return a response value or reraise the
        exception with the same traceback.

        .. versionchanged:: 1.0
            Key errors raised from request data like ``form`` show the the bad
            key in debug mode rather than a generic bad request message.

        .. versionadded:: 0.7
        """
        exc_type, exc_value, tb = sys.exc_info()  # pylint: disable=invalid-name
        assert exc_value is e
        # ensure not to trash sys.exc_info() at that point in case someone
        # wants the traceback preserved in handle_http_exception.  Of course
        # we cannot prevent users from trashing it themselves in a custom
        # trap_http_exception method so that's their fault then.

        # MultiDict passes the key to the exception, but that's ignored
        # when generating the response message. Set an informative
        # description for key errors in debug mode or when trapping errors.
        if (
            (self.debug or self.config['TRAP_BAD_REQUEST_ERRORS'])
            and isinstance(e, BadRequestKeyError)
            # only set it if it's still the default description
            and e.description is BadRequestKeyError.description
        ):
            e.description = "KeyError: '{0}'".format(*e.args)

        if isinstance(e, HTTPException) and not self.trap_http_exception(e):
            return self.handle_http_exception(e)

        handler = self._find_error_handler(e)

        if handler is None:
            reraise(exc_type, exc_value, tb)
        return handler(e)

    @property
    def propagate_exceptions(self):
        """Returns the value of the ``PROPAGATE_EXCEPTIONS`` configuration
        value in case it's set, otherwise a sensible default is returned.

        .. versionadded:: 0.7
        """
        rv = self.config['PROPAGATE_EXCEPTIONS']  # pylint: disable=invalid-name
        if rv is not None:
            return rv
        return self.testing or self.debug

    def handle_exception(self, e):  # pylint: disable=invalid-name
        """Default exception handling that kicks in when an exception
        occurs that is not caught.  In debug mode the exception will
        be re-raised immediately, otherwise it is logged and the handler
        for a 500 internal server error is used.  If no such handler
        exists, a default 500 internal server error message is displayed.

        .. versionadded:: 0.3
        """
        exc_type, exc_value, tb = sys.exc_info()  # pylint: disable=invalid-name

        got_request_exception.send(self, exception=e)
        handler = self._find_error_handler(InternalServerError())

        if self.propagate_exceptions:
            # if we want to repropagate the exception, we can attempt to
            # raise it with the whole traceback in case we can do that
            # (the function was actually called from the except part)
            # otherwise, we just raise the error again
            if exc_value is e:
                reraise(exc_type, exc_value,
                        tb)  # pylint: disable=invalid-name
            else:
                raise e

        self.log_exception((exc_type, exc_value, tb))
        if handler is None:
            return InternalServerError()
        return self.finalize_request(handler(e), from_error_handler=True)

    def wsgi_app(self, environ, start_response):
        """The actual WSGI application. This is not implemented in
        :meth:`__call__` so that middlewares can be applied without
        losing a reference to the app object. Instead of doing this::

            app = MyMiddleware(app)

        It's a better idea to do this instead::

            app.wsgi_app = MyMiddleware(app.wsgi_app)

        Then you still have the original application object around and
        can continue to call methods on it.

        .. versionchanged:: 0.7
            Teardown events for the request and app contexts are called
            even if an unhandled error occurs. Other events may not be
            called depending on when an error occurs during dispatch.
            See :ref:`callbacks-and-errors`.

        :param environ: A WSGI environment.
        :param start_response: A callable accepting a status code,
            a list of headers, and an optional exception context to
            start the response.
        """
        ctx = self.request_context(environ)
        error = None
        try:
            try:
                ctx.push()
                response = self.full_dispatch_request()
            except Exception as e:  # pylint: disable=invalid-name,broad-except
                error = e
                response = self.handle_exception(e)
            except:
                error = sys.exc_info()[1]
                raise
            return response(environ, start_response)
        finally:
            if self.should_ignore_error(error):
                error = None
            ctx.auto_pop(error)

    def app_context(self):
        """Create an :class:`~flask.ctx.AppContext`. Use as a ``with``
        block to push the context, which will make :data:`current_app`
        point at this application.

        An application context is automatically pushed by
        :meth:`RequestContext.push() <flask.ctx.RequestContext.push>`
        when handling a request, and when running a CLI command. Use
        this to manually create a context outside of these situations.

        ::

            with app.app_context():
                init_db()

        See :doc:`/appcontext`.

        .. versionadded:: 0.9
        """
        return AppContext(self)

    def do_teardown_appcontext(self, exc=_sentinel):
        """Called right before the application context is popped.

        When handling a request, the application context is popped
        after the request context. See :meth:`do_teardown_request`.

        This calls all functions decorated with
        :meth:`teardown_appcontext`. Then the
        :data:`appcontext_tearing_down` signal is sent.

        This is called by
        :meth:`AppContext.pop() <flask.ctx.AppContext.pop>`.

        .. versionadded:: 0.9
        """
        if exc is _sentinel:
            exc = sys.exc_info()[1]
        for func in reversed(self.teardown_appcontext_funcs):
            func(exc)
        appcontext_tearing_down.send(self, exc=exc)

    def do_teardown_request(self, exc=_sentinel):
        """Called after the request is dispatched and the response is
        returned, right before the request context is popped.

        This calls all functions decorated with
        :meth:`teardown_request`, and :meth:`Blueprint.teardown_request`
        if a blueprint handled the request. Finally, the
        :data:`request_tearing_down` signal is sent.

        This is called by
        :meth:`RequestContext.pop() <flask.ctx.RequestContext.pop>`,
        which may be delayed during testing to maintain access to
        resources.

        :param exc: An unhandled exception raised while dispatching the
            request. Detected from the current exception information if
            not passed. Passed to each teardown function.

        .. versionchanged:: 0.9
            Added the ``exc`` argument.
        """
        if exc is _sentinel:
            exc = sys.exc_info()[1]
        funcs = reversed(self.teardown_request_funcs.get(None, ()))
        bp = _request_ctx_stack.top.request.blueprint  # pylint: disable=invalid-name
        if bp is not None and bp in self.teardown_request_funcs:
            funcs = chain(funcs, reversed(self.teardown_request_funcs[bp]))
        for func in funcs:
            func(exc)
        request_tearing_down.send(self, exc=exc)

    def __call__(self, environ, start_response):
        """The WSGI server calls the Flask application object as the
        WSGI application. This calls :meth:`wsgi_app` which can be
        wrapped to applying middleware."""
        return self.wsgi_app(environ, start_response)

    def __repr__(self):
        return '<%s %r>' % (
            self.__class__.__name__,
            self.name,
        )
