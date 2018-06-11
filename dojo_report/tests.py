from datetime import datetime

from django.test import TestCase
from pandas._libs import json

from dojo.models import Finding, Dojo_User, Product_Type, Product, Engagement, \
    Test, Test_Type, System_Settings
from dojo_report.utils import JsonReportRenderer, AsciiReportRenderer, \
    ProductTypeReportCreator


class ReportRenderingTests(TestCase):
    def test_render_basic_json_report(self):
        report_data = {
            'title': 'My Report',
            'subtitle': 'bugs everywhere',
            'findings': [
                {
                    'title': 'A vulnerability',
                    'cwe': 'whoot?',
                    'description': 'the worst vuln ever',
                }
            ]
        }
        qs = Finding.objects.all()
        renderer = JsonReportRenderer(qs, initial_context=report_data)
        rendered_data = renderer.render()
        self.assertTrue(rendered_data)

    def test_render_basic_html_report(self):
        report_data = {
            'title': 'My Report',
            'subtitle': 'bugs everywhere',
            'findings': [
                {
                    'title': 'A vulnerability',
                    'cwe': 'whoot?',
                    'description': 'the worst vuln ever',
                }
            ]
        }
        qs = Finding.objects.all()
        renderer = AsciiReportRenderer(qs, initial_context=report_data)
        rendered_data = renderer.render()
        self.assertTrue(rendered_data)


class ReportCreationTests(TestCase):
    default_format = 'application/json'

    def setUp(self):
        # We need a System_Settings object to be present
        System_Settings.objects.create()

        self.reporter = Dojo_User.objects.create_user(username='reporter-user')
        self.prod_type = Product_Type.objects.create(name="Web")
        self.prod = Product.objects.create(name="MyWebProduct",
                                           prod_type=self.prod_type)
        self.engagement = Engagement.objects.create(name="Rockin' engagement",
                                                    target_start=datetime.now(),
                                                    target_end=datetime.now(),
                                                    product=self.prod)
        self.test_type = Test_Type.objects.create(name='SuperSAST',
                                                  static_tool=True)
        self.test = Test.objects.create(engagement=self.engagement,
                                        target_start=datetime.now(),
                                        target_end=datetime.now(),
                                        test_type=self.test_type)
        self.findings = [
            Finding.objects.create(title='Voodoo magic happened',
                                   date=datetime.now(), cwe=123,
                                   severity='High', test=self.test,
                                   reporter=self.reporter),
            Finding.objects.create(title='No one is around',
                                   date=datetime.now(), cwe=124,
                                   severity='High', test=self.test,
                                   reporter=self.reporter),
        ]

        self.report_creation_user = Dojo_User.objects.create_user(username='abc',
                                                      first_name='foo',
                                                      last_name='bar')

    def test_create_product_type_report(self):
        # Initialize report creation
        creator = ProductTypeReportCreator(user=self.report_creation_user,
                                           host='host.local',
                                           parameters={})
        creator.populate(self.prod_type)
        json_rendered_report = creator.render(format='application/json')

        # Verify everything went well
        self.assertTrue(json_rendered_report)
        report = json.loads(json_rendered_report)
        self.assertEqual(2, len(report['findings']))
        self.assertEqual("Product_Type Report", report['title'])
        self.assertEqual("Web", report['product_type']['name'])
        self.assertEqual(1, len(report['products']))
        self.assertEqual("MyWebProduct", report['products'][0]['name'])
        self.assertEqual(1, len(report['engagements']))
        self.assertEqual("Rockin' engagement",
                         report['engagements'][0]['name'])
        self.assertEqual(1, len(report['tests']))
        self.assertEqual("SuperSAST", report['tests'][0]['test_type']['name'])