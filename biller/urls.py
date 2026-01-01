from django.contrib import admin
from django.urls import path, include
from django.shortcuts import redirect
from django.conf import settings
from django.conf.urls.static import static

def root_redirect(request):
    return redirect("/billing/dashboard/")

urlpatterns = [
    path("", root_redirect),
    path("admin/", admin.site.urls),
    path("billing/", include("billing.urls")),
    path('manifest/', include('manifest.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
