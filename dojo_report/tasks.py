from __future__ import unicode_literals

from celery.utils.log import get_task_logger

from dojo.celery import app

logger = get_task_logger(__name__)


@app.task
def create_report(format, filter_params, template=None, filename='report',
                  report_title="Report", report_subtitle="", report_info="",
                  context={}):
    pass
