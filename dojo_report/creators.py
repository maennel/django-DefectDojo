import logging
from collections import namedtuple
from datetime import datetime

from dateutil import relativedelta
from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.utils import timezone

from dojo.filters import ReportFindingFilter, ReportAuthedFindingFilter
from dojo.models import Product_Type, Product, Engagement, Test, Endpoint, \
    Finding
from dojo.utils import get_period_counts_legacy
from dojo_report.renderers import JsonReportRenderer, PdfReportRenderer, \
    AsciiReportRenderer

logger = logging.getLogger(__name__)

IncludeFlags = namedtuple('IncludeFlags', ['finding_notes',
                                           'finding_images',
                                           'executive_summary',
                                           'table_of_contents'])


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
    include_flags = None
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
            'subtitle': self.report_subtitle,
            'report_name': self.report_name,
            'user': self.user,
            'team_name': settings.TEAM_NAME,
            'parameters': self.parameters,

            # Inclusion flags
            'include_finding_notes': self.include_flags.finding_notes,
            'include_finding_images': self.include_flags.finding_images,
            'include_executive_summary': self.include_flags.executive_summary,
            'include_table_of_contents': self.include_flags.table_of_contents,
        })

    def populate(self, *objs, **context_kwargs):
        """
        Populate the creator object by applying filter criteria to identify
        the report's root node(s) from which Finding objects will be looked up
        :param list objs:
        :param dict context_kwargs:
        """
        self.include_flags = IncludeFlags(
            finding_notes=context_kwargs.pop('include_finding_notes', False),
            finding_images=context_kwargs.pop('include_finding_images', False),
            executive_summary=context_kwargs.pop('include_executive_summary',
                                                 False),
            table_of_contents=context_kwargs.pop('include_table_of_contents',
                                                 False))

        # TODO: model dependent authorization
        self._queryset = self.report_type_class.objects.filter(
            **context_kwargs)
        self.add_authorizing_filter(self.user)
        self._root_nodes = self._queryset.all()
        self.populate_base_context()

    def add_authorizing_filter(self, user):
        pass

    def render(self, format='application/json', ):
        report_type = self.report_type_class.__name__.lower()
        renderer_class = self._renderer_map[format]
        renderer = renderer_class(self._queryset, report_type)
        return renderer.render(self.base_context)


class ProductTypeReportCreator(GenericReportCreator):
    report_type_class = Product_Type

    def populate(self, product_type, **context_kwargs):
        super(ProductTypeReportCreator, self).populate(**context_kwargs)

        # context_kwargs was request.GET
        findings = ReportFindingFilter(context_kwargs,
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
            'findings': findings.qs,

            'endpoint_opened_per_month': opened_per_period,
            'endpoint_active_findings': findings.qs,
        })


class ProductReportCreator(GenericReportCreator):
    report_type_class = Product

    def add_authorizing_filter(self, user):
        self._queryset = self._queryset.filter(authorized_users=user)

    def populate(self, product, **context_kwargs):
        super(ProductReportCreator, self).populate(**context_kwargs)

        findings = ReportFindingFilter(context_kwargs,
                                       queryset=Finding.objects.filter(
                                           test__engagement__product=product).distinct().prefetch_related(
                                           'test',
                                           'test__engagement__product',
                                           'test__engagement__product__prod_type'))
        engagements = Engagement.objects.filter(
            test__finding__in=findings.qs).distinct()
        tests = Test.objects.filter(finding__in=findings.qs).distinct()
        self.base_context.update({
            'product': product,
            'engagements': engagements,
            'tests': tests,
            'findings': findings.qs,
        })


class EngagementReportCreator(GenericReportCreator):
    report_type_class = Engagement

    def populate(self, engagement, **context_kwargs):
        super(EngagementReportCreator, self).populate(**context_kwargs)
        findings = ReportFindingFilter(context_kwargs,
                                       queryset=Finding.objects.filter(
                                           test__engagement=engagement,
                                       ).prefetch_related('test',
                                                          'test__engagement__product',
                                                          'test__engagement__product__prod_type').distinct())
        tests = Test.objects.filter(finding__in=findings.qs).distinct()
        self.base_context.update({
            'engagement': engagement,
            'tests': tests,
            'findings': findings.qs,
        })


class TestReportCreator(GenericReportCreator):
    report_type_class = Test
    test_instance = None

    def populate(self, test, **context_kwargs):
        self.test_instance = test
        super(TestReportCreator, self).populate(**context_kwargs)
        findings = ReportFindingFilter(context_kwargs,
                                       queryset=Finding.objects.filter(
                                           test=test).prefetch_related('test',
                                                                       'test__engagement__product',
                                                                       'test__engagement__product__prod_type').distinct())
        self.base_context.update({
            'test': test,
            'findings': findings.qs,
        })

    @property
    def report_subtitle(self):
        return str(self.test_instance)


class EndpointReportCreator(GenericReportCreator):
    report_type_class = Endpoint
    endpoint_instance = None

    def add_authorizing_filter(self, user):
        self._queryset = self._queryset.filter(product__authorized_users=user)

    def populate(self, endpoint, **context_kwargs):
        self.endpoint_instance = endpoint
        super(EndpointReportCreator, self).populate(**context_kwargs)
        host = endpoint.host_no_port
        endpoints = Endpoint.objects.filter(host__regex="^" + host + ":?",
                                            product=endpoint.product).distinct()
        findings = ReportFindingFilter(context_kwargs,
                                       queryset=Finding.objects.filter(
                                           endpoints__in=endpoints,
                                       ).prefetch_related('test',
                                                          'test__engagement__product',
                                                          'test__engagement__product__prod_type').distinct())
        self.base_context.update({
            'endpoint': endpoint,
            'endpoints': endpoints,
            'findings': findings.qs,
        })

    @property
    def report_subtitle(self):
        return self.endpoint_instance.host_no_port


class FindingReportCreator(GenericReportCreator):
    report_type_class = Finding

    def populate(self, finding_qs, **context_kwargs):
        super(FindingReportCreator, self).populate(**context_kwargs)
        findings = ReportAuthedFindingFilter(context_kwargs,
                                             queryset=finding_qs.prefetch_related(
                                                 'test',
                                                 'test__engagement__product',
                                                 'test__engagement__product__prod_type').distinct(),
                                             user=self.user)
        self.base_context.update({
            'findings': findings.qs,
        })

    @property
    def report_subtitle(self):
        return ""


_report_creator_map = {
    Product_Type: ProductTypeReportCreator,
    Product: ProductReportCreator,
    Engagement: EngagementReportCreator,
    Test: TestReportCreator,
    Endpoint: EndpointReportCreator,
    Finding: FindingReportCreator,
}


def get_report_creator_class(model_class):
    """
    Returns a ReportCreator class.
    Raises a KeyError if not found.

    :param model_class:
    :return:
    """
    return _report_creator_map[model_class]
