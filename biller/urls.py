from django.contrib import admin
from django.urls import path, include
from django.shortcuts import redirect
from django.conf import settings
from django.conf.urls.static import static
from django.contrib.auth import logout 

def root_redirect(request):
    return redirect("/billing/dashboard/")

def custom_logout(request):
    logout(request)
    return redirect('/admin/')

urlpatterns = [
    path("", root_redirect),
    path("admin/", admin.site.urls),
    path('logout/', custom_logout, name='logout'),
    path("billing/", include("billing.urls")),
    path('manifest/', include('manifest.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)