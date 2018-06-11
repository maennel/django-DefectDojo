import logging

from django.contrib.auth.mixins import LoginRequiredMixin
from django.views import View

from dojo.models import Product, Endpoint, Engagement, Product_Type, Test

logger = logging.getLogger(__name__)

class ReportCreationView(LoginRequiredMixin, View):
    def generate_report(self, request, reportable_class, report_filter):
        if reportable_class is Product:
            pass
        elif reportable_class is Endpoint:
            pass
        elif reportable_class is Engagement:
            pass
        elif reportable_class is Product_Type:
            pass
        elif reportable_class is Test:
            pass
        else:
            msg = "Unsupported report type '%s' requested" % reportable_class.__name__
            logger.error(msg)
            raise ValueError(msg)
