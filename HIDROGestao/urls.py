from django.contrib import admin
from django.urls import path, include
from gestao_contratos import views
from gestao_contratos.downloads import private_download

urlpatterns = [
    path("admin/", admin.site.urls),
    path('', include('gestao_contratos.urls')),
    path('', views.home, name='home'),
    path('accounts/', include('django.contrib.auth.urls')),
    path('arquivos/<path:name>', private_download, name='private_download'),
    path('media/<path:name>', private_download, name='legacy_private_download'),


]
