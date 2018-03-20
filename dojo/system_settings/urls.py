from django.conf.urls import url

from dojo.system_settings import views

urlpatterns = [
    url(r'^system_settings$', views.system_settings, name='system_settings')
]
