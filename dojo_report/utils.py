import json
import logging
from datetime import datetime, date, time
from numbers import Number

import six
from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.template.loader import get_template
from django.utils import timezone

from dojo.filters import ReportFindingFilter
from dojo.models import Product_Type, Product, Engagement, Test, Endpoint, \
    Finding
from dojo.utils import get_period_counts_legacy

logger = logging.getLogger(__name__)


def is_iterable(x):
    try:
        iter(x)
    except TypeError:
        return False
    return True


def convert_model_typed_object(obj, exclude_fields=[], include_fields=[]):
    """
    Convert objects having Django's Model class as a base class to native
    types. ``include_fields`` takes precedence over ``exclude_fields``,
    meaning, if include_fields is specified, exclude_fields is ignored.
    :param obj: the object (of a Model type) to be converted to native data types
    :param list exclude_fields: a list of field names (strings) to be excluded
    :param list include_fields: a list of field names to be included
    :return: a new dict holding the native data-type object
    """
    if not include_fields:
        all_fields = {f.name for f in obj._meta.local_fields}
        include_fields = all_fields.difference(set(exclude_fields))

    return {f_name: convert_to_native_type(getattr(obj, f_name)) for
            f_name in include_fields}


def convert_to_native_type(obj, ignore_errors=False):
    """
    Convert complex, non-serializable objects to native data types
    :param obj: a python object of a given type
    :return: a representation with native data types of the given object
    """
    if obj is None:
        return None
    if isinstance(obj, six.string_types) or isinstance(obj, Number):
        return obj
    if isinstance(obj, dict):
        return {
            convert_to_native_type(k): convert_to_native_type(v) for
            k, v in obj.items()}
    if is_iterable(obj):
        return [convert_to_native_type(part) for part in obj]
    if isinstance(obj, datetime):
        return obj.strftime('%Y-%m-%dT%H:%M:%S')
    if isinstance(obj, date):
        return obj.strftime('%Y-%m-%d')
    if isinstance(obj, time):
        return obj.strftime('%H:%M:%S')
    if isinstance(obj, AbstractUser):
        return convert_model_typed_object(obj, exclude_fields=['password'])
    if isinstance(obj, models.Model):
        return convert_model_typed_object(obj)

    msg = "Unhandled object type detected: %s" % str(type(obj))
    logger.warning(msg)
    if not ignore_errors:
        raise ValueError(msg)


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


class GenericReportCreator(object):
    """
    A report creator should follow the flow:
    - Instanciate
    - populate
    - render
    """
    user = None
    report_type_class = None
    report_filter = None
    base_context = None
    _queryset = None
    _root_nodes = []

    _renderer_map = {
        'application/json': JsonReportRenderer,
        'application/pdf': PdfReportRenderer,
        'text/plain': AsciiReportRenderer,
    }

    def __init__(self, user, report_filter=None, host='',
                 parameters={}):
        """

        :param Dojo_User user:
        :param Filter report_filter:
        """
        self.user = user
        self.report_filter = report_filter
        self.base_context = {}
        self.host = host
        self.parameters = parameters

    @property
    def report_title(self):
        return "{verbose_name} Report".format(
            verbose_name=self.report_type_class.__name__)

    @property
    def report_subtitle(self):
        subtitle = ""
        if self._root_nodes and self._root_nodes.count():
            subtitle = "{name}".format(name=self._root_nodes[0].name)
        return subtitle

    @property
    def report_name(self):
        return "{title}: {subtitle}".format(title=self.report_title,
                                            subtitle=self.report_subtitle)

    def populate_base_context(self):
        self.base_context.update({
            'host': self.host,
            'title': self.report_title,
            'user': self.user,
            'team_name': settings.TEAM_NAME,
            'parameters': self.parameters,
        })

    def populate(self, **root_filter_criteria):
        """
        Populate the creator object by applying filter criteria to identify
        the report's root node(s) from which Finding objects will be looked up
        :param dict root_filter_criteria:
        """
        # TODO: model dependent authorization
        self._queryset = self.report_type_class.objects.filter(
            **root_filter_criteria)
        self._root_nodes = self._queryset.all()
        self.populate_base_context()

    def add_authorizing_filter(self, user):
        pass

    def render(self, format='application/json', ):
        renderer = self._renderer_map[format](self._queryset)
        return renderer.render(self.base_context)


class ProductTypeReportCreator(GenericReportCreator):
    report_type_class = Product_Type

    def populate(self, product_type, incl_finding_notes=False,
                 incl_finding_images=False, incl_executive_summary=False,
                 incl_table_of_contents=False, **root_filter_criteria):
        super(ProductTypeReportCreator, self).populate(**root_filter_criteria)

        self.base_context.update({
            'include_finding_notes': incl_finding_notes,
            'include_finding_images': incl_finding_images,
            'include_executive_summary': incl_executive_summary,
            'include_table_of_contents': incl_table_of_contents,
        })

        # root_filter_criteria was request.GET
        findings = ReportFindingFilter(root_filter_criteria,
                                       queryset=Finding.objects.filter(
                                           test__engagement__product__prod_type=product_type).distinct().prefetch_related(
                                           'test',
                                           'test__engagement__product',
                                           'test__engagement__product__prod_type'))
        products = Product.objects.filter(prod_type=product_type,
                                          engagement__test__finding__in=findings.qs).distinct()
        engagements = Engagement.objects.filter(
            product__prod_type=product_type,
            test__finding__in=findings.qs).distinct()
        tests = Test.objects.filter(
            engagement__product__prod_type=product_type,
            finding__in=findings.qs).distinct()
        if findings:
            start_date = timezone.make_aware(
                datetime.combine(findings.qs.last().date, datetime.min.time()))
        else:
            start_date = timezone.now()

        end_date = timezone.now()
        r = relativedelta(end_date, start_date)
        months_between = (r.years * 12) + r.months
        # include current month
        months_between += 1

        endpoint_monthly_counts = get_period_counts_legacy(findings.qs,
                                                           findings.qs, None,
                                                           months_between,
                                                           start_date,
                                                           relative_delta='months')

        opened_per_period = []
        if endpoint_monthly_counts is not None:
            opened_per_period = endpoint_monthly_counts['opened_per_period']

        self.base_context.update({
            'product_type': product_type,
            'products': products,
            'engagements': engagements,
            'tests': tests,
            'report_name': self.report_name,
            'endpoint_opened_per_month': opened_per_period,
            'endpoint_active_findings': findings.qs,
            'findings': findings.qs,
        })


class ProductReportCreator(GenericReportCreator):
    def add_authorizing_filter(self, user):
        self._queryset = self._queryset.filter(authorized_users=user)


class EngagementReportCreator(GenericReportCreator):
    pass


class TestReportCreator(GenericReportCreator):
    pass


class EndpointReportCreator(GenericReportCreator):
    def add_authorizing_filter(self, user):
        self._queryset = self._queryset.filter(product__authorized_users=user)


_report_creator_map = {
    Product_Type: ProductTypeReportCreator,
    Product: ProductReportCreator,
    Engagement: EngagementReportCreator,
    Test: TestReportCreator,
    Endpoint: EndpointReportCreator,
}


def get_report_creator_class(model_class):
    return _report_creator_map[model_class]
