from django.urls import path
from . import views

urlpatterns = [
    path('', views.upload_manifest, name='upload_manifest'),
    path('scan/', views.scan_docket, name='scan_docket'),
    path('missing/', views.missing_dockets, name='missing_dockets'),
    path('missing/download/', views.download_missing_excel, name='download_missing_excel'),
    path('download/', views.download_excel, name='download_excel'),
    path('merge-excel/', views.merge_excel, name='merge_excel'),

]

