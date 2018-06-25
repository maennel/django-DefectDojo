import json
import logging

from django.template.loader import get_template

from dojo.models import Report
from dojo.tasks import async_pdf_report
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
    TYPE_CUSTOM = 'custom'
    TYPE_ENDPOINT = 'endpoint'
    TYPE_ENGAGEMENT = 'engagement'
    TYPE_FINDING = 'finding'
    TYPE_PRODUCT_ENDPOINT = 'product_endpoint'
    TYPE_PRODUCT = 'product'
    TYPE_PRODUCT_TYPE = 'product_type'
    TYPE_REPORT = 'report'
    TYPE_TEST = 'test'
    TYPE_QUERYSET = 'queryset'

    report_types = [
        TYPE_CUSTOM,
        TYPE_ENDPOINT,
        TYPE_ENGAGEMENT,
        TYPE_FINDING,
        TYPE_PRODUCT_ENDPOINT,
        TYPE_PRODUCT,
        TYPE_PRODUCT_TYPE,
        TYPE_REPORT,
        TYPE_TEST,
        TYPE_QUERYSET,
    ]
    report_type = None
    template = None

    _queryset = None
    _context = None
    _initial_context = None

    def __init__(self, queryset, report_type, initial_context={}):
        self._queryset = queryset
        if report_type not in self.report_types:
            raise ReportRenderingError(
                "Invalid report_type specified while rendering report")
        self.report_type = report_type
        self._initial_context = initial_context

    def create_context(self):
        self._context = self._initial_context
        self._context['objects'] = self._queryset.values()
        return self._context

    def prepare_rendering(self):
        if not self._context:
            self.create_context()
        if not self.template:
            raise ReportRenderingError(
                "No template defined while rendering report")

    def perform_rendering(self, context):
        template = get_template(self.template)
        return template.render(context)

    def render(self, context_update={}):
        self.prepare_rendering()
        context = self._context
        context.update(context_update)
        return self.perform_rendering(context_update)


class PdfReportRenderer(ReportRenderer):
    filename = None

    def __init__(self, queryset, report_type, *args, **kwargs):
        super(PdfReportRenderer, self).__init__(queryset, report_type, *args,
                                                **kwargs)
        self.template = '{report_type}_pdf_report.html'.format(
            report_type=self.report_type)
        self.filename = '{report_type}_report.pdf'.format(
            report_type=self.report_type)

    def perform_rendering(self, context):
        report = Report.objects.create(
            name=context.get('report_name', 'Unnamed Report'),
            type=self.report_type,
            format='PDF',
            requester=context.get('user'),
            options=context.get('options', '')
        )
        async_result = async_pdf_report.delay(
            report=report,
            template=self.template,
            filename=self.filename,
            report_title=context.get('title', 'Untitled Report'),
            report_subtitle=context.get('subtitle', ''),
            report_info=context.get('info', ''),
            context=context,
            uri=report.get_url(),
        )
        # TODO: Move this to view level
        # messages.success(request, 'Your report is building', extra_tags='alert-success')
        # return HttpResponseRedirect(reverse('reports'))
        return async_result


class AsciiReportRenderer(ReportRenderer):
    template = 'asciidoc_report.html'


class JsonReportRenderer(ReportRenderer):
    def prepare_rendering(self):
        """
        Monkey-patching the parent method, since no template is required for
        JSON reports
        """
        if not self._context:
            self.create_context()

    def perform_rendering(self, context):
        return json.dumps(convert_to_native_type(context))
