from django.contrib import admin
from .models import Company, Bill, FinalDetails, Invoice, PincodeFile


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "created_at")
    search_fields = ("name",)


@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "rule_file", "active", "created_at")
    search_fields = ("name",)
    list_filter = ("active",)
    ordering = ("id",)


@admin.register(PincodeFile)
class PincodeFileAdmin(admin.ModelAdmin):
    list_display = ("id", "file", "uploaded_at")
    ordering = ("id",)

@admin.register(FinalDetails)
class FinalDetailsAdmin(admin.ModelAdmin):
    list_display = ("id", "company_name", "inv_date", "inv_number", "cgst", "sgst", "igst", "grand_total")
    search_fields = (
            "company_name","inv_number"
        )
    ordering = ("id",)

@admin.register(Bill)
class BillAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "company",
        "invoice",
        "docket_no",
        "date",
        "destination",
        "segment",
        "amount",
        "month",
    )

    search_fields = (
        "docket_no",
        "destination",
        "segment",
        "invoice__name",
        "company__name",
    )

    list_filter = (
        "invoice__name",
        "company__name",
    )

    list_select_related = ("company", "invoice")
    ordering = ("-id",)
