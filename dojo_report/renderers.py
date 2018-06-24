import json
import logging

from django.template.loader import get_template

from dojo_report.utils import convert_to_native_type

logger = logging.getLogger(__name__)


class ReportRenderingError(Exception):
    pass


class ReportRenderer(object):
    """
    Render a Dojo to a given format report by following the flow:
    - Get the queryset to be filtered
    - Create a context
    - Render the report
    """
    template = None
    _queryset = None
    _context = None
    _initial_context = None

    def __init__(self, queryset, initial_context={}):
        self._queryset = queryset
        self._initial_context = initial_context

    def create_context(self):
        self._context = self._initial_context
        self._context['objects'] = self._queryset.values()
        return self._context

    def _prepare_rendering(self):
        if not self._context:
            self.create_context()
        if not self.template:
            raise ReportRenderingError(
                "No template defined while rendering report")

    def _perform_rendering(self, context):
        template = get_template(self.template)
        return template.render(context)

    def render(self, context_update={}):
        self._prepare_rendering()
        context = self._context
        context.update(context_update)
        return self._perform_rendering(context_update)


class PdfReportRenderer(ReportRenderer):
    template = 'finding_pdf_report.pdf'

    def __init__(self, *args, **kwargs):
        super(PdfReportRenderer, self).__init__(*args, **kwargs)
        self.template = 'dojo/product_type_pdf_report.html'


class AsciiReportRenderer(ReportRenderer):
    template = 'asciidoc_report.html'


class JsonReportRenderer(ReportRenderer):
    def _prepare_rendering(self):
        """
        Monkey-patching the parent method, since no template is required for
        JSON reports
        """
        if not self._context:
            self.create_context()

    def _perform_rendering(self, context):
        return json.dumps(convert_to_native_type(context))
