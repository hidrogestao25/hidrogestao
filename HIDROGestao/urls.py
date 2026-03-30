from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import path, include
from gestao_contratos import views
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path("admin/", admin.site.urls),
    path('', include('gestao_contratos.urls')),
    path('', views.home, name='home'),
    path('accounts/', include('django.contrib.auth.urls')),


]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
