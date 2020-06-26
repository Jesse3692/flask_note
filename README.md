# flask学习笔记

> 基于Flask 1.0.2

## 1. 基础用法

### 最小实例hello world

```python
from flask import Flask  # 从flask模块导入Flask类

app = Flask(__name__)  # 实例化Flask类


@app.route('/')  # 添加路由
def helloworld():
    return "<h1>helloworld</h1>"


if __name__ == "__main__":
    app.run(debug=True)  # 调用werkzerug中的run_simple
```



1. 先看一下Flask对象的 `__init__`方法，先不考虑`jinja2`，看下核心成员有哪些：

```python
# https://github.com/Jesse3692/flask_note/blob/4c05ffebc83f2c4070e920e3d06b23157ed20c7c/source/flask/app.py
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
    	# 执行父类中的初始化方法，获取包的绝对路径
        _PackageBoundObject.__init__(
            self,
            import_name,
            template_folder=template_folder,
            root_path=root_path
        )

        #: A dictionary of all view functions registered.  
        #: 这个字典中保存的是所有已经注册过的视图函数
        #: The keys will be function names which are also used to generate URLs and the values are the function objects themselves.
        #: 键是函数名称可以用来生成URLs，值是函数对象本身
        #: To register a view function, use the :meth:`route` decorator.
        #: 使用route装饰器来注册一个视图函数
        self.view_functions = {}

        #: A dictionary of all registered error handlers.
        #：这个字典用来存储已经注册的错误处理函数
        #: The key is ``None``for error handlers active on the application, otherwise the key is the name of the blueprint.
        #: Each key points to another dictionary where the key is the status code of the http exception.
        #:   
        #: The special key ``None`` points to a list of tuples where the first item
        #: is the class for the instance check and the second the error handler
        #: function.
        #:
        #: To register an error handler, use the :meth:`errorhandler` decorator.
        #: 使用errorhandler装饰器来注册一个错误处理函数
        self.error_handler_spec = {}

        #: A dictionary with lists of functions that will be called at the beginning of each request.
        #: 这个字典中列出的函数将在每个请求之前被调用
        #: The key of the dictionary is the name of the blueprint this function is active for, or ``None`` for all
        #: requests. To register a function, use the :meth:`before_request` decorator.
        #: 
        self.before_request_funcs = {}

        #: A list of functions that will be called at the beginning of the first request to this instance.
        #:  To register a function, use the
        #: :meth:`before_first_request` decorator.
        #:
        #: .. versionadded:: 0.8
        self.before_first_request_funcs = []

        #: A dictionary with lists of functions that should be called after each request.
        #: 这个字典中列出的函数将在每个请求之后被调用
        #: The key of the dictionary is the name of the blueprint this function is active for, ``None`` for all requests.  
        #: This can for example be used to close database connections. To register a function
        #: here, use the :meth:`after_request` decorator.
        self.after_request_funcs = {}

        #: all the attached blueprints in a dictionary by name.  Blueprints
        #: can be attached multiple times so this dictionary does not tell
        #: you how often they got attached.
        #:
        #: .. versionadded:: 0.7
        self.blueprints = {}
        self._blueprint_order = []

        #: The :class:`~werkzeug.routing.Map` for this instance.  
        #: You can use this to change the routing converters after the class was created but before any routes are connected.
        #:  你能使用这个改变路由转换器，需要在任何路由连接之前在类创建之后
        #:  Example::
        #:    from werkzeug.routing import BaseConverter
        #:
        #:    class ListConverter(BaseConverter):
        #:        def to_python(self, value):
        #:            return value.split(',')
        #:        def to_url(self, values):
        #:            return ','.join(super(ListConverter, self).to_url(value)
        #:                            for value in values)
        #:
        #:    app = Flask(__name__)
        #:    app.url_map.converters['list'] = ListConverter
        #: 保存url到视图函数的映射，即保存app.route()这个装饰器的信息
        self.url_map = Map()
```



- `self.import_name` 应用程序包的名称
- `self.root_path` 应用程序的根目录
- `self.view_functions = {}`  这个字典中保存的是所有已经注册过的视图函数，使用 `@route` 装饰器注册
- `self.error_handler_spec = {}` 这个字典用来存储已经注册的错误处理函数，使用 `@errorhandler`装饰器注册
- `self.before_request_funcs = {}`  这个字典中列出的函数将在每个请求之前被调用，使用 `@before_request`装饰器注册
- `self.url_map = Map()` 是`~werkzeug.routing.Map`的实例，保存url到视图函数的映射，即保存`app.route()`这个装饰器的信息

2. 再看一看`Flask`类中传 `__name__`的作用：

```python
# https://github.com/Jesse3692/flask_note/blob/4c05ffebc83f2c4070e920e3d06b23157ed20c7c/source/flask/app.py
class Flask(_PackageBoundObject):
	@locked_cached_property
    def name(self):
        """The name of the application.  
        This is usually the import name with the difference that it's guessed from the run file if the import name is main.  
        This name is used as a display name when Flask needs the name of the application.  
        It can be set and overridden to change the value.

        .. versionadded:: 0.8
        """
        if self.import_name == '__main__':
            fn = getattr(sys.modules['__main__'], '__file__', None)
            if fn is None:
                return '__main__'
            return os.path.splitext(os.path.basename(fn))[0]
        return self.import_name
```

这个 `__name__` 名称是用来寻找文件系统上的资源，这里`getattr`的作用是[^1]返回的是模块的绝对路径。

3. 接下来看下，路由的添加

```python
def route(self, rule, **options):
        """A decorator that is used to register a view function for a
        given URL rule（这个装饰器被用来使用给定的url规则注册一个视图函数 ）.  This does the same thing as :meth:`add_url_rule`
        but is intended for decorator usage::

            @app.route('/')
            def index():
                return 'Hello World'

        For more information refer to :ref:`url-route-registrations`.

        :param rule: the URL rule as string
        :param endpoint: the endpoint for the registered URL rule.  Flask
                         itself assumes the name of the view function as
                         endpoint
        :param options: the options to be forwarded to the underlying
                        :class:`~werkzeug.routing.Rule` object.  A change
                        to Werkzeug is handling of method options.  methods
                        is a list of methods this rule should be limited
                        to (``GET``, ``POST`` etc.).  By default a rule
                        just listens for ``GET`` (and implicitly ``HEAD``).
                        Starting with Flask 0.6, ``OPTIONS`` is implicitly
                        added and handled by the standard request handling.
        """
        def decorator(f):
            endpoint = options.pop('endpoint', None)
            self.add_url_rule(rule, endpoint, f, **options)
            return f
        return decorator
```

在为视图函数添加路由时，是用的Flask类实例的`route`方法进行装饰的，实际上调用的是`self.add_url_rule`方法

4. 最后看一下应用的运行

![image-20200625221720369](https://i.loli.net/2020/06/25/Z4cG5nAabESlCBj.png)

```python
# Flask类
def __call__(self, environ, start_response):
        """The WSGI server calls the Flask application object as the WSGI application. 
        Wsgi 服务器将 Flask 应用程序对象调用为 WSGI 应用程序
        This calls :meth:`wsgi_app` which can be
        wrapped to applying middleware."""
        return self.wsgi_app(environ, start_response)
```

```python
# Flask类
def wsgi_app(self, environ, start_response):
        """The actual WSGI application. This is not implemented in
        :meth:`__call__` so that middlewares can be applied without
        losing a reference to the app object. 
        这在: meth: ‘call’中没有实现，因此中间件可以应用而不会丢失对 app 对象的引用。
        Instead of doing this::

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
            except Exception as e:
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
```

`wsgi_app`是flask的核心，它的作用就是先调用所有的预处理函数，然后分发请求，再处理可能的异常，最后返回response。

这里看一下`dispatch_request`的实现逻辑，它主要进行请求的分发

```python
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
```

这里是对异常的处理

```python
def full_dispatch_request(self):
        """Dispatches the request and on top of that performs request
        pre and postprocessing as well as HTTP exception catching and error handling.
        调度请求，并在此基础上执行请求预处理和后处理，以及 HTTP 异常捕获和错误处理。
        .. versionadded:: 0.7
        """
        self.try_trigger_before_first_request_functions()
        try:
            request_started.send(self)
            rv = self.preprocess_request()
            if rv is None:
                rv = self.dispatch_request()
        except Exception as e:
            rv = self.handle_user_exception(e)
        return self.finalize_request(rv)
```



```python
# https://github.com/Jesse3692/flask_note/blob/4c05ffebc83f2c4070e920e3d06b23157ed20c7c/source/werkzeug/serving.py
# werkzeug.serving.run_simple
def run_simple(
    hostname,
    port,
    application,
    use_reloader=False,
    use_debugger=False,
    use_evalex=True,
    extra_files=None,
    reloader_interval=1,
    reloader_type="auto",
    threaded=False,
    processes=1,
    request_handler=None,
    static_files=None,
    passthrough_errors=False,
    ssl_context=None,
):
    """Start a WSGI application. Optional features include a reloader,
    multithreading and fork support.

    This function has a command-line interface too::

        python -m werkzeug.serving --help

    .. versionadded:: 0.5
       `static_files` was added to simplify serving of static files as well
       as `passthrough_errors`.

    .. versionadded:: 0.6
       support for SSL was added.

    .. versionadded:: 0.8
       Added support for automatically loading a SSL context from certificate
       file and private key.

    .. versionadded:: 0.9
       Added command-line interface.

    .. versionadded:: 0.10
       Improved the reloader and added support for changing the backend
       through the `reloader_type` parameter.  See :ref:`reloader`
       for more information.

    .. versionchanged:: 0.15
        Bind to a Unix socket by passing a path that starts with
        ``unix://`` as the ``hostname``.

    :param hostname: The host to bind to, for example ``'localhost'``.
        If the value is a path that starts with ``unix://`` it will bind
        to a Unix socket instead of a TCP socket..
    :param port: The port for the server.  eg: ``8080``
    :param application: the WSGI application to execute
    :param use_reloader: should the server automatically restart the python
                         process if modules were changed?
    :param use_debugger: should the werkzeug debugging system be used?
    :param use_evalex: should the exception evaluation feature be enabled?
    :param extra_files: a list of files the reloader should watch
                        additionally to the modules.  For example configuration
                        files.
    :param reloader_interval: the interval for the reloader in seconds.
    :param reloader_type: the type of reloader to use.  The default is
                          auto detection.  Valid values are ``'stat'`` and
                          ``'watchdog'``. See :ref:`reloader` for more
                          information.
    :param threaded: should the process handle each request in a separate
                     thread?
    :param processes: if greater than 1 then handle each request in a new process
                      up to this maximum number of concurrent processes.
    :param request_handler: optional parameter that can be used to replace
                            the default one.  You can use this to replace it
                            with a different
                            :class:`~BaseHTTPServer.BaseHTTPRequestHandler`
                            subclass.
    :param static_files: a list or dict of paths for static files.  This works
                         exactly like :class:`SharedDataMiddleware`, it's actually
                         just wrapping the application in that middleware before
                         serving.
    :param passthrough_errors: set this to `True` to disable the error catching.
                               This means that the server will die on errors but
                               it can be useful to hook debuggers in (pdb etc.)
    :param ssl_context: an SSL context for the connection. Either an
                        :class:`ssl.SSLContext`, a tuple in the form
                        ``(cert_file, pkey_file)``, the string ``'adhoc'`` if
                        the server should automatically create one, or ``None``
                        to disable SSL (which is the default).
    """
    if not isinstance(port, int):
        raise TypeError("port must be an integer")
    if use_debugger:
        from .debug import DebuggedApplication

        application = DebuggedApplication(application, use_evalex)
    if static_files:
        from .middleware.shared_data import SharedDataMiddleware

        application = SharedDataMiddleware(application, static_files)

    def log_startup(sock):
        display_hostname = hostname if hostname not in ("", "*") else "localhost"
        quit_msg = "(Press CTRL+C to quit)"
        if sock.family == af_unix:
            _log("info", " * Running on %s %s", display_hostname, quit_msg)
        else:
            if ":" in display_hostname:
                display_hostname = "[%s]" % display_hostname
            port = sock.getsockname()[1]
            _log(
                "info",
                " * Running on %s://%s:%d/ %s",
                "http" if ssl_context is None else "https",
                display_hostname,
                port,
                quit_msg,
            )

    def inner():
        try:
            fd = int(os.environ["WERKZEUG_SERVER_FD"])
        except (LookupError, ValueError):
            fd = None
        srv = make_server(
            hostname,
            port,
            application,
            threaded,
            processes,
            request_handler,
            passthrough_errors,
            ssl_context,
            fd=fd,
        )
        if fd is None:
            log_startup(srv.socket)
        srv.serve_forever()

    if use_reloader:
        # If we're not running already in the subprocess that is the
        # reloader we want to open up a socket early to make sure the
        # port is actually available.
        if not is_running_from_reloader():
            if port == 0 and not can_open_by_fd:
                raise ValueError(
                    "Cannot bind to a random port with enabled "
                    "reloader if the Python interpreter does "
                    "not support socket opening by fd."
                )

            # Create and destroy a socket so that any exceptions are
            # raised before we spawn a separate Python interpreter and
            # lose this ability.
            address_family = select_address_family(hostname, port)
            server_address = get_sockaddr(hostname, port, address_family)
            s = socket.socket(address_family, socket.SOCK_STREAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(server_address)
            if hasattr(s, "set_inheritable"):
                s.set_inheritable(True)

            # If we can open the socket by file descriptor, then we can just
            # reuse this one and our socket will survive the restarts.
            if can_open_by_fd:
                os.environ["WERKZEUG_SERVER_FD"] = str(s.fileno())
                s.listen(LISTEN_QUEUE)
                log_startup(s)
            else:
                s.close()
                if address_family == af_unix:
                    _log("info", "Unlinking %s" % server_address)
                    os.unlink(server_address)

        # Do not use relative imports, otherwise "python -m werkzeug.serving"
        # breaks.
        from ._reloader import run_with_reloader

        run_with_reloader(inner, extra_files, reloader_interval, reloader_type)
    else:
        inner()
```



## 2. 进阶用法

## 3. 高级用法

## 4. 源码分析

注释：

[^1]:  相当于`sys.modules['__main__'].__file__`