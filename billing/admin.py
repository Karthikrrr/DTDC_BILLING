from django.contrib import admin
from .models import Company, Bill, PincodeFile


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


@admin.register(Bill)
class BillAdmin(admin.ModelAdmin):
    list_display = ("id", "company", "docket_no", "date", "destination", "segment", "amount", "month")
    search_fields = ("docket_no", "destination", "segment")
    list_filter = ("company", "month")
    ordering = ("id",)
