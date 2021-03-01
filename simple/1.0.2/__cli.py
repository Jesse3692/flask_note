"""cli"""
import ast
import inspect
import os
import re
import sys
import traceback
from functools import update_wrapper
from inspect import getfullargspec as getargspec

import click
from __compat import iteritems

try:
    import dotenv
except ImportError:
    dotenv = None


def show_server_banner(env, debug, app_import_path, eager_loading):
    """Show extra startup messages the first time the server is run,
    ignoring the reloader.
    """
    if os.environ.get('WERKZEUG_RUN_MAIN') == 'true':
        return

    if app_import_path is not None:
        message = ' * Serving Flask app "{0}"'.format(app_import_path)

        if not eager_loading:
            message += ' (lazy loading)'

        click.echo(message)

    click.echo(' * Environment: {0}'.format(env))

    if env == 'production':
        click.secho(
            '   WARNING: Do not use the development server in a production'
            ' environment.', fg='red')
        click.secho('   Use a production WSGI server instead.', dim=True)

    if debug is not None:
        click.echo(' * Debug mode: {0}'.format('on' if debug else 'off'))


def call_factory(script_info, app_factory, arguments=()):
    """Takes an app factory, a ``script_info` object and  optionally a tuple
    of arguments. Checks for the existence of a script_info argument and calls
    the app_factory depending on that and the arguments provided.
    """
    args_spec = getargspec(app_factory)
    arg_names = args_spec.args
    arg_defaults = args_spec.defaults

    if 'script_info' in arg_names:
        return app_factory(*arguments, script_info=script_info)
    elif arguments:
        return app_factory(*arguments)
    elif not arguments and len(arg_names) == 1 and arg_defaults is None:
        return app_factory(script_info)

    return app_factory()


def prepare_import(path):
    """Given a filename this will try to calculate the python path, add it
    to the search path and return the actual module name that is expected.
    """
    path = os.path.realpath(path)

    if os.path.splitext(path)[1] == '.py':
        path = os.path.splitext(path)[0]

    if os.path.basename(path) == '__init__':
        path = os.path.dirname(path)

    module_name = []

    # move up until outside package structure (no __init__.py)
    while True:
        path, name = os.path.split(path)
        module_name.append(name)

        if not os.path.exists(os.path.join(path, '__init__.py')):
            break

    if sys.path[0] != path:
        sys.path.insert(0, path)

    return '.'.join(module_name[::-1])


def load_dotenv(path=None):
    """Load "dotenv" files in order of precedence to set environment variables.

    If an env var is already set it is not overwritten, so earlier files in the
    list are preferred over later files.

    Changes the current working directory to the location of the first file
    found, with the assumption that it is in the top level project directory
    and will be where the Python path should import local packages from.

    This is a no-op if `python-dotenv`_ is not installed.

    .. _python-dotenv: https://github.com/theskumar/python-dotenv#readme

    :param path: Load the file at this location instead of searching.
    :return: ``True`` if a file was loaded.

    .. versionadded:: 1.0
    """
    if dotenv is None:
        if path or os.path.exists('.env') or os.path.exists('.flaskenv'):
            click.secho(
                ' * Tip: There are .env files present.'
                ' Do "pip install python-dotenv" to use them.',
                fg='yellow')
        return

    if path is not None:
        return dotenv.load_dotenv(path)

    new_dir = None

    for name in ('.env', '.flaskenv'):
        path = dotenv.find_dotenv(name, usecwd=True)

        if not path:
            continue

        if new_dir is None:
            new_dir = os.path.dirname(path)

        dotenv.load_dotenv(path)

    if new_dir and os.getcwd() != new_dir:
        os.chdir(new_dir)

    return new_dir is not None  # at least one file was located and loaded


class NoAppException(click.UsageError):
    """Raised if an application cannot be found or loaded."""


def _called_with_wrong_args(factory):
    """Check whether calling a function raised a ``TypeError`` because
    the call failed or because something in the factory raised the
    error.

    :param factory: the factory function that was called
    :return: true if the call failed
    """
    tb = sys.exc_info()[2]  # pylint: disable=invalid-name

    try:
        while tb is not None:
            if tb.tb_frame.f_code is factory.__code__:
                # in the factory, it was called successfully
                return False

            tb = tb.tb_next  # pylint: disable=invalid-name

        # didn't reach the factory
        return True
    finally:
        del tb


def find_best_app(script_info, module):
    """Given a module instance this tries to find the best possible
    application in the module or raises an exception.
    """
    from . import Flask  # pylint:disable=import-outside-toplevel,relative-beyond-top-level

    # Search for the most common names first.
    for attr_name in ('app', 'application'):
        app = getattr(module, attr_name, None)

        if isinstance(app, Flask):
            return app

    # Otherwise find the only object that is a Flask instance.
    matches = [
        v for k, v in iteritems(module.__dict__) if isinstance(v, Flask)
    ]

    if len(matches) == 1:
        return matches[0]
    elif len(matches) > 1:
        raise NoAppException(
            'Detected multiple Flask applications in module "{module}". Use '
            '"FLASK_APP={module}:name" to specify the correct '
            'one.'.format(module=module.__name__)
        )

    # Search for app factory functions.
    for attr_name in ('create_app', 'make_app'):
        app_factory = getattr(module, attr_name, None)

        if inspect.isfunction(app_factory):
            try:
                app = call_factory(script_info, app_factory)

                if isinstance(app, Flask):
                    return app
            except TypeError as type_error:
                if not _called_with_wrong_args(app_factory):
                    raise
                raise NoAppException(
                    'Detected factory "{factory}" in module "{module}", but '
                    'could not call it without arguments. Use '
                    '"FLASK_APP=\'{module}:{factory}(args)\'" to specify '
                    'arguments.'.format(
                        factory=attr_name, module=module.__name__
                    )
                ) from type_error

    raise NoAppException(
        'Failed to find Flask application or factory in module "{module}". '
        'Use "FLASK_APP={module}:name to specify one.'.format(
            module=module.__name__
        )
    )


def find_app_by_string(script_info, module, app_name):
    """Checks if the given string is a variable name or a function. If it is a
    function, it checks for specified arguments and whether it takes a
    ``script_info`` argument and calls the function with the appropriate
    arguments.
    """
    from flask import Flask  # pylint: disable=import-outside-toplevel
    match = re.match(r'^ *([^ ()]+) *(?:\((.*?) *,? *\))? *$', app_name)

    if not match:
        raise NoAppException(
            '"{name}" is not a valid variable name or function '
            'expression.'.format(name=app_name)
        )

    name, args = match.groups()

    try:
        attr = getattr(module, name)
    except AttributeError as attribute_error:
        raise NoAppException(attribute_error.args[0]) from attribute_error

    if inspect.isfunction(attr):
        if args:
            try:
                args = ast.literal_eval('({args},)'.format(args=args))
            except (ValueError, SyntaxError)as value_syntax_error:
                raise NoAppException(
                    # HACK pylint: disable=unused-format-string-argument
                    'Could not parse the arguments in '
                    '"{app_name}".'.format(
                        e=value_syntax_error, app_name=app_name)
                ) from value_syntax_error
        else:
            args = ()

        try:
            app = call_factory(script_info, attr, args)
        except TypeError as type_error:
            if not _called_with_wrong_args(attr):
                raise

            raise NoAppException(
                '{e}\nThe factory "{app_name}" in module "{module}" could not '
                'be called with the specified arguments.'.format(
                    e=type_error, app_name=app_name, module=module.__name__
                )
            ) from type_error
    else:
        app = attr

    if isinstance(app, Flask):
        return app

    raise NoAppException(
        'A valid Flask application was not obtained from '
        '"{module}:{app_name}".'.format(
            module=module.__name__, app_name=app_name
        )
    )


def locate_app(script_info, module_name, app_name, raise_if_not_found=True):
    """#TODO"""
    __traceback_hide__ = True  # pylint: disable=unused-variable

    try:
        __import__(module_name)
    except ImportError as import_error:
        # Reraise the ImportError if it occurred within the imported module.
        # Determine this by checking whether the trace has a depth > 1.
        if sys.exc_info()[-1].tb_next:
            raise NoAppException(
                'While importing "{name}", an ImportError was raised:'
                '\n\n{tb}'.format(name=module_name, tb=traceback.format_exc())
            ) from import_error
        elif raise_if_not_found:
            raise NoAppException(
                'Could not import "{name}".'.format(name=module_name)
            ) from import_error
        else:
            return

    module = sys.modules[module_name]

    if app_name is None:
        return find_best_app(script_info, module)
    else:
        return find_app_by_string(script_info, module, app_name)


def get_env():
    """Get the environment the app is running in, indicated by the
    :envvar:`FLASK_ENV` environment variable. The default is
    ``'production'``.
    """
    return os.environ.get('FLASK_ENV') or 'production'


def get_debug_flag():
    """Get whether debug mode should be enabled for the app, indicated
    by the :envvar:`FLASK_DEBUG` environment variable. The default is
    ``True`` if :func:`.get_env` returns ``'development'``, or ``False``
    otherwise.
    """
    val = os.environ.get('FLASK_DEBUG')

    if not val:
        return get_env() == 'development'

    return val.lower() not in ('0', 'false', 'no')


class ScriptInfo(object):
    """Help object to deal with Flask applications.  This is usually not
    necessary to interface with as it's used internally in the dispatching
    to click.  In future versions of Flask this object will most likely play
    a bigger role.  Typically it's created automatically by the
    :class:`FlaskGroup` but you can also manually create it and pass it
    onwards as click object.
    """

    def __init__(self, app_import_path=None, create_app=None):
        #: Optionally the import path for the Flask application.
        self.app_import_path = app_import_path or os.environ.get('FLASK_APP')
        #: Optionally a function that is passed the script info to create
        #: the instance of the application.
        self.create_app = create_app
        #: A dictionary with arbitrary data that can be associated with
        #: this script info.
        self.data = {}
        self._loaded_app = None

    def load_app(self):
        """Loads the Flask app (if not yet loaded) and returns it.  Calling
        this multiple times will just result in the already loaded app to
        be returned.
        """
        __traceback_hide__ = True  # pylint: disable=unused-variable

        if self._loaded_app is not None:
            return self._loaded_app

        app = None

        if self.create_app is not None:
            app = call_factory(self, self.create_app)
        else:
            if self.app_import_path:
                path, name = (self.app_import_path.split(':', 1) + [None])[:2]
                import_name = prepare_import(path)
                app = locate_app(self, import_name, name)
            else:
                for path in ('wsgi.py', 'app.py'):
                    import_name = prepare_import(path)
                    app = locate_app(self, import_name, None,
                                     raise_if_not_found=False)

                    if app:
                        break

        if not app:
            raise NoAppException(
                'Could not locate a Flask application. You did not provide '
                'the "FLASK_APP" environment variable, and a "wsgi.py" or '
                '"app.py" module was not found in the current directory.'
            )

        debug = get_debug_flag()

        # Update the app's debug flag through the descriptor so that other
        # values repopulate as well.
        if debug is not None:
            app.debug = debug

        self._loaded_app = app
        return app


def with_appcontext(f):  # pylint: disable=invalid-name
    """Wraps a callback so that it's guaranteed to be executed with the
    script's application context.  If callbacks are registered directly
    to the ``app.cli`` object then they are wrapped with this function
    by default unless it's disabled.
    """
    @click.pass_context
    def decorator(__ctx, *args, **kwargs):
        with __ctx.ensure_object(ScriptInfo).load_app().app_context():
            return __ctx.invoke(f, *args, **kwargs)
    return update_wrapper(decorator, f)


class AppGroup(click.Group):
    """This works similar to a regular click :class:`~click.Group` but it
    changes the behavior of the :meth:`command` decorator so that it
    automatically wraps the functions in :func:`with_appcontext`.

    Not to be confused with :class:`FlaskGroup`.
    """

    def command(self, *args, **kwargs):
        """This works exactly like the method of the same name on a regular
        :class:`click.Group` but it wraps callbacks in :func:`with_appcontext`
        unless it's disabled by passing ``with_appcontext=False``.
        """
        wrap_for_ctx = kwargs.pop('with_appcontext', True)

        def decorator(f):  # pylint: disable=invalid-name
            if wrap_for_ctx:
                f = with_appcontext(f)
            return click.Group.command(self, *args, **kwargs)(f)
        return decorator

    def group(self, *args, **kwargs):
        """This works exactly like the method of the same name on a regular
        :class:`click.Group` but it defaults the group class to
        :class:`AppGroup`.
        """
        kwargs.setdefault('cls', AppGroup)
        return click.Group.group(self, *args, **kwargs)
