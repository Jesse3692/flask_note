"""templating"""
from jinja2 import Environment as BaseEnvironment, TemplateNotFound, BaseLoader
from __globals import _request_ctx_stack, _app_ctx_stack


class Environment(BaseEnvironment):
    """Works like a regular Jinja2 environment but has some additional
    knowledge of how Flask's blueprint works so that it can prepend the
    name of the blueprint to referenced templates if necessary.
    """

    def __init__(self, app, **options):
        if 'loader' not in options:
            options['loader'] = app.create_global_jinja_loader()
        BaseEnvironment.__init__(self, **options)
        self.app = app


class DispatchingJinjaLoader(BaseLoader):
    """A loader that looks for templates in the application and all
    the blueprint folders.
    """

    def __init__(self, app):
        self.app = app

    def get_source(self, environment, template):
        if self.app.config['EXPLAIN_TEMPLATE_LOADING']:
            return self._get_source_explained(environment, template)
        return self._get_source_fast(environment, template)

    def _get_source_explained(self, environment, template):
        attempts = []
        trv = None

        for srcobj, loader in self._iter_loaders(template):
            try:
                # pylint: disable=invalid-name
                rv = loader.get_source(
                    environment, template)
                if trv is None:
                    trv = rv
            except TemplateNotFound:
                rv = None  # pylint: disable=invalid-name
            attempts.append((loader, srcobj, rv))

        from __debughelpers import explain_template_loading_attempts  # pylint: disable=relative-beyond-top-level,import-outside-toplevel
        explain_template_loading_attempts(self.app, template, attempts)

        if trv is not None:
            return trv
        raise TemplateNotFound(template)

    def _get_source_fast(self, environment, template):
        for srcobj, loader in self._iter_loaders(template):  # pylint: disable=unused-variable
            try:
                return loader.get_source(environment, template)
            except TemplateNotFound:
                continue
        raise TemplateNotFound(template)

    def _iter_loaders(self, template):  # pylint: disable=unused-argument
        loader = self.app.jinja_loader
        if loader is not None:
            yield self.app, loader

        for blueprint in self.app.iter_blueprints():
            loader = blueprint.jinja_loader
            if loader is not None:
                yield blueprint, loader

    def list_templates(self):
        result = set()
        loader = self.app.jinja_loader
        if loader is not None:
            result.update(loader.list_templates())

        for blueprint in self.app.iter_blueprints():
            loader = blueprint.jinja_loader
            if loader is not None:
                for template in loader.list_templates():
                    result.add(template)

        return list(result)


def _default_template_ctx_processor():
    """Default template context processor.  Injects `request`,
    `session` and `g`.
    """
    reqctx = _request_ctx_stack.top
    appctx = _app_ctx_stack.top
    rv = {}  # pylint: disable=invalid-name
    if appctx is not None:
        rv['g'] = appctx.g
    if reqctx is not None:
        rv['request'] = reqctx.request
        rv['session'] = reqctx.session
    return rv
