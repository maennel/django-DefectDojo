import logging
from datetime import datetime

from dateutil import relativedelta
from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.utils import timezone

from dojo.filters import ReportFindingFilter
from dojo.models import Product_Type, Product, Engagement, Test, Endpoint, \
    Finding
from dojo.utils import get_period_counts_legacy
from dojo_report.renderers import JsonReportRenderer, PdfReportRenderer, \
    AsciiReportRenderer

logger = logging.getLogger(__name__)


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
