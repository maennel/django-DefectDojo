from __future__ import absolute_import
from __future__ import unicode_literals

import tempfile
from datetime import timedelta

import pdfkit
from celery.utils.log import get_task_logger
from django.conf import settings
from django.core.files.base import ContentFile
from django.core.urlresolvers import reverse
from django.db.models import Count
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.http import urlencode

from dojo.celery import app
from dojo.models import Finding, Engagement, System_Settings
from dojo.reports.widgets import report_widget_factory
from dojo.utils import add_comment, add_epic, add_issue, update_epic, \
    update_issue, \
    close_epic, create_notification
from dojo.utils import sync_dedupe, sync_false_history

logger = get_task_logger(__name__)


# Logs the error to the alerts table, which appears in the notification toolbar
def log_generic_alert(source, title, description):
    create_notification(event='other', title=title, description=description,
                        icon='bullseye', source=source)


@app.task(bind=True)
def add_alerts(self, runinterval):
    now = timezone.now()

    upcoming_engagements = Engagement.objects.filter(
        target_start__gt=now + timedelta(days=3),
        target_start__lt=now + timedelta(days=3) + runinterval).order_by(
        'target_start')
    for engagement in upcoming_engagements:
        create_notification(event='upcoming_engagement',
                            title='Upcoming engagement: %s' % engagement.name,
                            engagement=engagement,
                            recipients=[engagement.lead],
                            url=reverse('view_engagement',
                                        args=(engagement.id,)))

        stale_engagements = Engagement.objects.filter(
            target_start__gt=now - runinterval,
            target_end__lt=now,
            status='In Progress').order_by('-target_end')
    for eng in stale_engagements:
        create_notification(event='stale_engagement',
                            title='Stale Engagement: %s' % eng.name,
                            description='The engagement "%s" is stale. Target end was %s.' % (
                                eng.name,
                                eng.target_end.strftime("%b. %d, %Y")),
                            url=reverse('view_engagement', args=(eng.id,)),
                            recipients=[eng.lead])


@app.task(bind=True)
def async_pdf_report(self,
                     report=None,
                     template="None",
                     filename='report.pdf',
                     report_title=None,
                     report_subtitle=None,
                     report_info=None,
                     context={},
                     uri=None):
    xsl_style_sheet = settings.DOJO_ROOT + "/static/dojo/xsl/pdf_toc.xsl"
    x = urlencode({'title': report_title,
                   'subtitle': report_subtitle,
                   'info': report_info})

    cover = context['host'] + reverse(
        'report_cover_page') + "?" + x

    try:
        config = pdfkit.configuration(wkhtmltopdf=settings.WKHTMLTOPDF_PATH)
        report.task_id = async_pdf_report.request.id
        report.save()
        bytes = render_to_string(template, context)
        itoc = context['include_table_of_contents']
        if itoc:
            toc = {'xsl-style-sheet': xsl_style_sheet}
        else:
            toc = None
        pdf = pdfkit.from_string(bytes,
                                 False,
                                 configuration=config,
                                 cover=cover,
                                 toc=toc)
        if report.file.name:
            with open(report.file.path, 'w') as f:
                f.write(pdf)
            f.close()
        else:
            f = ContentFile(pdf)
            report.file.save(filename, f)
        report.status = 'success'
        report.done_datetime = timezone.now()
        report.save()

        create_notification(event='report_created', title='Report created',
                            description='The report "%s" is ready.' % report.name,
                            url=uri, report=report, objowner=report.requester)
    except IOError as e:
        report.status = 'error'
        report.save()
        logger.error(
            "Report creation failure - make sure WKHTMLTOPDF is "
            "installed. %s" % str(e))
        log_generic_alert("PDF Report", "Report Creation Failure",
                          "Something went terribly wrong. " + str(e))
    except Exception as e:
        report.status = 'error'
        report.save()
        log_generic_alert("PDF Report", "Report Creation Failure",
                          "Make sure WKHTMLTOPDF is installed. " + str(e))
    return True


@app.task(bind=True)
def async_custom_pdf_report(self,
                            report=None,
                            template="None",
                            filename='report.pdf',
                            host=None,
                            user=None,
                            uri=None,
                            finding_notes=False,
                            finding_images=False):
    config = pdfkit.configuration(wkhtmltopdf=settings.WKHTMLTOPDF_PATH)

    selected_widgets = report_widget_factory(json_data=report.options,
                                             request=None, user=user,
                                             finding_notes=finding_notes,
                                             finding_images=finding_images,
                                             host=host)

    widgets = selected_widgets.values()
    temp = None

    try:
        report.task_id = async_custom_pdf_report.request.id
        report.save()

        toc = None
        toc_depth = 4

        if 'table-of-contents' in selected_widgets:
            xsl_style_sheet_tempalte = "dojo/pdf_toc.xsl"
            temp = tempfile.NamedTemporaryFile()

            toc_settings = selected_widgets['table-of-contents']

            toc_depth = toc_settings.depth
            toc_bytes = render_to_string(xsl_style_sheet_tempalte,
                                         {'widgets': widgets,
                                          'depth': toc_depth,
                                          'title': toc_settings.title})
            temp.write(toc_bytes)
            temp.seek(0)

            toc = {'toc-header-text': toc_settings.title,
                   'xsl-style-sheet': temp.name}

        # default the cover to not come first by default
        cover_first_val = False

        cover = None
        if 'cover-page' in selected_widgets:
            cover_first_val = True
            cp = selected_widgets['cover-page']
            x = urlencode({'title': cp.title,
                           'subtitle': cp.sub_heading,
                           'info': cp.meta_info})
            cover = host + reverse(
                'report_cover_page') + "?" + x
        bytes = render_to_string(template, {'widgets': widgets,
                                            'toc_depth': toc_depth,
                                            'host': host,
                                            'report_name': report.name})
        pdf = pdfkit.from_string(bytes,
                                 False,
                                 configuration=config,
                                 toc=toc,
                                 cover=cover,
                                 cover_first=cover_first_val)

        if report.file.name:
            with open(report.file.path, 'w') as f:
                f.write(pdf)
            f.close()
        else:
            f = ContentFile(pdf)
            report.file.save(filename, f)
        report.status = 'success'
        report.done_datetime = timezone.now()
        report.save()

        create_notification(event='report_created', title='Report created',
                            description='The report "%s" is ready.' % report.name,
                            url=uri, report=report, objowner=report.requester)
    except Exception as e:
        report.status = 'error'
        report.save()
        # email_requester(report, uri, error=e)
        # raise e
        log_generic_alert("PDF Report", "Report Creation Failure",
                          "Make sure WKHTMLTOPDF is installed. " + str(e))
    finally:
        if temp is not None:
            # deleting temp xsl file
            temp.close()

    return True


@app.task(name='add_issue_task')
def add_issue_task(find, push_to_jira):
    logger.info("add issue task")
    add_issue(find, push_to_jira)


@app.task(name='update_issue_task')
def update_issue_task(find, old_status, push_to_jira):
    logger.info("add issue task")
    update_issue(find, old_status, push_to_jira)


@app.task(name='add_epic_task')
def add_epic_task(eng, push_to_jira):
    logger.info("add epic task")
    add_epic(eng, push_to_jira)


@app.task(name='update_epic_task')
def update_epic_task(eng, push_to_jira):
    logger.info("update epic task")
    update_epic(eng, push_to_jira)


@app.task(name='close_epic_task')
def close_epic_task(eng, push_to_jira):
    logger.info("close epic task")
    close_epic(eng, push_to_jira)


@app.task(name='add comment')
def add_comment_task(find, note):
    logger.info("add comment")
    add_comment(find, note)


@app.task(name='async_dedupe')
def async_dedupe(new_finding, *args, **kwargs):
    logger.info("running deduplication")
    sync_dedupe(new_finding, *args, **kwargs)


@app.task(name='async_false_history')
def async_false_history(new_finding, *args, **kwargs):
    logger.info("running false_history")
    sync_false_history(new_finding, *args, **kwargs)


@app.task(bind=True)
def async_dupe_delete(*args, **kwargs):
    logger.info("delete excess duplicates")
    system_settings = System_Settings.objects.get()
    if system_settings.delete_dupulicates:
        dupe_max = system_settings.max_dupes
        findings = Finding.objects.all().annotate(
            num_dupes=Count('duplicate_list')).filter(num_dupes__gt=dupe_max)
        for finding in findings:
            duplicate_list = finding.duplicate_list.all().order_by(
                'date').all()
            dupe_count = len(duplicate_list) - dupe_max
            for finding in duplicate_list:
                finding.delete()
                dupe_count = dupe_count - 1
                if dupe_count == 0:
                    break
