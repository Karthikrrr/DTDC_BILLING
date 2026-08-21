from django.urls import path
from . import views

app_name = 'billing'

urlpatterns = [
    path('dashboard/', views.dashboard, name='dashboard'),
    path('upload/monthly/', views.upload_monthly, name='upload_monthly'),
    path('download/report/', views.download_report_page, name='download_report_page'),


    path(
        "invoice/by-invoice/<int:invoice_id>/",
        views.invoice_preview_by_invoice,
        name="invoice_preview_by_invoice"
    ),
    

    path('update/bill/', views.update_bill_data, name='update_bill_data'),
    path('create/bill/', views.create_bill, name='create_bill'),
    path('delete/bill/', views.delete_bill, name='delete_bill'),
    path('clear/edits/', views.clear_edits, name='clear_edits'),
    path('generate/final/pdf/', views.invoice_generate_final_pdf, name='invoice_generate_final_pdf'),
    path('generate/pdf/', views.generate_pdf, name='generate_pdf'),
    path("recalculate/bill/", views.recalculate_bill, name="recalculate_bill"),
    path("download/finaldetails/", views.download_FinalDetails_excel, name='download_details'),
]
